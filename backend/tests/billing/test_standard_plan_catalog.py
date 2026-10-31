"""Canonical templates against disposable PostgreSQL and real owner commands."""
from copy import deepcopy
from uuid import uuid4

import pytest
from psycopg2 import errors

from src.ai.billing import economic_catalog
from src.ai.billing.standard_plan_catalog import (
    CatalogInvalid, fingerprint, install_catalog, installed_catalog, load_catalog, validate_catalog,
)
from src.ai.core import feature_contracts
from .test_provider_accounting_db import owner_client  # noqa: F401


def rows(conn, query, args=()):
    with conn.cursor() as cursor:
        cursor.execute(query, args)
        return cursor.fetchall() if cursor.description else None


def test_all_customer_identities_are_explicit_without_financial_or_platform_bindings():
    catalog = load_catalog()
    keys = {f['key'] for f in catalog['features']}
    assert keys == set(economic_catalog.FEATURES)
    assert len(keys) == 19
    for plan in catalog['plans']:
        assert set(plan['features']) == keys
        assert len(plan['allowances']) == 13
        competitors = next(a for a in plan['allowances'] if a['feature_key'] == 'tracked_competitors')
        assert competitors == dict(feature_key='tracked_competitors', state='unlimited', value=None, trial_value=None)
    assert not {'platform_administration','billing','pricing_studio','provider_accounting'} & keys
    assert not any('cost' in k or 'provider' in k for f in catalog['features'] for k in f)
    assert all('?' not in f['label_ar'] and f['label_ar'] != f['label_en'] for f in catalog['features'])


@pytest.mark.parametrize('invalid', [
    'duplicate_plan','duplicate_feature','unknown_category','unknown_feature','missing_feature',
    'bad_type','duplicate_assignment','negative','float','bool','missing_not_unlimited','bad_trial',
    'unknown_allowance','unknown_plan','platform_feature','bad_period','bad_price','duplicate_period',
])
def test_catalog_rejects_invalid_definitions(invalid):
    c = deepcopy(load_catalog()); f=c['features'][0]; p=c['plans'][0]; a=p['allowances'][0]
    if invalid=='duplicate_plan': c['plans'].append(deepcopy(p))
    if invalid=='duplicate_feature': c['features'].append(deepcopy(f))
    if invalid=='unknown_category': f['category']='unapproved'
    if invalid=='unknown_feature': f['key']='invented_feature'
    if invalid=='missing_feature': c['features'].pop()
    if invalid=='bad_type': f['entitlement_type']='cadence'
    if invalid=='duplicate_assignment': p['features'].append(p['features'][0])
    if invalid=='negative': a['value']=-1
    if invalid=='float': a['value']=1.5
    if invalid=='bool': a['value']=True
    if invalid=='missing_not_unlimited': a['value']=None
    if invalid=='bad_trial': a['trial_value']=-1
    if invalid=='unknown_allowance': a['feature_key']='made_up'
    if invalid=='unknown_plan': p['plan_key']='standard'
    if invalid=='platform_feature': f['key']='platform_administration'
    if invalid=='bad_period': p['bootstrap_commercial_defaults']['billing_periods'][0]['period_code']='weekly'
    if invalid=='bad_price': p['bootstrap_commercial_defaults']['monthly_price']='NaN'
    if invalid=='duplicate_period': p['bootstrap_commercial_defaults']['billing_periods'].append(deepcopy(p['bootstrap_commercial_defaults']['billing_periods'][0]))
    with pytest.raises(CatalogInvalid): validate_catalog(c)


def test_missing_approval_is_explicit_and_database_units_must_match():
    c=deepcopy(load_catalog()); c['plans'][0]['allowances'][0].update(state='owner_required',value=None)
    validate_catalog(c)
    with pytest.raises(CatalogInvalid,match='Executable usage definition differs'):
        validate_catalog(c,{})


