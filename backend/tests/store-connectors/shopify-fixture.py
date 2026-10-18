"""Real private adapter service with a deterministic Shopify upstream for tests."""
import json
import sys
import uvicorn
from src.ai.connectors import app as api
from src.ai.connectors.shopify import Shopify


def fetch(_url, payload, _headers):
    with open(sys.argv[2], encoding='utf-8') as stream:
        fixture = json.load(stream)
    query, after = payload['query'], payload.get('variables', {}).get('after')
    if fixture.get('throttled'):
        return {'errors': [{'extensions': {'code': 'THROTTLED'}}]}
    if 'query Verify' in query:
        return {'data': {'shop': {'id': 'gid://shopify/Shop/777', 'myshopifyDomain': 'test-shop.myshopify.com', 'currencyCode': 'JOD', 'plan': {'partnerDevelopment': True}},
                         'currentAppInstallation': {'accessScopes': [{'handle': s} for s in fixture['scopes']]}}}
    field = 'productVariants' if 'query Catalog' in query else 'orders'
    pages = fixture['catalog' if field == 'productVariants' else 'orders']
    index = int(after or 0)
    nodes = pages[index] if index < len(pages) else []
    more = index + 1 < len(pages)
    return {'data': {field: {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': str(index + 1) if more else None}}}}


class FixtureShopify(Shopify):
    def __init__(self, url, token, include_test_orders=False):
        super().__init__(url, token, fetch, include_test_orders)

api.Shopify = FixtureShopify
uvicorn.run(api.app, host='127.0.0.1', port=int(sys.argv[1]), log_level='error')
