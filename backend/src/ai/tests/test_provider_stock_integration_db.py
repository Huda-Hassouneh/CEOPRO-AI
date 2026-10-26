"""Current fenced scans, explicit M96 authority, canonical stock and conflict guards."""
import os
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest,psycopg2
from src.ai import db
from src.ai.core.security import create_access_token
from src.ai.tests.test_provider_catalog_integration_db import source_fixture,preview as cat_preview,post as cat_post
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.market_scraper import provider_store_sync
from src.market_scraper.shopify import ShopifyRecord
from src.market_scraper.woocommerce import WooRecord


def scan(f,provider,quantity,stamp='2026-10-26T03:00:00Z',managed=True):
    client,ts,us,source,item=f
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('UPDATE data_sources SET last_synced_at=NULL WHERE tenant_id=%s AND source_id=%s',(ts[0],source))
    conn=db.app_role_connection(ts[0],us[0])
    try:
        with conn.cursor() as q:q.execute('SELECT verified_store_id,verified_store_domain FROM keel_provider_sources WHERE source_id=%s',(source,));store,domain=q.fetchone()
        if provider=='shopify':
            inventory=[ShopifyRecord('location','gid://shopify/Location/9',{'name':'Synthetic source location','isActive':True,'updatedAt':stamp})]
            if managed:inventory.append(ShopifyRecord('inventory_level','gid://shopify/InventoryLevel/99',{'updatedAt':stamp,'item':{'id':'gid://shopify/InventoryItem/8','variant':{'id':'gid://shopify/ProductVariant/2'}},'quantities':[{'name':'available','quantity':quantity}]},'gid://shopify/Location/9'))
            factory=lambda *a,**k:SimpleNamespace(verify_connection=lambda:{'verified':True,'shop_id':store,'shop_domain':domain,'granted_scopes':frozenset({'read_products','read_orders','read_inventory'})},iter_products=lambda:iter([]),iter_orders=lambda **k:iter([]),iter_inventory=lambda:iter(inventory))
            results=provider_store_sync.run_due_provider_syncs(conn,ts[0],client_factory=factory)
        else:
            with conn.cursor() as q:q.execute("SELECT collector_config->>'store_url' FROM data_sources WHERE source_id=%s",(source,));store=q.fetchone()[0].rstrip('/')
            raw={'id':1,'name':'Synthetic source product','type':'simple','sku':'SOURCE-1','price':'12.5000','date_modified_gmt':stamp,'manage_stock':managed,'stock_quantity':quantity}
            factory=lambda *a,**k:SimpleNamespace(verify_connection=lambda:{'verified':True,'api':'wc/v3','products_accessible':True,'orders_accessible':True,'currency_code':'JOD','canonical_store_url':store},iter_products=lambda:iter([WooRecord('product',1,raw)]),iter_orders=lambda **k:iter([]))
            results=provider_store_sync.run_due_provider_syncs(conn,ts[0],woocommerce_client_factory=factory)
        assert results and 'error' not in results[0],results
    finally:conn.close()
    r=client.get('/onboarding/sources/'+source+'/inventory-review');assert r.status_code==200,r.text;return r.json()['items']


def post(f,p):return f[0].post('/onboarding/sources/'+f[3]+'/inventory-post',json={'observation_id':p['observation_id'],'preview_hash':p['preview_hash']})


def test_owner_selected_source_stock_refresh_replay_unknown_and_isolation(source_fixture,request):
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];assert cat_post(f,cat_preview(f)).status_code==200
    p=scan(f,provider,8)[0];assert p['eligible'],p
    with ThreadPoolExecutor(max_workers=2) as pool:rs=list(pool.map(lambda _:post(f,p),[1,2]))
    assert all(r.status_code==200 for r in rs),[r.text for r in rs]
    pid=rs[0].json()['product_id']
    def stock():
        with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT stock_quantity,warehouse_location FROM inventory WHERE tenant_id=%s AND product_id=%s',(f[1][0],pid));return q.fetchone()
    assert stock()==(8,p['warehouse'])
    p2=scan(f,provider,3,'2026-10-26T04:00:00Z')[0];assert p2['eligible'],p2
    assert post(f,p2).status_code==200 and stock()[0]==3
    # Identical provider observations on another completed scan remain eligible/replayable.
    same=scan(f,provider,3,'2026-10-26T04:00:00Z')[0];assert same['already_applied'] and post(f,same).json()['replayed']
    assert scan(f,provider,None,'2026-10-26T05:00:00Z',False)==[]
    assert post(f,p2).status_code==404 and stock()[0]==3
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        q.execute('SELECT count(*) FROM keel_provider_stock_posts WHERE tenant_id=%s',(f[1][0],));assert q.fetchone()==(2,)
        q.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='INVENTORY_AUTHORITY_SELECT'",(f[1][0],));assert q.fetchone()==(1,)
    f[0].headers['Authorization']='Bearer '+create_access_token(f[1][1],f[2][1],email_verified=True)[0]
    assert f[0].get('/onboarding/sources/'+f[3]+'/inventory-review').status_code==404


def test_manual_stock_is_never_silently_overwritten(source_fixture,request):
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];r=cat_post(f,cat_preview(f));assert r.status_code==200;pid=r.json()['product_id']
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("INSERT INTO inventory(tenant_id,product_id,stock_quantity,warehouse_location) VALUES(%s,%s,17,'Manual synthetic stock')",(f[1][0],pid))
    p=scan(f,provider,8)[0];assert not p['eligible'] and 'stock_conflict' in p['reasons'];assert post(f,p).status_code==409
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s',(f[1][0],pid));assert q.fetchone()==(17,)


def test_source_stock_uses_existing_python_numeric_precision(source_fixture,request):
    from decimal import Decimal
    f=source_fixture;provider=request.node.callspec.params['source_fixture'];assert cat_post(f,cat_preview(f)).status_code==200
    quantity='2.5000' if provider=='woocommerce' else 2
    p=scan(f,provider,quantity)[0];assert p['eligible'],p
    r=post(f,p);assert r.status_code==200,r.text
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s',(f[1][0],r.json()['product_id']));assert q.fetchone()==(Decimal(str(quantity)),)
