import hashlib
import json
import time
from unittest.mock import patch
import jwt
import pytest
from fastapi.testclient import TestClient
from src.ai.connectors.woocommerce import WooCommerce, ProviderError
from src.ai.connectors.app import app
from src.ai.connectors.transport import get_json

URL='https://store.example.test'
KEY='ck_'+'a'*40
SECRET='cs_'+'b'*40

def provider(fetch):return WooCommerce(URL,KEY,SECRET,fetch)

def response(value,more=1):return value,{'X-WP-TotalPages':str(more)}

def test_detection_verify_requires_products_orders_and_currency():
    calls=[]
    def fetch(url,authorization):
        calls.append((url,authorization))
        if url.endswith('woocommerce_currency'):return response({'value':'JOD'})
        return response([])
    assert provider(fetch).verify()['currency']=='JOD'
    assert len(calls)==3
    assert all(auth.startswith('Basic ') and KEY not in url and SECRET not in url for url,auth in calls)
    assert WooCommerce(URL,fetch=lambda *_:response({'namespaces':['wp/v2','wc/v3']})).detect()['supported']


def test_pages_variations_and_minimal_normalized_products():
    def fetch(url,_):
        if '/variations?' in url:return response([{'id':202,'sku':'BLUE','price':'3','attributes':[{'option':'Blue'}]}])
        return response([{'id':101,'type':'variable','name':'Shirt'}])
    result=provider(fetch).products(1,'JOD',None,None)
    assert result['contractVersion']==2
    assert result['items'][0]=={'externalId':'202','sku':'BLUE','name':'Shirt — Blue','price':'3.0000','currency':'JOD','inventory':{'state':'unmanaged','quantity':None,'stockStatus':None,'lowStockThreshold':None,'stockOwnerExternalId':None}}
    assert not result['hasMore']
    with pytest.raises(ProviderError,match='PAGINATION'):
        provider(lambda *_:([],{})).products(1,'JOD',None,None)


def order(**changes):
    return {'id':900,'status':'completed','currency':'JOD','date_created_gmt':'2026-10-10T09:00:00','date_modified_gmt':'2026-10-10T09:00:00',
        'total':'6.00','total_tax':'0','shipping_total':'0',
        'billing':{'email':'private@example.test'},'customer_id':33,'refunds':[],
        'line_items':[{'id':8,'product_id':101,'variation_id':202,'sku':'BLUE','name':'Shirt Blue','quantity':3,'total':'6.00'}],**changes}


def test_order_items_discounts_dates_and_privacy():
    result=provider(lambda *_:None).order(order())
    line=result['lines'][0]
    assert line['productExternalId']=='202' and line['quantity']==3 and line['total']=='6.0000'
    assert line['unitPrice']=='2.0000' and line['date'].endswith('+00:00')
    assert 'billing' not in json.dumps(result) and 'private@example.test' not in json.dumps(result)
    for status in ('pending','processing','on-hold','cancelled','refunded','failed','trash'):
        assert provider(lambda *_:None).order(order(status=status,**({'total':'0','line_items':[]} if status=='refunded' else {})))['lines']==[]


def test_allocated_partial_refund_and_unallocated_refund_rejection():
    refunded={'amount':'2.00','line_items':[{'quantity':-1,'total':'-2.00','meta_data':[{'key':'_refunded_item_id','value':8}]}]}
    result=provider(lambda *_:response(refunded)).order(order(refunds=[{'id':1}]))
    assert result['lines'][0]['quantity']==2 and result['lines'][0]['total']=='4.0000'
    refunded['line_items']=[]
    with pytest.raises(ProviderError,match='UNALLOCATED_REFUND'):
        provider(lambda *_:response(refunded)).order(order(refunds=[{'id':1}]))


def test_incremental_bounds_include_changed_orders_without_status_filter():
    calls=[]
    def fetch(url,_):calls.append(url);return response([],0)
    provider(fetch).orders(1,'2026-10-01T00:00:00Z','2026-10-02T00:00:00Z')
    assert 'modified_after=' in calls[0] and 'modified_before=' in calls[0] and 'dates_are_gmt=true' in calls[0]
    assert 'status=completed' not in calls[0]


