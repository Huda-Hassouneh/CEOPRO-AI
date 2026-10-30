"""Controlled provider simulation -> real worker/database -> real owner API.
No external Shopify/Woo merchant is contacted; fixtures are explicit synthetic inputs.
"""
import os,json
from uuid import uuid4
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest,psycopg2
from cryptography.fernet import Fernet
from src.ai import db
from src.ai.core.security import create_access_token
from src.ai.core.exceptions import register_exception_handlers
from src.ai.routers import onboarding,products
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.market_scraper import data_access,provider_store_sync
from src.market_scraper.provider_lifecycle import bind_verified_provider_source
from src.market_scraper.shopify import ShopifyRecord
from src.market_scraper.woocommerce import WooRecord

@pytest.fixture(params=['shopify','woocommerce'])
def source_fixture(setup,monkeypatch,request):
    client,app,ts,us=setup;app.include_router(onboarding.router);app.include_router(products.router);register_exception_handlers(app)
    tenant,actor=ts[0],us[0];source=str(uuid4());provider=request.param;domain='fixture-'+tenant[:8]+'.myshopify.com';store='https://synthetic-'+tenant[:8]+'.example/';shop='gid://shopify/Shop/123456'
    monkeypatch.setenv('CREDENTIAL_VAULT_MASTER_KEY',Fernet.generate_key().decode());monkeypatch.setenv('SCRAPER_ACTOR_USER_ID',actor);monkeypatch.setenv('KEEL_ENT008_STAGE2_ENABLED','true')
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute("INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collector_key,collector_config,is_active,policy_status,approval_reference,approved_by,approved_at,privacy_reviewed_at,sync_frequency_minutes) VALUES(%s,%s,'SYNTHETIC provider contract fixture','OWN_SYSTEM_CONNECTOR',%s,%s,true,'ALLOWED','synthetic-owner-approved',%s,now(),now(),1)",(source,tenant,provider,json.dumps({'store_url':store,'api_version':'2026-10'}),actor))
        data_access.set_source_credentials(c,tenant,source,{'access_token':'synthetic-token'} if provider=='shopify' else {'consumer_key':'ck_synthetic','consumer_secret':'cs_synthetic'})
    conn=db.app_role_connection(tenant,actor)
    try:
        verification={'verified':True,'shop_id':shop,'shop_domain':domain,'api_version':'2026-10'} if provider=='shopify' else {'verified':True,'api':'wc/v3','products_accessible':True,'orders_accessible':True,'currency_code':'JOD','canonical_store_url':store.rstrip('/')}
        bind_verified_provider_source(conn,tenant_id=tenant,source_id=source,provider=provider,verification=verification);conn.commit()
        if provider=='shopify':
            records=[ShopifyRecord('product','gid://shopify/Product/1',{'id':'gid://shopify/Product/1','title':'Synthetic source product','status':'ACTIVE','updatedAt':'2026-10-26T00:00:00Z'}),ShopifyRecord('variant','gid://shopify/ProductVariant/2',{'id':'gid://shopify/ProductVariant/2','title':'Default Title','sku':'SOURCE-1','price':{'amount':'12.5000','currencyCode':'JOD'},'updatedAt':'2026-10-26T00:00:00Z'},'gid://shopify/Product/1')]
            factory=lambda *a,**k:SimpleNamespace(verify_connection=lambda:{**verification,'granted_scopes':frozenset({'read_products','read_orders','read_inventory'})},iter_products=lambda:iter(records),iter_orders=lambda **k:iter([]),iter_inventory=lambda:iter([]))
            result=provider_store_sync.run_due_provider_syncs(conn,tenant,client_factory=factory)
        else:
            records=[WooRecord('product',1,{'id':1,'name':'Synthetic source product','type':'simple','status':'publish','sku':'SOURCE-1','price':'12.5000','date_modified_gmt':'2026-10-26T00:00:00','manage_stock':False})]
            factory=lambda *a,**k:SimpleNamespace(verify_connection=lambda:verification,iter_products=lambda:iter(records),iter_orders=lambda **k:iter([]))
            result=provider_store_sync.run_due_provider_syncs(conn,tenant,woocommerce_client_factory=factory)
        assert result and 'error' not in result[0],result
    finally:conn.close()
    listed=client.get('/onboarding/sources/'+source+'/provider-records');assert listed.status_code==200,listed.text
    item=next(x for x in listed.json()['items'] if x['entity_type']==('variant' if provider=='shopify' else 'product'))
    return client,ts,us,source,item