def test_fresh_setup_has_only_three_current_standard_tiers_and_all_features(owner_db):
    c=installed_catalog(owner_db)
    assert rows(owner_db,"SELECT plan_key FROM usage_plans WHERE self_serve AND is_active ORDER BY tier_level") == [('starter',),('growth',),('enterprise',)]
    for p in c['plans']:
        key=p['plan_key']
        assert {r[0] for r in rows(owner_db,'SELECT feature_code FROM usage_plan_entitlements WHERE plan_key=%s',(key,))} == set(feature_contracts.MODULE_FEATURES + feature_contracts.BASELINE_ENTITLEMENTS)
        expected={a['feature_key']:(a['value'],a['trial_value']) for a in p['allowances']}
        assert {r[0]:tuple(r[1:]) for r in rows(owner_db,'SELECT feature_code,limit_value,trial_limit_value FROM usage_plan_limits WHERE plan_key=%s',(key,))} == expected
    # Old identities and Custom are intentionally preserved, never reused.
    assert rows(owner_db,"SELECT plan_key,is_active FROM usage_plans WHERE plan_key IN ('standard','pro') ORDER BY plan_key") == [('pro',False),('standard',False)]


def test_repeat_setup_and_changed_defaults_preserve_owner_history_and_accounting(owner_db):
    protected = ['provider_cost_schedules','billing_custom_cost_rates','billing_custom_cost_bindings',
                 'billing_cost_policy','billing_subscriptions','tenant_plan_assignments','tenant_credit_balances',
                 'billing_plan_prices','usage_features']
    # Use a rollback-only transaction; do not leak deliberate owner alterations into other tests.
    rows(owner_db,'BEGIN')
    try:
        rows(owner_db,"UPDATE usage_plans SET is_active=false,display_name='Explicit owner name' WHERE plan_key='growth'")
        rows(owner_db,"UPDATE usage_plan_limits SET limit_value=777 WHERE plan_key='growth' AND feature_code='ai_credits'")
        rows(owner_db,"DELETE FROM usage_plan_entitlements WHERE plan_key='growth' AND feature_code='demand_prediction'")
        before={t:rows(owner_db,f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in protected+['usage_plans','usage_plan_limits','usage_plan_entitlements','keel_platform_audit']}
        assert install_catalog(owner_db)['initialized_plans']==[]
        assert install_catalog(owner_db)['initialized_plans']==[]
        assert before=={t:rows(owner_db,f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in before}
        c=deepcopy(load_catalog());c['catalog_version']='standard-plans-test-v2'
        c['plans'][1]['allowances'][0]['value']=999
        from psycopg2.extras import Json
        rows(owner_db,'SELECT billing_standard_catalog_install(%s,%s,false)',(Json(c),fingerprint(c)))
        assert before['usage_plan_limits']==rows(owner_db,'SELECT to_jsonb(r) FROM usage_plan_limits r ORDER BY to_jsonb(r)::text')
        # A version cannot silently change in place.
        rows(owner_db,'SAVEPOINT immutable')
        with pytest.raises(errors.InvalidParameterValue):
            rows(owner_db,'SELECT billing_standard_catalog_install(%s,%s,false)',(Json(c),'changed_digest'))
        rows(owner_db,'ROLLBACK TO SAVEPOINT immutable')
        assert before['usage_plans']==rows(owner_db,'SELECT to_jsonb(r) FROM usage_plans r ORDER BY to_jsonb(r)::text')
    finally:
        rows(owner_db,'ROLLBACK')


def test_template_owner_creation_edits_and_stripe_gating(owner_client,owner_db):
    client,_=owner_client
    catalog=client.get('/platform/billing/plan-templates')
    assert catalog.status_code==200
    c=catalog.json(); key='template_'+uuid4().hex[:12]
    protected={t:rows(owner_db,f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in
               ['billing_subscriptions','tenant_plan_assignments','provider_cost_schedules','billing_custom_cost_rates']}
    body=dict(plan_key=key,display_name=key,display_name_ar=key+'_ar',tier_level=8,trial_days=3,
              monthly_price='87.21',billing_periods=[],reason='Synthetic template acceptance',
              template_key='growth',template_catalog_version=c['catalog_version'])
    created=client.post('/platform/billing/plans',json=body)
    assert created.status_code==201,created.text
    assert created.json()['is_active'] is False
    assert client.post('/platform/billing/plans',json={**body,'plan_key':'standard'}).status_code==409
    configured=next(p for p in client.get('/platform/billing/standard-plans').json()['plans'] if p['plan_key']==key)
    assert configured['monthly_price']==87.21 and configured['is_active'] is False
    assert len(configured['feature_limits'])==13 and len(configured['entitlements'])==6
    assert rows(owner_db,'SELECT trial_limit_value FROM usage_plan_limits WHERE plan_key=%s AND feature_code=%s',(key,'ai_credits'))==[(111,)]
    for code,value in [('ai_credits',700),('data_credits',800)]:
        assert client.patch(f'/platform/billing/plans/{key}/features',json=dict(feature_code=code,included=True,limit_value=value,reason='Owner template adjustment')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/features',json=dict(feature_code='dashboard_analytics',included=False,limit_value=None,reason='Owner baseline adjustment')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=True,reason='Configured future offer')).status_code==200
    from src.ai.billing.service import _price_or_error, BillingError
    with pytest.raises(BillingError) as unsynced: _price_or_error(owner_db,key,'monthly')
    assert unsynced.value.status==503 and unsynced.value.code=='price_not_synced'
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=False,reason='End synthetic acceptance')).status_code==200
    assert protected=={t:rows(owner_db,f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in protected}
    metadata=client.get('/platform/billing/feature-catalog').json()
    assert len(metadata['features'])==19
    assert {f['feature_code'] for f in metadata['features'] if f['custom_plan_supported']} == set(feature_contracts.QUANTITATIVE_FEATURES + feature_contracts.MODULE_FEATURES)
    assert {f['category']['key'] for f in metadata['features']}=={r['key'] for r in c['categories']}
    assert rows(owner_db,"SELECT count(*) FROM keel_platform_audit WHERE action='standard_plan_template_apply' AND subject=%s",('plan:'+key,))==[(1,)]


def test_non_owner_cannot_read_templates_create_or_change_catalog(owner_client,tenant,owner_db):
    client,app=owner_client
    from src.ai.routers import platform
    from src.ai.core.security import TenantContext
    app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(*tenant)
    assert client.get('/platform/billing/plan-templates').status_code==403
    assert client.post('/platform/billing/plans',json=dict(plan_key='forbidden_new_plan',display_name='No',
        display_name_ar='No ar',tier_level=1,trial_days=0,monthly_price='50',reason='Synthetic denial',
        template_key='growth',template_catalog_version='standard-plans-v1')).status_code==403
    assert client.patch('/platform/billing/plans/forbidden_new_plan/draft-terms',json=dict(plan_key='forbidden_new_plan',
        display_name='No',display_name_ar='No ar',tier_level=1,trial_days=0,monthly_price='50',reason='Synthetic denial')).status_code==403
    rows(owner_db,'BEGIN')
    try:
        rows(owner_db,'SET LOCAL ROLE ceopro_app')
        with pytest.raises(errors.InsufficientPrivilege):
            rows(owner_db,"SELECT billing_standard_catalog_install('{}','x',false)")
    finally: rows(owner_db,'ROLLBACK')


def test_inventory_has_no_destructive_cleanup_even_for_referenced_test_plan(owner_db,tenant,test_price):
    from scripts.standard_plan_inventory import inventory
    key=test_price[0]
    rows(owner_db,"INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,%s,'active','manual')",(tenant[0],key))
    try:
        result=inventory(owner_db)
        plan=next(p for p in result['plans'] if p['plan_key']==key)
        assert plan['references']['tenant_plan_assignments.plan_key']==1
        assert plan['cleanup']=='PRESERVE' and result['deletion_candidates']==[]
        with pytest.raises(errors.ReadOnlySqlTransaction): rows(owner_db,'DELETE FROM usage_plans WHERE plan_key=%s',(key,))
        assert rows(owner_db,'SELECT count(*) FROM usage_plans WHERE plan_key=%s',(key,))==[(1,)]
    finally:
        owner_db.rollback();owner_db.set_session(readonly=False)


def test_owner_required_template_quantity_blocks_activation_and_unknown_version_is_atomic(owner_client,owner_db):
    from psycopg2.extras import Json
    client,_=owner_client
    c=deepcopy(load_catalog());c['catalog_version']='standard-plan-owner-required'
    c['plans'][0]['allowances'][0].update(state='owner_required',value=None)
    validate_catalog(c)
    rows(owner_db,'SELECT billing_standard_catalog_install(%s,%s,false)',(Json(c),fingerprint(c)))
    key='required_'+uuid4().hex[:12]
    body=dict(plan_key=key,display_name=key,display_name_ar=key+'_ar',tier_level=5,trial_days=0,
        monthly_price='50',reason='Synthetic missing allowance',template_key='starter',template_catalog_version='unknown-version')
    assert client.post('/platform/billing/plans',json=body).status_code==422
    assert rows(owner_db,'SELECT count(*) FROM usage_plans WHERE plan_key=%s',(key,))==[(0,)]
    body['template_catalog_version']=c['catalog_version']
    assert client.post('/platform/billing/plans',json=body).status_code==201
    read=next(p for p in client.get('/platform/billing/standard-plans').json()['plans'] if p['plan_key']==key)
    assert read['configuration_status']=='MISSING_FEATURES' and read['template_missing_allowances']
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=True,reason='Not complete')).status_code==422
    missing=c['plans'][0]['allowances'][0]['feature_key']
    assert rows(owner_db,'SELECT count(*) FROM usage_plan_limits WHERE plan_key=%s AND feature_code=%s',(key,missing))==[(0,)]
    assert client.patch(f'/platform/billing/plans/{key}/features',json=dict(feature_code=missing,included=True,limit_value=12,reason='Explicit owner quantity')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=True,reason='Configured')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=False,reason='End synthetic acceptance')).status_code==200
    # Test-only added version must not replace the installed v1 for later tests.
    rows(owner_db,'DELETE FROM billing_standard_catalog_versions WHERE catalog_version=%s',(c['catalog_version'],))


