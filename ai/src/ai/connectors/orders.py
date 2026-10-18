"""Privacy-preserving order accounting. No canonical writes or payment guesses."""
import re
from decimal import Decimal, ROUND_HALF_UP
from .values import identifier, money, timestamp
from .transport import ProviderError

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

def normalize_order(raw, call):
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