@pytest.mark.parametrize('url',['http://shop.example','https://user:pass@shop.example','https://shop.example:8443','https://shop.example/?consumer_key=secret','https://shop.example/%2e%2e'])
def test_unsafe_store_urls(url):
    with pytest.raises(ProviderError):WooCommerce(url)


def test_transport_no_plaintext_credentials_or_redirect_following():
    with pytest.raises(ProviderError):get_json('http://example.test','Basic secret')
    class Connection:
        def __init__(self,*_,**__):pass
        def request(self,*_,**__):pass
        def getresponse(self):return type('Response',(),{'status':302})()
        def close(self):pass
    with patch('src.ai.connectors.transport.PublicConnection',Connection):
        with pytest.raises(ProviderError,match='STORE_RESPONSE_ERROR'):get_json(URL,'Basic secret')


def test_private_service_requires_short_lived_signed_request_and_hides_validation_secrets(monkeypatch):
    secret='test-service-secret-'+'a'*32
    monkeypatch.setenv('STORE_CONNECTOR_SERVICE_SECRET',secret)
    client=TestClient(app)
    payload={'action':'detect','url':URL}
    body=json.dumps(payload).encode()
    def auth(body,expiry=60):
        return {'Authorization':'Bearer '+jwt.encode({'aud':'keel-store-adapter','tenant':'11111111-1111-4111-8111-111111111111','iat':int(time.time()),'exp':int(time.time())+expiry,'body_hash':hashlib.sha256(body).hexdigest()},secret,algorithm='HS256')}
    assert client.post('/provider',content=body).status_code==401
    assert client.post('/provider',content=body,headers=auth(body,-1)).status_code==401
    assert client.post('/provider',content=body+b' ',headers=auth(body)).status_code==401
    with patch('src.ai.connectors.app.execute',return_value={'supported':True}):
        assert client.post('/provider',content=body,headers=auth(body)).json()=={'supported':True}
    invalid=json.dumps({**payload,'secret':'do-not-echo-me','extra':'bad'}).encode()
    result=client.post('/provider',content=invalid,headers=auth(invalid))
    assert result.status_code==422 and 'do-not-echo-me' not in result.text


def test_order_pagination_uses_first_remaining_page_and_rejects_ignored_exclusions():
    calls=[]
    def fetch(url,_):calls.append(url);return response([order()],2)
    with pytest.raises(ProviderError,match='PAGINATION_UNVERIFIED'):
        provider(fetch).orders(7,None,None,['900'])
    assert 'page=1' in calls[0] and 'exclude=900' in calls[0]


def test_unpriced_catalog_items_are_not_invented_as_zero_price_products():
    records=[{'id':1,'type':'simple','name':'Unpriced','price':''},{'id':2,'type':'simple','name':'Free item','price':'0'}]
    result=provider(lambda *_:response(records)).products(1,'JOD',None,None)
    assert len(result['items'])==1 and result['items'][0]['externalId']=='2' and result['items'][0]['price']=='0.0000'


def test_missing_order_line_name_is_rejected_instead_of_invented():
    value=order();value['line_items'][0]['name']=None
    with pytest.raises(ProviderError,match='INVALID_DATA'):provider(lambda *_:None).order(value)


def test_refund_allocation_includes_refunded_tax_but_sales_total_excludes_tax():
    value={'amount':'2.32','line_items':[{'quantity':-1,'total':'-2.00','total_tax':'-0.32','meta_data':[{'key':'_refunded_item_id','value':8}]}]}
    taxed=order(refunds=[{'id':1}],total='6.96',total_tax='0.96');taxed['line_items'][0]['total_tax']='0.96'
    result=provider(lambda *_:response(value)).order(taxed)
    assert result['lines'][0]['quantity']==2 and result['lines'][0]['total']=='4.0000'