def preview(f):
    client,ts,us,source,item=f;r=client.get('/onboarding/sources/'+source+'/provider-records/'+item['business_revision_id']+'/catalog-preview');assert r.status_code==200,r.text;return r.json()

def post(f,plan):
    client,ts,us,source,item=f;return client.post('/onboarding/sources/'+source+'/provider-records/catalog-post',json={'business_revision_id':item['business_revision_id'],'preview_hash':plan['preview_hash']})

def test_owner_confirmed_provider_catalog_persists_once_with_capacity_audit_and_no_stock_or_credit_changes(source_fixture,monkeypatch):
    f=source_fixture;client,ts,us,source,item=f;published=[];monkeypatch.setattr(products,'_publish_discovery_request',lambda tenant:published.append(tenant));plan=preview(f);assert plan['eligible'] and plan['action']=='create',plan
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:post(f,plan),[1,2]))
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    assert len({r.json()['product_id'] for r in results})==1
    assert published==[ts[0]]
    product=client.get('/products/'+results[0].json()['product_id']).json();assert product['sku']=='SOURCE-1' and product['current_price']==12.5 and product['source']=='IMPORTED' and product['inventory'] is None
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM products WHERE tenant_id=%s',(ts[0],));assert q.fetchone()==(1,)
        q.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='PROVIDER_RECORD_ASSOCIATED'",(ts[0],));assert q.fetchone()==(1,)
        q.execute('SELECT count(*) FROM usage_ledger WHERE tenant_id=%s',(ts[0],));assert q.fetchone()==(0,)

def test_source_identifiers_stale_review_cross_tenant_and_staff_cannot_overwrite_products(source_fixture):
    f=source_fixture;client,ts,us,source,item=f;plan=preview(f)
    c=db.app_role_connection(ts[0],us[0])
    try:products.create_product(c,ts[0],us[0],{'en':'Conflicting canonical title'},None,None,None,99,None,'JOD',sku='SOURCE-1');c.commit()
    finally:c.close()
    assert post(f,plan).status_code==409
    changed=preview(f);assert not changed['eligible'] and changed['reasons']
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT current_price FROM products WHERE tenant_id=%s',(ts[0],));assert q.fetchone()==(99,)
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    assert client.get('/onboarding/sources/'+source+'/provider-records/'+item['business_revision_id']+'/catalog-preview').status_code==404
    client.headers['Authorization']='Bearer '+create_access_token(ts[0],us[0],email_verified=True)[0]
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s",(ts[0],))
    assert post(f,plan).status_code==403


def test_reviewed_revision_lock_blocks_worker_change_until_owner_post_commits(source_fixture,monkeypatch):
    import threading
    from src.market_scraper import provider_catalog
    f=source_fixture;client,ts,us,source,item=f;plan=preview(f);entered=threading.Event();release=threading.Event();updating=threading.Event()
    original=products.create_product
    def paused(*args,**kwargs):
        result=original(*args,**kwargs);entered.set()
        assert release.wait(10),'Owner post was not released'
        return result
    monkeypatch.setattr(products,'create_product',paused)
    def worker_revision_write():
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn,conn.cursor() as q:
            updating.set();q.execute("UPDATE keel_provider_record_identities SET current_revision_sha256=repeat('b',64) WHERE tenant_id=%s AND provider_record_identity_id=%s",(ts[0],item['provider_record_identity_id']))
    with ThreadPoolExecutor(max_workers=2) as pool:
        posting=pool.submit(post,f,plan)
        try:
            assert entered.wait(10);worker=pool.submit(worker_revision_write);assert updating.wait(5)
            assert not worker.done()
            import time;time.sleep(.2);assert not worker.done()
        finally:release.set()
        response=posting.result(timeout=15);assert response.status_code==200,response.text;worker.result(timeout=15)
    c=db.app_role_connection(ts[0],us[0])
    try:
        with c.cursor() as q:
            q.execute("SELECT has_table_privilege(current_user,'keel_provider_sources','UPDATE'),has_table_privilege(current_user,'keel_provider_record_identities','UPDATE')");assert q.fetchone()==(False,False)
    finally:c.close()
    r=client.get('/onboarding/sources/'+source+'/provider-records/'+item['business_revision_id']+'/catalog-preview');assert r.status_code==409
