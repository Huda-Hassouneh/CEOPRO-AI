"""Isolated test upstream: real adapter and service auth; no production entrypoint."""
import sys
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit, parse_qs
import uvicorn
from src.ai.connectors import app as api
from src.ai.connectors.woocommerce import WooCommerce

def upstream(url, authorization):
    path=urlsplit(url).path
    limit=int(parse_qs(urlsplit(url).query).get('per_page',['20'])[0])
    if path=='/wp-json/':return {'namespaces':['wc/v3']},{}
    assert authorization and authorization.startswith('Basic ')
    if path.endswith('woocommerce_currency'):return {'value':'JOD'},{}
    if path.endswith('/products'):
        return [{'id':101,'type':'simple','name':'Fixture Tea','sku':'TEA001','price':'2.50','manage_stock':True,'stock_quantity':31,'stock_status':'instock','low_stock_amount':5}][:limit],{'X-WP-TotalPages':'1'}
    if path.endswith('/orders'):
        return [{'id':900,'status':'completed','currency':'JOD','date_created_gmt':'2026-10-10T10:00:00','date_modified_gmt':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),'refunds':[],
            'date_paid_gmt':'2026-10-10T10:00:00','total':'4.00','total_tax':'0','shipping_total':'0',
            'billing':{'email':'must-not-be-imported@example.test'},
            'line_items':[{'id':8,'product_id':101,'variation_id':0,'name':'Fixture Tea','sku':'TEA001','quantity':2,'total':'4.00'}]}][:limit],{'X-WP-TotalPages':'1'}
    raise AssertionError('Unexpected fixture request')

class FixtureWoo(WooCommerce):
    def __init__(self,url,key=None,secret=None):super().__init__(url,key,secret,upstream)

api.WooCommerce=FixtureWoo
uvicorn.run(api.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
