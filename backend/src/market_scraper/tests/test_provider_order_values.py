from copy import deepcopy
import pytest
from src.market_scraper.provider_order_values import normalize_shopify_order as normalize_order,ProviderError

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




def test_woocommerce_refunds_are_allocated_and_keep_tax_shipping_separate():
    from src.ai.tests.test_provider_orders_integration_db import fixture_order
    from src.market_scraper.provider_order_values import normalize_woocommerce_order,validate_accounting_projection
    raw=fixture_order('woocommerce');raw.pop('keel_accounting');raw['refunds']=[{'id':900}]
    refund={'amount':'3.6666','line_items':[{'quantity':-1,'total':'-3.3333','total_tax':'-.3333','meta_data':[{'key':'_refunded_item_id','value':77}]}]}
    result=normalize_woocommerce_order(raw,lambda path:(refund,{}));validate_accounting_projection(result)
    assert result['invoice']['total']=='9.3334' and result['invoice']['tax']=='0.6667' and result['invoice']['shipping']=='2.0000'
    assert result['lines'][0]['quantity']==2 and result['lines'][0]['total']=='6.6667'
    with pytest.raises(ProviderError,match='UNALLOCATED_REFUND'):normalize_woocommerce_order(raw,lambda path:({'amount':'1','line_items':[]},{}))
    raw['status']='refunded';refund={'amount':'13','line_items':[{'quantity':-3,'total':'-10','total_tax':'-1','meta_data':[{'key':'_refunded_item_id','value':77}]},{'total':'-2','total_tax':'0','meta_data':[{'key':'_refunded_item_id','value':88}]}]}
    result=normalize_woocommerce_order(raw,lambda path:(refund,{}));assert result['invoice']['paymentStatus']=='CANCELLED' and result['invoice']['total']=='0.0000' and result['lines']==[] and result['invoice']['items']==[]
