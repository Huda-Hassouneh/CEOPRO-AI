import json
from types import SimpleNamespace
from unittest.mock import Mock,MagicMock
import pytest
from src.market_scraper.provider_incremental import next_order_continuation,woo_modified_after,load_order_watermark
from src.market_scraper.shopify import ShopifyGraphQLClient,ShopifyError
from src.market_scraper.woocommerce import WooCommerceClient

def test_order_watermark_uses_provider_time_not_wall_clock_and_never_skips_invalid_records():
    records=[SimpleNamespace(entity_type='order',payload={'updatedAt':'2026-10-25T12:00:00Z'}),SimpleNamespace(entity_type='line_item',payload={})]
    assert next_order_continuation(records,'shopify')=={'modified_since':'2026-10-25T12:00:00Z'}
    records.append(SimpleNamespace(entity_type='order',payload={}))
    assert next_order_continuation(records,'shopify')=={}
    assert next_order_continuation(records,'shopify','2026-10-24T00:00:00Z')=={'modified_since':'2026-10-24T00:00:00Z'}
    assert woo_modified_after('2026-10-25T12:00:00.999Z')=='2026-10-25T11:59:59Z'

def test_shopify_incremental_query_is_inclusive_and_validated():
    client=object.__new__(ShopifyGraphQLClient);client._page_size=20
    client.verify_connection=lambda:{'granted_scopes':frozenset({'read_orders'})}
    captured=[];client._iterate_connection=lambda q,path,variables:(captured.append((q,variables)) or [])
    assert list(client.iter_orders(modified_since='2026-10-25T12:00:00Z'))==[]
    query,variables=captured[0];assert 'query:$query' in query and variables['query']=="updated_at:>='2026-10-25T12:00:00Z'"
    with pytest.raises(ShopifyError):list(client.iter_orders(modified_since="invalid' OR anything"))

def test_woo_incremental_filter_keeps_boundary_overlap_and_gmt():
    client=object.__new__(WooCommerceClient);client._api_root='https://synthetic.example/wp-json/wc/v3';client._page_size=20
    urls=[];client._pages=lambda url:(urls.append(url) or [])
    assert list(client.iter_orders(modified_since='2026-10-25T12:00:00Z'))==[]
    assert 'modified_after=2026-10-25T11%3A59%3A59Z' in urls[0] and 'dates_are_gmt=true' in urls[0]
    with pytest.raises(ValueError):list(client.iter_orders(modified_since='invalid'))

def test_checkpoint_is_configuration_version_bound():
    conn=Mock();cursor=MagicMock();conn.cursor.return_value=cursor
    cursor.__enter__.return_value.fetchone.return_value=({'modified_since':'2026-10-25T12:00:00Z'},)
    assert load_order_watermark(conn,'tenant',{'source_id':'source','configuration_version':5})=='2026-10-25T12:00:00Z'
    args=cursor.__enter__.return_value.execute.call_args.args
    assert 'configuration_version=%s' in args[0] and args[1]==('tenant','source',5)
