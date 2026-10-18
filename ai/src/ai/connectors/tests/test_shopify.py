from copy import deepcopy
import pytest
from src.ai.connectors.shopify import Shopify, normalize_order, connection, shop_domain, valid_gtin
from src.ai.connectors.transport import ProviderError


def amount(value):
    return {'shopMoney': {'amount': str(value), 'currencyCode': 'JOD'}}


def raw_order():
    line = {'id': 'gid://shopify/LineItem/1', 'name': 'Real model', 'sku': 'REAL01', 'quantity': 3,
            'currentQuantity': 3, 'variant': {'id': 'gid://shopify/ProductVariant/101'},
            'priceAfterAllDiscountsBeforeTaxesSet': amount('10')}
    return {'id': 'gid://shopify/Order/900', 'createdAt': '2026-10-10T09:00:00Z', 'updatedAt': '2026-10-17T09:00:00Z',
            'processedAt': '2026-10-10T09:00:00Z', 'cancelledAt': None, 'closed': False, 'test': False, 'currencyCode': 'JOD',
            'displayFinancialStatus': 'PAID', 'displayFulfillmentStatus': 'UNFULFILLED',
            'transactions': [{'kind': 'SALE', 'status': 'SUCCESS', 'processedAt': '2026-10-10T09:01:00Z'}],
            'currentSubtotalPriceSet': amount('10'), 'currentShippingPriceSet': amount('2'), 'currentTotalPriceSet': amount('13.6'),
            'currentTotalTaxSet': amount('1.6'), 'currentTotalAdditionalFeesSet': None, 'currentTotalDutiesSet': None,
            'currentTotalDiscountsSet': amount('5'), 'totalPriceSet': amount('13.6'), 'totalRefundedSet': amount('0'),
            'email': 'must-not-import@example.test', 'lineItems': page([line])}


