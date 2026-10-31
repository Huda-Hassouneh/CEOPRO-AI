"""Synthetic explicit assumptions; no fixture constitutes commercial policy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from psycopg2 import errors

from src.ai.billing import plan_analysis, plan_studio
from .test_provider_accounting_db import owner_client, rows  # noqa: F401

URL = '/platform/billing/pricing-studio'


def assumptions():
    return dict(target_margin='.4', minimum_margin='.2', risk_buffer='.1', expected_utilization='.5', stress_utilization='1',
        infrastructure_jod='1', support_jod='1', operations_jod='1', processing_ratio='.05', processing_fixed_jod='.5',
        annual_discount='.1', annual_allowance_cycles=12, rounding_jod='.01', usd_to_jod='1',
        fx_source='SYNTHETIC ONLY', fx_version='test-v1', max_rate_age_days=90,
        feature_treatments={'monthly_reports': 'additional_external', 'tracked_products': 'internal_allocation',
                            'rag_assistant': 'ai_credits'}, unlimited_monthly_usage={}, cost_binding_policy_id=None)


def fixture():
    plan = dict(plan_key='starter', display_name='Standard', tier_level=1, currency='USD', monthly_price='20',
        feature_limits=[dict(feature_code=c, limit_value=q, reset_cycle='billing_period', aggregation_type='sum')
                        for c,q in [('ai_credits',100),('data_credits',100),('monthly_reports',5),('tracked_products',10)]],
        entitlements=['rag_assistant'], prices=[dict(amount='20',currency='USD',interval_months=1,period_code='monthly'),
                                               dict(amount='54',currency='USD',interval_months=3,period_code='three-months')])
    now = datetime.now(timezone.utc)
    sources = dict(as_of=now.isoformat(), credit_policy={'credit_usd_value': '.01'}, bindings=[
        dict(binding_id=str(uuid4()), feature_code='monthly_reports', rate_id=str(uuid4()), unit_cost_usd='.2',
             verified_at=now.date().isoformat(), cost_is_final=True, rate_source='SYNTHETIC invoice',
             cost_category='vendor', budget_kind='data', provider='test', operation='report', unit='request',
             usage_basis='limit_value', units_per_feature_unit='1', operational_multiplier='1', variability_reserve='1', usage_assumption={})])
    return plan, {'policy_id':str(uuid4()),'version':1,'assumptions':assumptions()}, sources


def test_deterministic_cost_price_margin_and_actual_period_contract():
    plan, policy, sources = fixture()
    result = plan_analysis.analyze(plan, policy, sources)
    assert result['costs']['expected'] == Decimal('4.50')
    assert result['costs']['stress'] == Decimal('6.00')
    assert result['pricing']['breakEven'] == Decimal('5.26')
    assert result['pricing']['safeMinimum'] == Decimal('9.47')
    assert result['pricing']['target'] == result['pricing']['recommended'] == Decimal('9.91')
    assert result['pricing']['contribution'] == Decimal('14.00')
    assert result['pricing']['expectedMargin'] == Decimal('.7')
    assert result['periods'][1]['expectedCost'] == Decimal('10.50')
    assert result['annual']['discountedCandidate'] == Decimal('107.03')
    assert result['status'] == 'SAFE'


@pytest.mark.parametrize('change,reason', [({'unit_cost_usd':None},'RATE_MISSING'), ({'verified_at':None},'RATE_UNVERIFIED'),
    ({'cost_is_final':False},'RATE_UNVERIFIED'), ({'rate_source':''},'RATE_UNVERIFIED'),
    ({'verified_at':'2000-01-01'},'RATE_STALE')])
def test_missing_unverified_stale_costs_never_become_zero_cost_recommendations(change, reason):
    plan, policy, sources = fixture()
    sources['bindings'][0].update(change)
    result = plan_analysis.analyze(plan, policy, sources)
    assert result['status'] == 'INCOMPLETE_DATA' and result['pricing'] is None
    assert reason + ':monthly_reports' in result['warnings']
    assert result['costs']['knownSubtotalOnly']


def test_coverage_prevents_credit_double_counting_and_simulation_is_pure():
    plan, policy, sources = fixture()
    policy['assumptions']['feature_treatments']['monthly_reports'] = 'data_credits'
    before = deepcopy(plan)
    result = plan_analysis.analyze(plan, policy, sources, {'limits':{'ai_credits':200}})
    assert result['costs']['expected'] == Decimal('4.50')  # .5*200*.01 + .5*100*.01 + internal3
    assert result['rateEvidence'] == []
    assert plan == before and result['plan']['feature_limits'][0]['limit_value'] == 200


def test_missing_policy_mapping_unlimited_and_fx_precision():
    plan, policy, sources = fixture()
    assert plan_analysis.analyze(plan, None, sources)['pricing'] is None
    del policy['assumptions']['feature_treatments']['monthly_reports']
    assert 'COST_COVERAGE_MISSING:monthly_reports' in plan_analysis.analyze(plan,policy,sources)['warnings']
    policy['assumptions']['feature_treatments']['monthly_reports'] = 'additional_external'
    plan['feature_limits'][2]['limit_value'] = None
    assert 'UNBOUNDED_USAGE:monthly_reports' in plan_analysis.analyze(plan,policy,sources)['warnings']
    plan['feature_limits'][2]['limit_value'] = 5
    policy['assumptions']['usd_to_jod'] = '.709'
    result = plan_analysis.analyze(plan,policy,sources)
    assert result['pricing']['currentJod'] == Decimal('14.180')


def test_micro_costs_remain_decimal_until_final_money_rounding():
    plan, policy, sources = fixture()
    sources['bindings'][0]['unit_cost_usd'] = '.001'
    result = plan_analysis.analyze(plan,policy,sources)
    # .005 external * .5 utilization + credit1 + internal3, not rounded .01*.5.
    assert next(r for r in result['costs']['breakdown'] if r['feature']=='monthly_reports')['expected'] == Decimal('.0025')


def test_negative_margin_unsafe_annual_discount_and_neighbor_ladder_are_visible():
    plan, policy, sources = fixture()
    plan['prices'][0]['amount'] = '1'
    policy['assumptions']['annual_discount'] = '.9'
    low = plan_analysis.analyze(plan,policy,sources)
    assert low['pricing']['expectedMargin'] < 0
    assert {'CURRENT_PRICE_UNSAFE','ANNUAL_DISCOUNT_UNSAFE'} <= set(low['warnings'])
    high_plan = deepcopy(plan)
    high_plan.update(plan_key='growth',tier_level=2)
    high_plan['feature_limits'][0]['limit_value'] *= 10
    high_plan['prices'][0]['amount'] = '1.01'
    policy['assumptions']['ladder_min_price_gap'] = '.1'
    high = plan_analysis.analyze(high_plan,policy,sources)
    assert {w['code'] for w in plan_analysis.ladder([low,high],policy)} == {'WEAK_PRICE_GAP_FOR_COST_INCREASE','COST_GROWS_FASTER_THAN_PRICE'}


def test_canonical_ladder_uses_catalog_membership_and_order_not_legacy_or_draft_tiers():
    plan, policy, sources = fixture()
    analyses = []
    # Mutable administration tier levels and input order must not change the
    # canonical sequence. Cheap compatibility/draft rows would cause warnings.
    for key, tier, price in [('enterprise',1,'10'), ('pro',2,'1'), ('basic',1,'1'),
                             ('growth',9,'20'), ('standard',1,'1'), ('starter',8,'30')]:
        p = deepcopy(plan)
        p.update(plan_key=key, tier_level=tier, is_active=key!='growth')
        p['prices'][0]['amount'] = price
        analyses.append(plan_analysis.analyze(p, policy, sources))
    warnings = plan_analysis.ladder(analyses, policy, plan_order=['starter','growth','enterprise'])
    # Genuine canonical price inversions are still reported.
    assert {(w['lower'], w['higher']) for w in warnings} == {('starter','growth'),('growth','enterprise')}
    assert sum(w['code']=='NON_INCREASING_PRICE' for w in warnings) == 2


def test_internal_allocations_are_fixed_not_tier_or_utilization_scaled():
    from src.ai.billing import economic_catalog
    from src.ai.billing.standard_plan_catalog import load_catalog
    plan, policy, sources = fixture()
    sources['feature_economics'] = economic_catalog.coverage()
    policy['assumptions']['feature_treatments'] = {}
    results = []
    for template in load_catalog()['plans']:
        p = deepcopy(plan)
        p.update(plan_key=template['plan_key'], entitlements=template['features'])
        p['feature_limits'] = [dict(feature_code=a['feature_key'], limit_value=a['value'])
                               for a in template['allowances']]
        results.append(plan_analysis.analyze(p, policy, sources))
    assert [r['costs']['internal'] for r in results] == [Decimal('3')]*3
    # With current canonical coverage, every inter-tier cost difference comes
    # from the Credit pools, not the substantially larger internal capacities.
    for r in results:
        pools = [b for b in r['costs']['breakdown'] if b['classification']=='configured_credit_exposure']
        for scenario in ('expected','stress'):
            assert r['costs'][scenario] == (Decimal('3') + sum(b[scenario] for b in pools)).quantize(Decimal('.01'))
        assert all(b['expected']==b['stress']==0 for b in r['costs']['breakdown']
                   if b['category']=='internal_allocation')


@pytest.mark.parametrize('patch', [dict(target_margin='NaN'),dict(minimum_margin='.5'),dict(stress_utilization='.1'),
    dict(processing_ratio='.6'),dict(usd_to_jod='0'),dict(fx_source=''),dict(annual_allowance_cycles=0),dict(rounding_jod='.013')])
def test_invalid_policy_rejected(patch):
    with pytest.raises(ValidationError):
        plan_studio.Assumptions.model_validate({**assumptions(), **patch})


def policy_body(sources, **patch):
    values = assumptions()
    codes = {r['feature_code'] for r in sources['features']} | set(sources['entitlement_catalog'])
    values.update(feature_treatments={code:'internal_allocation' for code in codes})
    values.update(patch)
    return {'assumptions':values, 'effective_from':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
            'reason':'SYNTHETIC pricing analysis only'}


def test_owner_effective_policy_versions_restricted_roles_and_immutable_evidence(owner_client, owner_db, platform_owner_context):
    client, _ = owner_client
    sources = client.get(URL).json()
    first = client.post(URL+'/policies',json=policy_body(sources))
    assert first.status_code == 201, first.text
    later = policy_body(sources)
    later['effective_from'] = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    future = client.post(URL+'/policies',json=later)
    assert future.status_code == 201
    selected = client.get(URL).json()['selected_policy']
    assert selected['policy_id'] == first.json()['policy_id']
    assert client.post(URL+'/analyze',json={'plan_key':'starter','policy_id':future.json()['policy_id']}).status_code == 422
    from src.ai import db
    conn = db.app_role_connection(*platform_owner_context)
    try:
        assert rows(conn,'SELECT current_user')[0][0] == 'ceopro_app'
        with pytest.raises(errors.InsufficientPrivilege):
            rows(conn,'SELECT * FROM billing_plan_analysis_policies')
        conn.rollback()
        assert rows(owner_db,"SELECT relforcerowsecurity FROM pg_class WHERE relname IN('billing_plan_analysis_policies','billing_plan_analyses')") == [(True,),(True,)]
        with pytest.raises(errors.InsufficientPrivilege):
            rows(owner_db,"UPDATE billing_plan_analysis_policies SET reason='tampered' WHERE policy_id=%s", (first.json()['policy_id'],))
        owner_db.rollback()
    finally:
        conn.close()


def test_analysis_simulation_and_history_cannot_reprice_or_grant_rights(owner_client, owner_db):
    client, _ = owner_client
    sources = client.get(URL).json()
    assert client.post(URL+'/policies',json=policy_body(sources)).status_code == 201
    tables = ['usage_plans','usage_plan_limits','billing_plan_prices','billing_subscriptions','billing_payments',
              'tenant_plan_assignments','tenant_custom_contracts','tenant_credit_balances','usage_ledger']
    def fingerprint():
        return {table: rows(owner_db,f"SELECT md5(coalesce(string_agg(row_to_json(t)::text,',' ORDER BY row_to_json(t)::text),'')) FROM {table} t") for table in tables}
    before = fingerprint()
    original = client.post(URL+'/analyze',json={'plan_key':'starter'})
    assert original.status_code == 200, original.text
    assert original.json()['pricing'] is not None, original.json()['warnings']
    simulated = client.post(URL+'/analyze',json={'plan_key':'starter','simulation':{'limits':{'ai_credits':9999}}})
    assert simulated.status_code == 200, simulated.text
    assert Decimal(simulated.json()['pricing']['recommended']) > Decimal(original.json()['pricing']['recommended'])
    assert fingerprint() == before
    history = client.get(URL+'/history').json()['analyses']
    frozen = next(x for x in history if x['analysis_id'] == original.json()['analysisId'])
    assert frozen['snapshot']['pricing'] == original.json()['pricing']
    assert frozen['source_hash'] == original.json()['sourceHash']
    assert client.post(URL+'/analyze',json={'plan_key':'starter','simulation':{'limits':{'imaginary_feature':1}}}).status_code == 422
    assert client.post(URL+'/analyze',json={'plan_key':'starter','simulation':{'limits':{'ai_credits':-1}}}).status_code == 422


def test_canonical_neighbors_exclude_history_and_owner_drafts_without_hiding_or_changing_them(owner_client, owner_db):
    client, _ = owner_client
    draft = 'draft_'+uuid4().hex[:12]
    created = client.post('/platform/billing/plans', json=dict(plan_key=draft, display_name='Unrelated draft',
        display_name_ar='Unrelated draft AR', tier_level=2, trial_days=0, monthly_price='1',
        reason='SYNTHETIC comparison isolation'))
    assert created.status_code==201, created.text
    tables = ['usage_plans','usage_plan_limits','usage_plan_entitlements','billing_plan_prices',
              'billing_subscriptions','tenant_plan_assignments','usage_ledger','keel_platform_audit']
    def snapshot():
        return {t:rows(owner_db,f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in tables}
    sources = client.get(URL).json()
    assert {'standard','pro',draft} <= {p['plan_key'] for p in sources['plans']}
    catalog = client.get('/platform/billing/plan-templates').json()
    assert client.post(URL+'/policies',json=policy_body(sources)).status_code==201
    before = snapshot()
    for selected in ['starter','growth','enterprise',draft,'pro']:
        response = client.post(URL+'/analyze', json={'plan_key':selected})
        assert response.status_code==200, response.text
        result = response.json()
        assert result['plan']['plan_key']==selected
        assert [n['planKey'] for n in result['neighbors']]==['starter','growth','enterprise']
        assert all((w['lower'],w['higher']) in [('starter','growth'),('growth','enterprise')]
                   for w in result['ladderWarnings'])
        assert result['evidence']['comparisonCatalog']==dict(version=catalog['catalog_version'],
            planKeys=['starter','growth','enterprise'])
    assert snapshot()==before
    history = client.get(URL+'/history').json()['analyses']
    assert any(h['snapshot']['plan']['plan_key']==draft for h in history)


@pytest.mark.parametrize('role',['owner','admin','staff'])
def test_tenant_roles_cannot_use_any_studio_operation(owner_client, tenant, owner_db, role, billing_connections):
    from src.ai.routers import platform
    from src.ai.core.security import TenantContext
    client, app = owner_client
    rows(owner_db,'UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s RETURNING user_id',(role,tenant[0]))
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(*tenant)
    assert client.get(URL).status_code == 403
    assert client.get(URL+'/history').status_code == 403
    assert client.post(URL+'/analyze',json={'plan_key':'starter'}).status_code == 403
    conn = billing_connections(*tenant)
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            rows(conn,"SELECT billing_plan_studio('inputs')")
    finally:
        conn.close()


def test_unauthenticated_studio_rejected(owner_client):
    client, app = owner_client
    app.dependency_overrides.clear()
    assert client.get(URL).status_code == 401


def test_provider_schedule_and_policy_changes_do_not_rewrite_frozen_analysis(owner_client,owner_db,billing_connections,platform_owner_context):
    from src.ai.billing import admin, custom_offers
    client,_ = owner_client
    sources = client.get(URL).json()
    provider = 'studio_synthetic_'+uuid4().hex[:12]
    admin.set_price(owner_db,budget_kind='data',provider=provider,operation='report',unit='request',
        unit_cost_usd=Decimal('1.234567890123'),safety_margin=Decimal('0'),charged_on_failure=True,cost_is_final=True,
        source='SYNTHETIC pricing evidence',verified_on=datetime.now(timezone.utc).date(),approved_by='test',reason='disposable fixture')
    with owner_db.cursor() as cur:
        cur.execute("""INSERT INTO billing_custom_pricing_policies(target_gross_margin,enforce_vendor_cost_ratio_floor,
          fixed_platform_fee_usd,upward_rounding_increment_usd,monthly_shared_infrastructure_cost_usd,active_paying_tenant_count,
          approved_by,approval_evidence) VALUES(.25,false,0,0,0,1,'test','SYNTHETIC') RETURNING policy_version_id""")
        binding_policy = str(cur.fetchone()[0])
        cur.execute("""INSERT INTO billing_custom_cost_rates(budget_kind,provider,operation,unit,unit_cost_usd,
          source,verified_at,effective_from,verified_by,verification_evidence)
          VALUES('data',%s,'report','request',1.234567890123,'SYNTHETIC',CURRENT_DATE,now()-interval '1 day','test','test') RETURNING cost_rate_id""",(provider,))
        quotation_rate=str(cur.fetchone()[0])
        cur.execute("""INSERT INTO billing_custom_cost_bindings(policy_version_id,feature_code,cost_category,budget_kind,
          provider,operation,unit,usage_basis,units_per_feature_unit,operational_multiplier,variability_reserve,effective_from,source,created_by,cost_rate_id)
          VALUES(%s,'monthly_reports','vendor','data',%s,'report','request','limit_value',1,1,1,now()-interval '1 minute','SYNTHETIC','test',%s)""",(binding_policy,provider,quotation_rate))
    operator=billing_connections(*platform_owner_context)
    try:
        custom_offers.pricing_admin_command(operator,'policy_activate',{'policy_version_id':binding_policy,'approval_evidence':'SYNTHETIC binding fixture'})
        operator.commit()
    finally:
        operator.close()
    body=policy_body(sources,cost_binding_policy_id=binding_policy)
    body['assumptions']['feature_treatments']['monthly_reports']='additional_external'
    created=client.post(URL+'/policies',json=body)
    assert created.status_code==201,created.text
    first=client.post(URL+'/analyze',json={'plan_key':'starter'}).json()
    assert first['pricing'] is not None,first['warnings']
    assert first['rateEvidence'][0]['unit_cost_usd']=='1.234567890123'
    assert first['rateEvidence'][0]['price_authority']=='provider_cost_schedules'
    admin.set_price(owner_db,budget_kind='data',provider=provider,operation='report',unit='request',
        unit_cost_usd=Decimal('9'),safety_margin=Decimal('0'),charged_on_failure=True,cost_is_final=True,
        source='SYNTHETIC changed provider evidence',verified_on=datetime.now(timezone.utc).date(),approved_by='test',reason='disposable fixture')
    second=client.post(URL+'/analyze',json={'plan_key':'starter'}).json()
    assert Decimal(second['pricing']['recommended'])>Decimal(first['pricing']['recommended'])
    historical=next(x for x in client.get(URL+'/history').json()['analyses'] if x['analysis_id']==first['analysisId'])
    assert historical['snapshot']['pricing']==first['pricing']
    assert historical['snapshot']['rateEvidence']==first['rateEvidence']
    assert rows(owner_db,'SELECT unit_cost_usd FROM billing_custom_cost_rates WHERE cost_rate_id=%s',(quotation_rate,))[0][0]==Decimal('1.234567890123')
    with pytest.raises(errors.InsufficientPrivilege):
        rows(owner_db,"UPDATE billing_plan_analyses SET source_hash=repeat('0',64) WHERE analysis_id=%s",(first['analysisId'],))
    owner_db.rollback()
