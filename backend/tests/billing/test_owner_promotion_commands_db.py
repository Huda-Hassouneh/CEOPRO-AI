"""Owner promotion/catalog APIs on actual restricted PostgreSQL identities."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.ai.billing import owner_promotions,custom_offers
from src.ai.core.security import TenantContext
from src.ai.routers import platform


def test_owner_promotion_http_draft_persistence_and_boundaries(owner_db,billing_connections,platform_owner_context,tenant,monkeypatch):
    pt,pu=platform_owner_context;tid,uid=tenant
    def forbidden():pytest.fail('Owner API must not request an administrator DSN')
    monkeypatch.setattr(platform.db,'system_connection',forbidden)
    app=FastAPI();app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(pt,pu)
    body={'code':'SYNTH_'+uuid4().hex[:12].upper(),'name':'SYNTHETIC draft','description':'isolated fixture','reason':'SYNTHETIC TEST ONLY','plan_keys':['starter'],'terms':{'discount_type':'percent','discount_value':'10','starts_at':None,'expires_at':None,'max_uses':2,'max_uses_per_tenant':1,'invoice_scope':'initial_subscription'}}
    with TestClient(app) as client:
        made=client.post('/platform/billing/promotions',json=body);assert made.status_code==201,made.text
        promo=made.json();pid=promo['promotion_id'];assert promo['status']=='draft'
        listed=client.get('/platform/billing/promotions');assert listed.status_code==200
        assert any(p['promotion_id']==pid for p in listed.json()['items'])
        body['name']='SYNTHETIC revised'
        saved=client.patch('/platform/billing/promotions/'+pid,json=body);assert saved.status_code==200,saved.text
        assert saved.json()['name']=='SYNTHETIC revised'
        body['terms']['discount_value']='101'
        assert client.patch('/platform/billing/promotions/'+pid,json=body).status_code==422
        app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(tid,uid)
        assert client.get('/platform/billing/promotions').status_code==403
        assert client.post('/platform/billing/promotions',json=body).status_code==403
    with owner_db.cursor() as cur:
        cur.execute('SELECT status,name FROM billing_promotions WHERE promotion_id=%s',(pid,));assert cur.fetchone()==('draft','SYNTHETIC revised')
        cur.execute("SELECT action FROM keel_platform_audit WHERE subject=%s ORDER BY created_at",(pid,));assert [r[0] for r in cur.fetchall()]==['promotion_draft_create','promotion_draft_update']
    conn=billing_connections(pt,pu)
    try:
        with pytest.raises(owner_promotions.PromotionError) as e:owner_promotions.command(conn,'activate',{'promotion_id':pid})
        assert e.value.status==403
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT has_table_privilege(current_user,'billing_promotions','UPDATE')");assert cur.fetchone()[0] is False
    finally:conn.close()


def test_owner_catalog_http_mutates_future_catalog_only(owner_db,billing_connections,platform_owner_context,tenant,monkeypatch):
    pt,pu=platform_owner_context;tid,uid=tenant
    with owner_db.cursor() as cur:
        cur.execute("SELECT limit_value FROM usage_plan_limits WHERE plan_key='starter' AND feature_code='team_seats'");old=cur.fetchone()[0]
    monkeypatch.setattr(platform.db,'system_connection',lambda:pytest.fail('No admin runtime connection permitted'))
    app=FastAPI();app.include_router(platform.router);app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(pt,pu)
    try:
        with TestClient(app) as client:
            changed=client.patch('/platform/billing/plans/starter/features',json={'feature_code':'team_seats','included':True,'limit_value':9,'reason':'SYNTHETIC TEST ONLY'})
            assert changed.status_code==200,changed.text
            assert changed.json()['existing_assignments_preserved'] is True
            bad=client.patch('/platform/billing/plans/starter/features',json={'feature_code':'market_intelligence','included':True,'limit_value':2,'reason':'SYNTHETIC invalid'})
            assert bad.status_code==422
            app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(tid,uid)
            assert client.patch('/platform/billing/plans/starter/status',json={'active':False,'reason':'SYNTHETIC denied'}).status_code==403
        with owner_db.cursor() as cur:
            cur.execute("SELECT limit_value FROM usage_plan_limits WHERE plan_key='starter' AND feature_code='team_seats'");assert cur.fetchone()[0]==9
            cur.execute("SELECT count(*) FROM keel_platform_audit WHERE action='plan_feature_update' AND subject='plan:starter:team_seats'");assert cur.fetchone()[0]>=1
    finally:
        with owner_db.cursor() as cur:cur.execute("UPDATE usage_plan_limits SET limit_value=%s WHERE plan_key='starter' AND feature_code='team_seats'",(old,))


@pytest.fixture
def activation_records(owner_db, platform_owner_context):
    # Remove only this test's synthetic definitions before its owner is removed.
    ids = []
    yield ids
    with owner_db.cursor() as cur:
        for identity in ids:
            cur.execute('DELETE FROM billing_promotion_plans WHERE promotion_id=%s', (identity,))
            cur.execute('DELETE FROM billing_promotions WHERE promotion_id=%s', (identity,))


@pytest.mark.parametrize('mismatched', [False, True])
def test_owner_activation_verifies_provider_before_publication(
    owner_db, billing_connections, platform_owner_context, tenant, monkeypatch, mismatched, activation_records
):
    """Offline provider economics; real HTTP, SQL, role checks and audit persistence."""
    from src.ai.billing import promotions
    pt, pu = platform_owner_context
    tid, uid = tenant
    code = 'SYNTH_' + uuid4().hex[:12].upper()
    coupon_id, provider_id = 'coupon_' + uuid4().hex, 'promo_' + uuid4().hex
    calls = []
    monkeypatch.setattr(platform.db, 'system_connection', lambda: pytest.fail('No admin runtime DSN'))
    monkeypatch.setattr(promotions, 'enabled', lambda: True)
    # This test isolates economics/persistence. Mode guards have their own tests;
    # no key is configured and the autouse fixture refuses any Stripe client.
    monkeypatch.setattr(promotions, '_provider_mutations_allowed', lambda: True)
    def coupon(params, key):
        calls.append('coupon')
        assert params['duration'] == 'once' and params['percent_off'] == 10
        return {'id': coupon_id, 'duration': 'once', 'percent_off': 20 if mismatched else 10, 'livemode': False}
    def promotion(params, key):
        calls.append('promotion')
        assert params['promotion']['coupon'] == coupon_id
        return {'id': provider_id, 'active': True, 'code': code, 'promotion': {'coupon': coupon_id}, 'max_redemptions': 2, 'livemode': False}
    monkeypatch.setattr(promotions.stripe_api, 'create_coupon', coupon)
    monkeypatch.setattr(promotions.stripe_api, 'create_promotion_code', promotion)
    app = FastAPI()
    app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(pt, pu)
    body = {'code': code, 'name': 'SYNTHETIC offline activation', 'description': 'No provider network', 'reason': 'SYNTHETIC TEST ONLY', 'plan_keys': ['starter'], 'terms': {'discount_type': 'percent', 'discount_value': '10', 'starts_at': None, 'expires_at': None, 'max_uses': 2, 'max_uses_per_tenant': 1, 'invoice_scope': 'initial_subscription'}}
    with TestClient(app) as client:
        draft = client.post('/platform/billing/promotions', json=body)
        assert draft.status_code == 201, draft.text
        pid = draft.json()['promotion_id']
        activation_records.append(pid)
        path = '/platform/billing/promotions/' + pid + '/activate'
        approval = {'approval_reference': 'SYNTHETIC offline verification', 'reason': 'SYNTHETIC TEST ONLY'}
        result = client.post(path, json=approval)
        assert result.status_code == (422 if mismatched else 200), result.text
        if not mismatched:
            repeat = client.post(path, json=approval)
            assert repeat.status_code == 200 and repeat.json()['reused'] is True
        assert calls == ['coupon', 'promotion']
        app.dependency_overrides[platform.get_tenant_context] = lambda: TenantContext(tid, uid)
        assert client.post(path, json=approval).status_code == 403
    with owner_db.cursor() as cur:
        cur.execute('SELECT status,stripe_coupon_id,stripe_promotion_code_id FROM billing_promotions WHERE promotion_id=%s', (pid,))
        assert cur.fetchone() == (('draft', None, None) if mismatched else ('active', coupon_id, provider_id))
        cur.execute("SELECT count(*) FROM keel_platform_audit WHERE subject=%s AND action='promotion_activate'", (pid,))
        assert cur.fetchone()[0] == (0 if mismatched else 1)