def test_inventory_managed_unknown_shared_and_no_fabricated_safety_stock():
    from src.ai.connectors.inventory import normalize_inventory
    raw={'id':1,'manage_stock':True,'stock_quantity':31,'stock_status':'instock','low_stock_amount':5}
    assert normalize_inventory(raw)=={'state':'managed','quantity':31,'stockStatus':'instock','lowStockThreshold':5,'stockOwnerExternalId':None}
    assert normalize_inventory({**raw,'stock_quantity':0})['quantity']==0
    assert normalize_inventory({**raw,'stock_quantity':None})['quantity'] is None
    assert normalize_inventory({**raw,'manage_stock':False})['quantity'] is None
    shared=normalize_inventory({'id':2,'manage_stock':'parent','stock_quantity':31},raw)
    assert shared['state']=='shared' and shared['quantity'] is None and shared['stockOwnerExternalId']=='1'
    for invalid in [-1,1.5,True]:
        with pytest.raises(ProviderError,match='UNSUPPORTED_STOCK'):normalize_inventory({**raw,'stock_quantity':invalid})


def test_paid_invoice_totals_include_shipping_tax_and_fees_without_counting_discount_twice():
    value=order(total='9.12',total_tax='1.12',shipping_total='1.50',discount_total='3.00',date_paid_gmt='2026-10-10T09:01:00',
        shipping_lines=[{'id':9,'total':'1.50','total_tax':'0.24'}],fee_lines=[{'id':10,'total':'0.50','total_tax':'0.08'}])
    value['line_items'][0]['total_tax']='0.80'
    result=provider(lambda *_:None).order(value)
    assert result['invoice']['paymentStatus']=='PAID'
    assert result['invoice']['total']=='9.1200' and result['invoice']['subtotal']=='8.0000'
    assert result['invoice']['shipping']=='1.5000' and result['invoice']['fees']=='0.5000'
    assert result['invoice']['discount']=='3.0000'
    assert result['lines'][0]['total']=='6.0000'
    assert provider(lambda *_:None).order(order())['invoice']['paymentStatus']=='UNPAID'
    assert provider(lambda *_:None).order(order(status='processing',date_paid_gmt='2026-10-10T09:01:00'))['invoice']['paymentStatus']=='PAID'


def test_refunds_reconcile_tax_and_shipping_and_reject_unexplained_totals():
    value=order(total='8.12',total_tax='1.12',shipping_total='1.00',date_paid_gmt='2026-10-10T09:01:00',
        shipping_lines=[{'id':9,'total':'1.00','total_tax':'0.16'}],refunds=[{'id':1}])
    value['line_items'][0]['total_tax']='0.96'
    refund={'amount':'3.48','line_items':[{'quantity':-1,'total':'-2','total_tax':'-0.32','meta_data':[{'key':'_refunded_item_id','value':8}]},
        {'quantity':0,'total':'-1','total_tax':'-0.16','meta_data':[{'key':'_refunded_item_id','value':9}]}]}
    result=provider(lambda *_:response(refund)).order(value)
    assert result['invoice']['total']=='4.6400' and result['invoice']['tax']=='0.6400'
    assert result['invoice']['shipping']=='0.0000' and result['invoice']['paymentStatus']=='PAID'
    assert result['invoice']['refundedTotal']=='3.4800'
    with pytest.raises(ProviderError,match='TOTAL_MISMATCH'):provider(lambda *_:None).order(order(total='999'))
    with pytest.raises(ProviderError,match='TOTAL_MISMATCH'):provider(lambda *_:None).order(order(status='refunded'))


def test_full_refund_cancel_and_repeating_discounted_unit_rate():
    refund={'amount':'6','line_items':[{'quantity':-3,'total':'-6','meta_data':[{'key':'_refunded_item_id','value':8}]}]}
    result=provider(lambda *_:response(refund)).order(order(status='refunded',refunds=[{'id':1}],date_paid_gmt='2026-10-10T09:01:00'))
    assert result['invoice']['total']=='0.0000' and result['invoice']['paymentStatus']=='CANCELLED'
    assert not result['invoice']['items'] and not result['lines']
    assert provider(lambda *_:None).order(order(status='cancelled',date_paid_gmt='2026-10-10T09:01:00'))['invoice']['paymentStatus']=='CANCELLED'
    value=order(total='10');value['line_items'][0]['total']='10'
    result=provider(lambda *_:None).order(value)
    assert result['invoice']['items'][0]['unitPrice']=='3.3333' and result['invoice']['total']=='10.0000'