def test_template_draft_names_prices_and_terms_are_editable_without_replacing_identity_or_allowances(owner_client,owner_db,tenant):
    client,_=owner_client
    c=client.get('/platform/billing/plan-templates').json();key='editable_'+uuid4().hex[:10]
    body=dict(plan_key=key,display_name=key,display_name_ar=key+'_ar',tier_level=4,trial_days=7,
        monthly_price='71.00',billing_periods=[],reason='Synthetic template draft',template_key='growth',template_catalog_version=c['catalog_version'])
    assert client.post('/platform/billing/plans',json=body).status_code==201
    before=rows(owner_db,'SELECT to_jsonb(r) FROM usage_plan_limits r WHERE plan_key=%s ORDER BY feature_code',(key,))
    update={k:v for k,v in body.items() if not k.startswith('template_')}
    update.update(display_name=key+' renamed',display_name_ar=key+' ar renamed',monthly_price='80.00',trial_days=3,
                  description='Explicit draft edit',billing_periods=[dict(period_code='three-months',discount_percent='5.00')])
    result=client.patch(f'/platform/billing/plans/{key}/draft-terms',json=update)
    assert result.status_code==200,result.text
    assert result.json()['plan']['plan_key']==key and result.json()['plan']['is_active'] is False
    assert result.json()['plan']['display_name']==key+' renamed'
    assert rows(owner_db,'SELECT to_jsonb(r) FROM usage_plan_limits r WHERE plan_key=%s ORDER BY feature_code',(key,))==before
    assert rows(owner_db,"SELECT amount FROM billing_plan_prices WHERE plan_key=%s AND period_code='three-months' AND retired_at IS NULL",(key,))==[(__import__('decimal').Decimal('228.00'),)]
    assert rows(owner_db,'SELECT count(*) FROM billing_plan_prices WHERE plan_key=%s AND retired_at IS NOT NULL',(key,))==[(1,)]
    assert rows(owner_db,"SELECT count(*) FROM keel_platform_audit WHERE subject=%s AND action='standard_plan_draft_update'",('plan:'+key,))==[(1,)]
    # Neither a different identity nor a seeded/historical plan is editable here.
    assert client.patch(f'/platform/billing/plans/{key}/draft-terms',json={**update,'plan_key':'changed_identity'}).status_code==422
    assert client.patch('/platform/billing/plans/starter/draft-terms',json={**update,'plan_key':'starter'}).status_code==422
    rows(owner_db,"INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,%s,'active','manual')",(tenant[0],key))
    snapshot=rows(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))
    assert client.patch(f'/platform/billing/plans/{key}/draft-terms',json=update).status_code==422
    assert rows(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))==snapshot
    rows(owner_db,'DELETE FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))
    # Even without customer records, a mapped price or first activation closes draft authoring.
    rows(owner_db,"UPDATE billing_plan_prices SET stripe_price_id=%s WHERE plan_key=%s AND period_code='monthly' AND retired_at IS NULL",('synthetic_'+key,key))
    assert client.patch(f'/platform/billing/plans/{key}/draft-terms',json=update).status_code==422
    rows(owner_db,'UPDATE billing_plan_prices SET stripe_price_id=NULL WHERE plan_key=%s',(key,))
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=True,reason='First activation')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/status',json=dict(active=False,reason='End synthetic acceptance')).status_code==200
    assert client.patch(f'/platform/billing/plans/{key}/draft-terms',json=update).status_code==422
