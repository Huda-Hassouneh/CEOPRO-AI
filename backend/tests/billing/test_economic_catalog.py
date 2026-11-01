"""Catalog reconciliation and source-backed coverage; disposable PostgreSQL only."""
from copy import deepcopy
from decimal import Decimal

import pytest
from psycopg2 import errors

from src.ai.billing import economic_catalog, plan_analysis, plan_studio
from .test_plan_studio import fixture, policy_body
from .test_provider_accounting_db import owner_client, rows  # noqa: F401


def test_readiness_keeps_price_credentials_approval_and_availability_separate():
    schedules = [dict(budget_kind='ai', provider='groq', operation='openai/gpt-oss-20b', unit=u,
        unit_cost_usd='0.000000075', verified_at='2026-10-28', source='Approved catalog', cost_is_final=True,
        configured_by='ai-provider-pricing-v1') for u in ['input_token', 'output_token']]
    result = economic_catalog.readiness(schedules, {}, '2026-10-31')
    groq = next(r for r in result['providers'] if r['provider']=='groq')
    assert all(r['status']=='VERIFIED' and r['provenance']=='catalog/bootstrap' for r in groq['rates'])
    assert groq['credential_status']=='MISSING' and groq['operational_status']=='UNVERIFIED'
    assert not any(a['present'] for a in result['approvals'])
    result = economic_catalog.readiness([], {'TAVILY_API_KEY':'secret-test-only','PLACES_TERMS_APPROVAL_REFERENCE':'secret-reference'}, '2026-10-31')
    tavily = next(r for r in result['providers'] if r['provider']=='tavily')
    assert tavily['credential_status']=='PRESENT_UNTESTED' and tavily['rates'][0]['status']=='MISSING'
    assert 'secret' not in str(result)


def test_dynamic_models_aliases_and_unverified_free_rates_are_not_invented():
    result=economic_catalog.readiness([], {'GROQ_MODEL':'new-model','APIFY_TOKEN':'test','GOOGLE_MAPS_API_KEY':'test'}, '2026-10-31')
    providers={p['provider']:p for p in result['providers']}
    assert providers['groq']['operation']=='new-model' and providers['groq']['rates'][0]['status']=='MISSING'
    assert providers['apify']['credential_status']==providers['google_places']['credential_status']=='PRESENT_UNTESTED'
    rate=dict(budget_kind='ai',provider='gemini',operation='image_generation',unit='image',unit_cost_usd='0',
              verified_at=None,source='Conditional free tier',cost_is_final=True,configured_by='migration 20261022000000')
    assert next(p for p in economic_catalog.readiness([rate], {}, '2026-10-31')['providers'] if p['provider']=='gemini')['rates'][0]['status']=='UNVERIFIED'


def test_runtime_coverage_is_not_a_second_price_and_cannot_double_count():
    plan, policy, sources=fixture()
    sources['feature_economics']=economic_catalog.coverage()
    policy['assumptions']['feature_treatments']={}
    before=deepcopy(policy)
    result=plan_analysis.analyze(plan,policy,sources)
    assert result['costs']['expected']==Decimal('4.00') # 2 pools *100*.01*.5 + internal3
    assert result['rateEvidence']==[] and result['pricing'] is not None
    assert policy==before
    for code in ['rag_assistant','web_searches','marketing_image_generation','competitor_management','market_intelligence']:
        plan['entitlements']=[code]
        policy['assumptions']['feature_treatments']={code:'additional_external'}
        failed=plan_analysis.analyze(plan,policy,sources)
        assert failed['pricing'] is None and 'CREDIT_COVERAGE_CONFLICT:'+code in failed['warnings']


def test_unknown_feature_and_missing_policy_still_fail_closed():
    plan,policy,sources=fixture();sources['feature_economics']=economic_catalog.coverage()
    plan['entitlements'].append('unknown_future_feature')
    assert 'COST_COVERAGE_MISSING:unknown_future_feature' in plan_analysis.analyze(plan,policy,sources)['warnings']
    assert plan_analysis.analyze(plan,None,sources)['pricing'] is None


def test_provider_wildcard_precedence_and_owner_staleness_policy():
    base=dict(budget_kind='ai',provider='groq',unit='input_token',source='Owner verified',
              cost_is_final=True,configured_by='owner',verified_at='2026-10-01')
    rates=[dict(base,operation='*',unit_cost_usd='0.1'),
           dict(base,operation='openai/gpt-oss-20b',unit_cost_usd=None)]
    def status(rows, **kwargs):
        return next(p for p in economic_catalog.readiness(rows, {}, '2026-10-31', **kwargs)['providers'] if p['provider']=='groq')['rates'][0]['status']
    assert status(rates)=='MISSING' # exact deliberately unpriced beats wildcard
    assert status(rates[:1])=='VERIFIED'
    assert status(rates[:1],max_rate_age_days=10)=='STALE'


