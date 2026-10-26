import io,os
from decimal import Decimal
import pytest,psycopg2
from openpyxl import Workbook
from src.ai import db
from src.ai.routers import catalog,products
from src.ai.core.security import create_access_token
from src.ai.core.exceptions import register_exception_handlers
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.ai.routers.products import create_product,upsert_inventory

@pytest.fixture
def fixtures(setup):
    client,app,ts,us=setup;app.include_router(catalog.router);app.include_router(products.router);register_exception_handlers(app)
    conn=db.app_role_connection(ts[0],us[0])
    try:
        p=create_product(conn,ts[0],us[0],{'en':'Original catalog','ar':'catalog ar'},None,None,None,10,None,'JOD',sku='ORIGINAL-1');upsert_inventory(conn,ts[0],p['product_id'],Decimal(8));conn.commit()
    finally:conn.close()
    return client,ts,us,p

def query(tenant,sql,args=()):
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute(sql,(tenant,*args));return q.fetchall()

def test_original_catalog_shapes_search_archived_and_existing_python_pages(fixtures):
    client,ts,us,p=fixtures;r=client.get('/catalog/products',params={'search':'ORIGINAL-1'});assert r.status_code==200,r.text
    result=r.json();assert result['products'][0]['sku']=='ORIGINAL-1' and result['products'][0]['name']['en']=='Original catalog'
    assert result['pagination']['total']==1 and result['canEdit'] and result['capacity']['currentUsage']==1
    detail=client.get('/catalog/products/'+p['product_id']);assert detail.status_code==200,detail.text;assert detail.json()['inventory']['currentStock']==8
    assert client.get('/products/'+p['product_id']).status_code==200

def test_archive_restore_are_versioned_audited_and_preserve_stock(fixtures):
    client,ts,us,p=fixtures;url='/catalog/products/'+p['product_id'];version=p['version']
    assert client.post(url+'/archive',json={'expectedVersion':version}).status_code==200
    assert client.get('/products/'+p['product_id']).status_code==404
    assert client.get('/catalog/products',params={'status':'archived'}).json()['pagination']['total']==1
    assert client.post(url+'/restore',json={'expectedVersion':version}).status_code==409
    archived=client.get(url).json()['product'];assert archived['version']>version
    assert client.post(url+'/restore',json={'expectedVersion':archived['version']}).status_code==200
    assert client.get('/products/'+p['product_id']).json()['inventory']['stock_quantity']==8
    assert len(query(ts[0],"SELECT 1 FROM audit_logs WHERE tenant_id=%s AND action_type IN ('PRODUCT_ARCHIVED','PRODUCT_RESTORED')"))==2

def test_restore_refuses_duplicate_active_sku_and_capacity_is_authoritative(fixtures):
    client,ts,us,p=fixtures;url='/catalog/products/'+p['product_id'];client.post(url+'/archive',json={'expectedVersion':p['version']});version=client.get(url).json()['product']['version']
    conn=db.app_role_connection(ts[0],us[0])
    try:create_product(conn,ts[0],us[0],{'en':'Replacement'},None,None,None,10,None,'JOD',sku='ORIGINAL-1');conn.commit()
    finally:conn.close()
    assert client.post(url+'/restore',json={'expectedVersion':version}).status_code==409
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",(ts[0],))
    assert client.post(url+'/restore',json={'expectedVersion':version}).status_code==402
    assert client.get(url).json()['product']['archivedAt']

def preview(client,raw):return client.post('/catalog/products/gtin-import/preview',files={'file':('gtins.csv',raw)})

def test_gtin_preview_apply_persistence_audit_and_stale_retry(fixtures):
    client,ts,us,p=fixtures;r=preview(client,b'sku,gtin\nORIGINAL-1,3017620422003\n');assert r.status_code==200,r.text
    rows=[{k:v for k,v in r.json()['rows'][0].items() if k in ('productId','expectedVersion','gtin')}]
    assert not query(ts[0],"SELECT metadata->>'barcode' FROM products WHERE tenant_id=%s")[0][0]
    applied=client.post('/catalog/products/gtin-import/apply',json={'rows':rows});assert applied.status_code==200,applied.text
    assert query(ts[0],"SELECT metadata->>'barcode' FROM products WHERE tenant_id=%s")==[('3017620422003',)]
    assert client.post('/catalog/products/gtin-import/apply',json={'rows':rows}).status_code==409
    assert len(query(ts[0],"SELECT 1 FROM audit_logs WHERE tenant_id=%s AND action_type='PRODUCT_GTIN_UPDATED'"))==1

@pytest.mark.parametrize('raw',[b'sku,gtin\nORIGINAL-1,3017620422004\n',b'sku,gtin\nORIGINAL-1,3017620422003\noriginal-1,3017620422003\n',b'sku,gtin\nUNKNOWN,3017620422003\n',b'sku,gtin,extra\nORIGINAL-1,3017620422003,x\n'])
def test_invalid_gtin_file_cannot_write(fixtures,raw):
    client,ts,us,p=fixtures;assert preview(client,raw).status_code==422
    assert not query(ts[0],"SELECT metadata->>'barcode' FROM products WHERE tenant_id=%s")[0][0]

def test_xlsx_numeric_or_formula_gtin_is_rejected_and_text_is_preserved(fixtures):
    client,ts,us,p=fixtures
    for value,status in [(3017620422003,422),('=1+1',422),('3017620422003',200)]:
        book=Workbook();book.active.append(['sku','gtin']);book.active.append(['ORIGINAL-1',value]);stream=io.BytesIO();book.save(stream);book.close()
        r=client.post('/catalog/products/gtin-import/preview',files={'file':('gtins.xlsx',stream.getvalue())});assert r.status_code==status,r.text

def test_staff_cross_tenant_and_direct_unauthorized_requests(fixtures):
    client,ts,us,p=fixtures;url='/catalog/products/'+p['product_id']
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    assert client.get(url).status_code==404
    assert client.post(url+'/archive',json={'expectedVersion':p['version']}).status_code==404
    client.headers['Authorization']='Bearer '+create_access_token(ts[0],us[0],email_verified=True)[0]
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s",(ts[0],))
    assert not client.get('/catalog/products').json()['canEdit']
    assert client.post(url+'/archive',json={'expectedVersion':p['version']}).status_code==403
    assert preview(client,b'sku,gtin\nORIGINAL-1,3017620422003\n').status_code==403
    client.headers.clear();assert client.get('/catalog/products').status_code==401
