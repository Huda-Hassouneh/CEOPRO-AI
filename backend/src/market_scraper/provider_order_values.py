"""Original provider accounting normalizers, adapted without its HTTP service.
Reference: original ai/src/ai/connectors/{values,orders,shopify}.py (read-only).
No canonical writes, payment guesses, customer PII or model changes.
"""
"""Strict provider values shared by catalog, stock and order mapping."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
class ProviderError(ValueError):
    """Safe provider accounting diagnostic, never a provider payload."""

def identifier(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,18}', str(value)):
        raise ProviderError('STORE_INVALID_DATA')
    return str(value)

def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number >= 100000000:
            raise ValueError()
        return number.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation):
        raise ProviderError('STORE_INVALID_DATA') from None

def timestamp(value):
    try:
        if not isinstance(value, str) or not value:
            raise ValueError()
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        raise ProviderError('STORE_INVALID_DATA') from None


STATUSES = {'pending', 'processing', 'on-hold', 'completed', 'cancelled', 'refunded', 'failed', 'trash'}

def amount(value):
    return money(value)

def quantity(value, refund=False):
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 999999999 or (not refund and value <= 0):
        raise ProviderError('STORE_INVALID_DATA')
    if refund and value > 0:
        raise ProviderError('STORE_INVALID_DATA')
    return abs(value)

def negative_amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number > 0:
            raise ValueError()
        return amount(-number)
    except (ValueError, ArithmeticError):
        raise ProviderError('STORE_INVALID_DATA') from None

def normalize_woocommerce_order(raw, call):
    order_id = identifier(raw['id'])
    status = raw.get('status')
    currency = raw.get('currency')
    if status not in STATUSES or not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
        raise ProviderError('STORE_INVALID_DATA')
    modified, created = timestamp(raw.get('date_modified_gmt')), timestamp(raw.get('date_created_gmt'))
    paid = timestamp(raw['date_paid_gmt']) if raw.get('date_paid_gmt') else None
    completed = timestamp(raw.get('date_completed_gmt') or raw.get('date_created_gmt'))
    originals = {}
    for field, kind in [('line_items', 'product'), ('shipping_lines', 'shipping'), ('fee_lines', 'fee')]:
        values = raw.get(field, [])
        if not isinstance(values, list) or len(values) > 500:
            raise ProviderError('STORE_LIMIT_EXCEEDED')
        for line in values:
            key = identifier(line['id'])
            if key in originals:
                raise ProviderError('STORE_INVALID_DATA')
            originals[key] = {'kind': kind, 'raw': line, 'total': amount(line['total']),
                              'tax': amount(line.get('total_tax', '0')), 'refund': Decimal(0), 'refundTax': Decimal(0), 'refundQuantity': 0}
    refunded = Decimal(0)
    refund_ids = set()
    for summary in raw.get('refunds', []):
        refund_id = identifier(summary['id'])
        if refund_id in refund_ids:
            raise ProviderError('STORE_INVALID_DATA')
        refund_ids.add(refund_id)
        data, _ = call('wc/v3/orders/' + order_id + '/refunds/' + refund_id)
        allocated = Decimal(0)
        for line in data.get('line_items', []):
            refs = [m.get('value') for m in line.get('meta_data', []) if m.get('key') == '_refunded_item_id']
            if len(refs) != 1 or str(refs[0]) not in originals:
                raise ProviderError('STORE_UNALLOCATED_REFUND')
            target = originals[str(refs[0])]
            net, tax = negative_amount(line['total']), negative_amount(line.get('total_tax', '0'))
            target['refund'] += net
            target['refundTax'] += tax
            if target['kind'] == 'product':
                target['refundQuantity'] += quantity(line.get('quantity'), refund=True)
            allocated += net + tax
        # An amount-only refund cannot safely be assigned to product sales.
        if amount(data['amount']) != allocated:
            raise ProviderError('STORE_UNALLOCATED_REFUND')
        refunded += allocated

    original_subtotal = sum((x['total'] for x in originals.values()), Decimal(0))
    original_tax = sum((x['tax'] for x in originals.values()), Decimal(0))
    original_total = amount(raw['total'])
    if original_tax != amount(raw['total_tax']) or original_total != original_subtotal + original_tax:
        raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    # Cross-check independent header amounts; discounts are already applied to
    # each line.total, so discount_total is provenance, not another deduction.
    shipping_original = sum((x['total'] for x in originals.values() if x['kind'] == 'shipping'), Decimal(0))
    if amount(raw.get('shipping_total', '0')) != shipping_original:
        raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    items, net_by_kind = [], {'product': Decimal(0), 'shipping': Decimal(0), 'fee': Decimal(0)}
    tax_total = Decimal(0)
    for key, entry in originals.items():
        line = entry['raw']
        net, tax = entry['total'] - entry['refund'], entry['tax'] - entry['refundTax']
        if net < 0 or tax < 0:
            raise ProviderError('STORE_INVALID_DATA')
        net_by_kind[entry['kind']] += net
        tax_total += tax
        if entry['kind'] != 'product':
            continue
        count = quantity(line.get('quantity')) - entry['refundQuantity']
        if count < 0 or count == 0 and net != 0:
            raise ProviderError('STORE_INVALID_DATA')
        if not count:
            continue
        name, sku = line.get('name'), line.get('sku') or None
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ProviderError('STORE_INVALID_DATA')
        if sku and (not isinstance(sku, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', sku)):
            raise ProviderError('STORE_INVALID_SKU')
        items.append({'externalId': key, 'productExternalId': identifier(line.get('variation_id') or line['product_id']),
                      'name': name, 'sku': sku, 'quantity': count,
                      'unitPrice': str((net / count).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)),
                      'total': str(net), 'currency': currency, 'date': completed})
    subtotal = sum(net_by_kind.values())
    total = subtotal + tax_total
    if total != original_total - refunded:
        raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    if status == 'refunded' and total != 0:
        raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    payment_status = 'CANCELLED' if status in {'cancelled', 'failed', 'trash', 'refunded'} or refunded > 0 and total == 0 else 'PAID' if paid else 'UNPAID'
    invoice = {'currency': currency, 'issuedAt': created, 'paidAt': paid, 'paymentStatus': payment_status,
               'subtotal': str(subtotal), 'tax': str(tax_total), 'total': str(total),
               'merchandise': str(net_by_kind['product']), 'shipping': str(net_by_kind['shipping']),
               'fees': str(net_by_kind['fee']), 'discount': str(amount(raw.get('discount_total', '0'))),
               'originalTotal': str(original_total), 'refundedTotal': str(refunded), 'items': items}
    return {'externalId': order_id, 'modifiedAt': modified, 'status': status,
            'invoice': invoice, 'lines': items if status == 'completed' and payment_status != 'CANCELLED' else []}

def gid(value, kind):
    if not isinstance(value,str) or not re.fullmatch(r'gid://shopify/'+kind+r'/[1-9][0-9]{0,19}',value):raise ProviderError('STORE_INVALID_DATA')
    return value

def normalize_shopify_order(raw, lines):
    currency = raw['currencyCode']
    if not re.fullmatch('[A-Z]{3}', currency) or len(lines) > 500:
        raise ProviderError('STORE_INVALID_DATA')

    def amount(field, optional=False):
        bag = raw.get(field)
        if bag is None and optional:
            return Decimal(0)
        if not isinstance(bag, dict) or bag.get('shopMoney', {}).get('currencyCode') != currency:
            raise ProviderError('STORE_CURRENCY_MISMATCH')
        return money(bag['shopMoney']['amount'])

    total, tax = amount('currentTotalPriceSet'), amount('currentTotalTaxSet')
    shipping, fees = amount('currentShippingPriceSet'), amount('currentTotalAdditionalFeesSet', True)
    duties = amount('currentTotalDutiesSet', True)
    if duties:
        raise ProviderError('STORE_UNSUPPORTED_DUTIES')
    original, refunded = amount('totalPriceSet'), amount('totalRefundedSet')
    financial = raw.get('displayFinancialStatus')
    if financial not in {'PAID', 'PARTIALLY_REFUNDED', 'REFUNDED', 'PARTIALLY_PAID', 'PENDING', 'AUTHORIZED', 'EXPIRED', 'VOIDED'}:
        raise ProviderError('STORE_INVALID_DATA')
    cancelled = bool(raw.get('cancelledAt')) or financial in {'REFUNDED', 'VOIDED', 'EXPIRED'}
    transactions = raw.get('transactions', [])
    if len(transactions) >= 100:
        raise ProviderError('STORE_LIMIT_EXCEEDED')
    payments = [timestamp(t['processedAt']) for t in transactions if t.get('kind') in {'SALE', 'CAPTURE'} and t.get('status') == 'SUCCESS' and t.get('processedAt')]
    paid_at = max(payments) if payments else None
    eligible = not cancelled and financial in {'PAID', 'PARTIALLY_REFUNDED'}
    if eligible and not paid_at:
        raise ProviderError('STORE_PAYMENT_EVIDENCE_MISSING')
    status = 'cancelled' if cancelled else 'closed' if raw.get('closed') else 'open'
    payment = 'CANCELLED' if cancelled else 'PAID' if eligible else 'PARTIAL' if financial == 'PARTIALLY_PAID' else 'UNPAID'
    date = timestamp(raw.get('processedAt') or raw['createdAt'])
    items = []
    for line in lines:
        count = line.get('currentQuantity')
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 999999999:
            raise ProviderError('STORE_INVALID_DATA')
        bag = line.get('priceAfterAllDiscountsBeforeTaxesSet', {}).get('shopMoney', {})
        if bag.get('currencyCode') != currency:
            raise ProviderError('STORE_CURRENCY_MISMATCH')
        net = money(bag.get('amount'))
        if not count:
            if net:
                raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
            continue
        if not line.get('variant'):
            raise ProviderError('STORE_PRODUCT_UNAVAILABLE')
        sku = line.get('sku') or None
        if sku and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', sku):
            raise ProviderError('STORE_INVALID_SKU')
        items.append({'externalId': gid(line['id'], 'LineItem'), 'productExternalId': gid(line['variant']['id'], 'ProductVariant'),
                      'name': line['name'], 'sku': sku, 'quantity': count,
                      'unitPrice': str((net / count).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)),
                      'total': str(net), 'currency': currency, 'date': date})
    merchandise = sum((Decimal(l['total']) for l in items), Decimal(0))
    subtotal = merchandise + shipping + fees
    if len({l['externalId'] for l in items}) != len(items) or subtotal + tax != total or original - refunded != total:
        # Includes amount-only refunds/order edits that cannot be reconciled.
        raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    invoice = {'currency': currency, 'issuedAt': timestamp(raw['createdAt']), 'paidAt': paid_at,
               'paymentStatus': payment, 'subtotal': str(subtotal), 'tax': str(tax), 'total': str(total),
               'merchandise': str(merchandise), 'shipping': str(shipping), 'fees': str(fees),
               'discount': str(amount('currentTotalDiscountsSet')), 'originalTotal': str(original),
               'refundedTotal': str(refunded), 'items': items}
    return {'externalId': gid(raw['id'], 'Order'), 'modifiedAt': timestamp(raw['updatedAt']), 'status': status,
            'financialStatus': financial, 'salesEligible': eligible, 'invoice': invoice, 'lines': items if eligible else []}


def validate_accounting_projection(value):
    """Strict JSON boundary: no customer/payment tokens or arbitrary nested fields."""
    import json
    allowed={'externalId','modifiedAt','status','financialStatus','salesEligible','invoice','lines'}
    invoice_keys={'currency','issuedAt','paidAt','paymentStatus','subtotal','tax','total','merchandise','shipping','fees','discount','originalTotal','refundedTotal','items'}
    line_keys={'externalId','productExternalId','name','sku','quantity','unitPrice','total','currency','date'}
    if not isinstance(value,dict) or set(value)-allowed:raise ProviderError('STORE_INVALID_DATA')
    inv=value['invoice']
    if not isinstance(inv,dict) or set(inv)!=invoice_keys:raise ProviderError('STORE_INVALID_DATA')
    if not isinstance(inv['items'],list) or len(inv['items'])>500 or not isinstance(value['lines'],list):raise ProviderError('STORE_LIMIT_EXCEEDED')
    if len(json.dumps(value))>55000:raise ProviderError('STORE_LIMIT_EXCEEDED')
    for line in inv['items']+value['lines']:
        if not isinstance(line,dict) or set(line)!=line_keys:raise ProviderError('STORE_INVALID_DATA')
        if isinstance(line['quantity'],bool) or not isinstance(line['quantity'],int) or not 1<=line['quantity']<=999999999:raise ProviderError('STORE_INVALID_DATA')
        for key in ('externalId','productExternalId','name'):
            if not isinstance(line[key],str) or not line[key] or len(line[key])>500:raise ProviderError('STORE_INVALID_DATA')
        timestamp(line['date'])
        if line['currency']!=inv['currency'] or abs(money(line['total'])-money(line['unitPrice'])*line['quantity'])>Decimal('.00005')*line['quantity']:raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    if len({l['externalId'] for l in inv['items']})!=len(inv['items']):raise ProviderError('STORE_INVALID_DATA')
    if not re.fullmatch('[A-Z]{3}',inv['currency']):raise ProviderError('STORE_INVALID_DATA')
    timestamp(value['modifiedAt']);timestamp(inv['issuedAt'])
    if inv['paidAt']:timestamp(inv['paidAt'])
    if inv['paymentStatus'] not in {'PAID','UNPAID','PARTIAL','CANCELLED'} or (inv['paymentStatus']=='PAID' and not inv['paidAt']):raise ProviderError('STORE_PAYMENT_EVIDENCE_MISSING')
    if sum((money(l['total']) for l in inv['items']),Decimal(0))!=money(inv['merchandise']) or money(inv['subtotal'])!=money(inv['merchandise'])+money(inv['shipping'])+money(inv['fees']) or money(inv['total'])!=money(inv['subtotal'])+money(inv['tax']) or money(inv['originalTotal'])!=money(inv['total'])+money(inv['refundedTotal']):raise ProviderError('STORE_ORDER_TOTAL_MISMATCH')
    expected=inv['items'] if (value.get('salesEligible') is True and inv['paymentStatus']=='PAID' or value.get('status')=='completed' and inv['paymentStatus']!='CANCELLED') else []
    if value['lines']!=expected:raise ProviderError('STORE_INVALID_DATA')
    return value
