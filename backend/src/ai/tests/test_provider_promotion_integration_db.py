"""Owner-approved disposable-only auto reconciliation; default off everywhere."""
import os
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest,psycopg2
from src.ai import db
from src.ai.core.security import create_access_token
from src.ai.tests.test_provider_catalog_integration_db import source_fixture,preview as cat_preview,post as cat_post
from src.ai.tests.test_provider_stock_integration_db import scan,post as stock_post
from src.ai.tests.test_provider_orders_integration_db import stage,fixture_order
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.market_scraper import provider_promotion


def choice(f,category,enabled):return f[0].post('/onboarding/sources/'+f[3]+'/promotion-settings',json={'category':category,'enabled':enabled})


def test_default_off_owner_per_source_catalog_optin_and_replay(source_fixture,request,monkeypatch):
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];published=[];monkeypatch.setattr(provider_promotion,'_publish_discovery_request',lambda t:published.append(t))
    monkeypatch.delenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION',raising=False)
    r=f[0].get('/onboarding/sources/'+f[3]+'/promotion-settings');assert r.status_code==200 and r.json()['categories']=={'catalog':False,'inventory':False,'orders':False} and not r.json()['disposable_runtime_enabled']
    assert choice(f,'catalog',True).status_code==409
    monkeypatch.setenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION','YES')
    assert choice(f,'catalog',True).status_code==200 and choice(f,'catalog',True).status_code==200
    assert choice(f,'orders',True).status_code==409
    item=stage(f,fixture_order(provider)) # Actual fenced worker invokes opt-in path after its read receipt.
    assert published==[f[1][0]]
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM products WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(1,)
        q.execute('SELECT count(*) FROM invoices WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(0,)
        q.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='PROVIDER_CATEGORY_OPT_IN'",(f[1][0],));assert q.fetchone()==(1,)
    def retry():
        conn=db.app_role_connection(f[1][0],f[2][0])
        try:return provider_promotion.reconcile(conn,f[1][0],f[3],f[2][0])
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:retry(),[1,2]))
    assert all(x['catalog_created']==0 and x['orders']=='POLICY_BLOCKED' for x in results)
    assert published==[f[1][0]]
    assert choice(f,'catalog',False).status_code==200
    f[0].headers['Authorization']='Bearer '+create_access_token(f[1][1],f[2][1],email_verified=True)[0]
    assert choice(f,'catalog',True).status_code==404


def test_inventory_optin_requires_owner_field_location_selection_and_preserves_manual_edits(source_fixture,request,monkeypatch):
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];monkeypatch.setenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION','YES')
    assert cat_post(f,cat_preview(f)).status_code==200
    assert choice(f,'inventory',True).status_code==200
    p=scan(f,provider,8)[0];assert not p['already_applied'] # Opt-in alone must not select a location or quantity field.
    assert stock_post(f,p).status_code==200
    p2=scan(f,provider,3,'2026-10-26T04:00:00Z')[0];assert p2['already_applied'] and Decimal(p2['previous'])==3
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('UPDATE inventory SET stock_quantity=17 WHERE tenant_id=%s AND product_id=%s',(f[1][0],p2['product_id']))
    p3=scan(f,provider,9,'2026-10-26T05:00:00Z')[0];assert not p3['eligible'] and 'stock_conflict' in p3['reasons'] and Decimal(p3['previous'])==17
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM keel_provider_stock_posts WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(2,)
        q.execute('SELECT count(*) FROM usage_ledger WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(0,)


def test_tenant_admin_cannot_enable_owner_source_category(source_fixture,monkeypatch):
    f=source_fixture;tenant,actor=f[1][0],f[2][0];monkeypatch.setenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION','YES')
    try:
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_users SET role_key='admin' WHERE tenant_id=%s AND user_id=%s",(tenant,actor))
        assert choice(f,'catalog',True).status_code==403
        conn=db.app_role_connection(tenant,actor)
        try:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                with conn.cursor() as q:q.execute("INSERT INTO keel_provider_promotion_decisions(tenant_id,source_id,provider,category,enabled,actor_id) SELECT tenant_id,source_id,provider,'catalog',true,%s FROM keel_provider_sources WHERE tenant_id=%s AND source_id=%s",(actor,tenant,f[3]))
            conn.rollback()
        finally:conn.close()
    finally:
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_users SET role_key='owner' WHERE tenant_id=%s AND user_id=%s",(tenant,actor))


def test_interrupted_canonical_write_rolls_back_and_retries_without_provider_read(source_fixture,request,monkeypatch):
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];monkeypatch.setenv('KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION','YES');monkeypatch.setattr(provider_promotion,'_publish_discovery_request',lambda t:None)
    assert choice(f,'catalog',True).status_code==200
    original=provider_promotion.provider_catalog.confirm
    def interrupted(*a,**kw):original(*a,**kw);raise RuntimeError('Synthetic interruption before canonical commit')
    monkeypatch.setattr(provider_promotion.provider_catalog,'confirm',interrupted)
    stage(f,fixture_order(provider))
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM products WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(0,)
        q.execute('SELECT count(*) FROM keel_provider_business_revisions WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()[0]>0
        q.execute('SELECT count(*) FROM ingestion_jobs WHERE tenant_id=%s',(f[1][0],));before=q.fetchone()[0]
    monkeypatch.setattr(provider_promotion.provider_catalog,'confirm',original)
    url='/onboarding/sources/'+f[3]+'/promotion-retry'
    r=f[0].post(url);assert r.status_code==200 and r.json()['catalog_created']==1,r.text
    assert f[0].post(url).json()['catalog_created']==0
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM ingestion_jobs WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(before,)
        q.execute('SELECT count(*) FROM products WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(1,)