def page(nodes, more=False, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def test_shopify_paid_sales_are_financial_not_fulfillment_and_minimize_data():
    raw = raw_order()
    result = normalize_order(raw, raw['lineItems']['nodes'])
    assert result['status'] == 'open' and result['salesEligible'] is True
    assert result['invoice']['paymentStatus'] == 'PAID'
    assert result['lines'][0]['unitPrice'] == '3.3333'
    assert result['invoice']['total'] == '13.6000'
    assert 'must-not-import' not in str(result)
    for status, expected in [('PENDING', 'UNPAID'), ('PARTIALLY_PAID', 'PARTIAL'), ('AUTHORIZED', 'UNPAID')]:
        raw['displayFinancialStatus'] = status
        value = normalize_order(raw, raw['lineItems']['nodes'])
        assert not value['lines'] and value['invoice']['paymentStatus'] == expected


def test_refund_uses_current_quantity_and_amount_and_reconciles():
    raw = raw_order()
    raw['displayFinancialStatus'] = 'PARTIALLY_REFUNDED'
    raw['lineItems']['nodes'][0]['currentQuantity'] = 2
    raw['lineItems']['nodes'][0]['priceAfterAllDiscountsBeforeTaxesSet'] = amount('6')
    raw['currentTotalPriceSet'], raw['currentSubtotalPriceSet'] = amount('9.6'), amount('6')
    raw['totalRefundedSet'] = amount('4')
    value = normalize_order(raw, raw['lineItems']['nodes'])
    assert value['lines'][0]['quantity'] == 2
    assert value['invoice']['refundedTotal'] == '4.0000'
    raw['cancelledAt'] = '2026-10-17T09:00:00Z'
    assert normalize_order(raw, raw['lineItems']['nodes'])['invoice']['paymentStatus'] == 'CANCELLED'


@pytest.mark.parametrize('change,code', [
    (lambda r: r.update(currentTotalPriceSet=amount('999')), 'TOTAL_MISMATCH'),
    (lambda r: r.update(transactions=[]), 'PAYMENT_EVIDENCE'),
    (lambda r: r.update(currentTotalDutiesSet=amount('1')), 'UNSUPPORTED_DUTIES'),
    (lambda r: r['lineItems']['nodes'][0].update(variant=None), 'PRODUCT_UNAVAILABLE'),
    (lambda r: r['currentTotalTaxSet']['shopMoney'].update(currencyCode='USD'), 'CURRENCY_MISMATCH'),
])
def test_ambiguous_financial_data_never_guessed(change, code):
    raw = raw_order(); change(raw)
    with pytest.raises(ProviderError, match=code):
        normalize_order(raw, raw['lineItems']['nodes'])


def test_catalog_variants_location_pagination_and_gtin():
    calls = []
    def upstream(url, body, headers):
        calls.append(body)
        assert url.startswith('https://test-shop.myshopify.com/admin/api/2026-10/')
        assert headers['X-Shopify-Access-Token'] == 'test-token-value'
        level = {'location': {'id': 'gid://shopify/Location/1'}, 'quantities': [{'name': 'on_hand', 'quantity': 4}]}
        if 'query Levels' in body['query']:
            level['location']['id'] = 'gid://shopify/Location/2'
            level['quantities'][0]['quantity'] = 0
            return {'data': {'inventoryItem': {'inventoryLevels': page([level])}}}
        variant = {'id': 'gid://shopify/ProductVariant/101', 'title': 'Black', 'sku': 'REAL01', 'barcode': '4006381333931', 'price': '12.5',
                   'product': {'id': 'gid://shopify/Product/1', 'title': 'Real model', 'status': 'ACTIVE'},
                   'inventoryItem': {'id': 'gid://shopify/InventoryItem/3', 'tracked': True, 'inventoryLevels': page([level], True, 'second-location')}}
        return {'data': {'productVariants': page([variant], True, 'second-variant')}}
    result = Shopify('https://test-shop.myshopify.com', 'test-token-value', upstream).products(None, 'JOD')
    assert result['nextCursor'] == 'second-variant'
    assert result['items'][0]['gtin'] == '4006381333931'
    assert [l['quantity'] for l in result['items'][0]['locations']] == [4, 0]
    assert len(calls) == 2


def test_graphql_throttling_partial_errors_and_scopes():
    provider = Shopify('test-shop.myshopify.com', 'test-token-value', lambda *_: {'errors': [{'extensions': {'code': 'THROTTLED'}}], 'data': {}})
    with pytest.raises(ProviderError, match='RATE_LIMITED'):
        provider.verify()
    provider.fetch = lambda *_: {'data': {'shop': {}, 'currentAppInstallation': {'accessScopes': []}}}
    with pytest.raises(ProviderError, match='SCOPES_REQUIRED'):
        provider.verify()


def test_graphql_rejection_logs_cause_without_credentials_or_response_data(caplog):
    token = 'shpat_private_test_token'
    response = {'errors': [{'message': 'Access denied for orders field. ' + token,
                            'path': ['orders'], 'extensions': {'code': 'ACCESS_DENIED'}}],
                'data': {'orders': {'customer': 'must-not-log'}}}
    provider = Shopify('test-shop.myshopify.com', token, lambda *_: response)
    with pytest.raises(ProviderError, match='STORE_SHOPIFY_QUERY_ERROR'):
        provider.orders(None, None, '2026-10-18T00:00:00Z')
    assert 'operation=Orders' in caplog.text
    assert 'code=ACCESS_DENIED' in caplog.text
    assert 'Access denied for orders field.' in caplog.text
    assert token not in caplog.text and 'must-not-log' not in caplog.text
    assert '[REDACTED]' in caplog.text


def test_graphql_rejection_logging_is_bounded_and_handles_null_extensions(caplog):
    errors = [{'message': 'x' * 1000 + '\nforged log', 'extensions': None}] * 10
    provider = Shopify('test-shop.myshopify.com', 'test-token-value',
                       lambda *_: {'errors': errors})
    with pytest.raises(ProviderError, match='STORE_SHOPIFY_QUERY_ERROR'):
        provider.verify()
    assert len(caplog.records) == 3
    assert 'forged log' not in caplog.text


@pytest.mark.parametrize('host', ['https://127.0.0.1', 'evil.myshopify.com.attacker.test', 'https://test.myshopify.com@evil.test', 'https://test.myshopify.com:444', 'https://test.myshopify.com/path'])
def test_host_boundary(host):
    # Node and adapter both enforce canonical Shopify domains, including URL shape.
    with pytest.raises(ProviderError):
        shop_domain(host)


def test_order_pagination_and_test_order_opt_in():
    raw = raw_order(); raw['test'] = True
    calls = []
    def upstream(_url, body, _headers):
        calls.append(body)
        if 'query Lines' in body['query']:
            extra = deepcopy(raw['lineItems']['nodes'][0]); extra['id'] = 'gid://shopify/LineItem/2'
            return {'data': {'order': {'lineItems': page([extra])}}}
        return {'data': {'orders': page([raw], True, 'next-order')}}
    provider = Shopify('test-shop.myshopify.com', 'test-token-value', upstream)
    assert provider.orders(None, None, '2026-10-18T00:00:00Z')['items'] == []
    assert 'transactions(first:' not in calls[0]['query']
    assert 'transactions { kind status processedAt }' in calls[0]['query']
    provider.include_tests = True
    assert len(provider.orders(None, None, '2026-10-18T00:00:00Z')['items']) == 1
    assert 'updated_at:<=' in calls[0]['variables']['query']


def test_pagination_requires_cursor_and_valid_gtin_check_digit():
    with pytest.raises(ProviderError, match='PAGINATION'):
        connection(page([], True, None))
    assert valid_gtin('4006381333932') is None
    assert valid_gtin('private-barcode') is None
    assert valid_gtin('4006381333931') == '4006381333931'