def test_setup_reconciliation_preserves_any_owner_values_and_is_idempotent(owner_db):
    # Roll back every synthetic edit. Never connect to the normal application DB.
    with owner_db.cursor() as cur:
        cur.execute('BEGIN')
        cur.execute('SAVEPOINT catalog_test')
        try:
            financial_tables=['usage_plans','usage_plan_limits','billing_plan_prices','billing_subscriptions',
                              'billing_payments','tenant_plan_assignments','tenant_credit_balances','billing_custom_cost_rates']
            def financial_snapshot():
                return [rows(owner_db,'SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text')
                        for table in financial_tables]
            financial=financial_snapshot()
            # Removal after the older approved migration is also authoritative.
            cur.execute("DELETE FROM provider_cost_schedules WHERE provider='groq'")
            cur.execute('SELECT billing_catalog_reconcile()')
            assert rows(owner_db,"SELECT count(*) FROM provider_cost_schedules WHERE provider='groq'")==[(0,)]
            # Exercise a genuinely new canonical key without deleting or
            # disabling append-only historical receipts. Synthetic DB only.
            cur.execute("SELECT pg_get_functiondef('billing_catalog_reconcile()'::regprocedure)")
            cur.execute(cur.fetchone()[0].replace("'groq'", "'synthetic_catalog_groq'"))
            cur.execute('SELECT billing_catalog_reconcile()')
            got=rows(owner_db,"SELECT provider,unit,unit_cost_usd,verified_at,configured_by FROM provider_cost_schedules WHERE provider IN ('synthetic_catalog_groq','serpapi','gemini_vision') ORDER BY provider,unit")
            assert len(got)==4 and sum(r[2] is None for r in got)==2
            assert sum(r[3] is not None for r in got)==2
            cur.execute("UPDATE provider_cost_schedules SET unit_cost_usd=NULL,configured_by='owner deliberate disable',source='Owner',verified_at=NULL WHERE provider='synthetic_catalog_groq'")
            before=rows(owner_db,'SELECT row_to_json(p)::text FROM provider_cost_schedules p ORDER BY schedule_id')
            audits=rows(owner_db,'SELECT row_to_json(a)::text FROM entitlement_audit_log a ORDER BY audit_id')
            for _ in range(3):cur.execute('SELECT billing_catalog_reconcile()')
            assert rows(owner_db,'SELECT row_to_json(p)::text FROM provider_cost_schedules p ORDER BY schedule_id')==before
            assert rows(owner_db,'SELECT row_to_json(a)::text FROM entitlement_audit_log a ORDER BY audit_id')==audits
            # A changed catalog must not supersede existing financial evidence.
            cur.execute("SELECT pg_get_functiondef('billing_catalog_reconcile()'::regprocedure)")
            future=cur.fetchone()[0].replace('billing-catalog-2026-10-v1','billing-catalog-test-v2').replace('0.075', '9.999')
            cur.execute(future)
            cur.execute('SELECT billing_catalog_reconcile()')
            assert rows(owner_db,'SELECT row_to_json(p)::text FROM provider_cost_schedules p ORDER BY schedule_id')==before
            assert rows(owner_db,'SELECT row_to_json(a)::text FROM entitlement_audit_log a ORDER BY audit_id')==audits
            assert financial_snapshot()==financial
        finally:cur.execute('ROLLBACK')


@pytest.mark.parametrize('role',['ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting'])
def test_runtime_roles_cannot_bootstrap(owner_db,role):
    with owner_db.cursor() as cur:
        cur.execute('BEGIN')
        cur.execute('SAVEPOINT catalog_denial')
        try:
            cur.execute('SET LOCAL ROLE '+role)
            with pytest.raises(errors.InsufficientPrivilege):cur.execute('SELECT billing_catalog_reconcile()')
        finally:cur.execute('ROLLBACK')


def test_owner_studio_evidence_uses_canonical_coverage_without_writing_plan(owner_client, owner_db):
    client,_=owner_client
    before=rows(owner_db,'SELECT row_to_json(p)::text FROM usage_plan_limits p ORDER BY plan_key,feature_code')
    data=client.get('/platform/billing/pricing-studio').json()
    assert set(data['feature_economics'])==set(economic_catalog.FEATURES)
    body=policy_body(data);body['assumptions']['feature_treatments']={}
    created=client.post('/platform/billing/pricing-studio/policies',json=body)
    assert created.status_code==201,created.text
    result=client.post('/platform/billing/pricing-studio/analyze',json={'plan_key':'starter'}).json()
    assert result['pricing'] is not None,result['warnings']
    assert result['evidence']['featureEconomics']['rag_assistant']['catalog_version']==economic_catalog.VERSION
    assert rows(owner_db,'SELECT row_to_json(p)::text FROM usage_plan_limits p ORDER BY plan_key,feature_code')==before
