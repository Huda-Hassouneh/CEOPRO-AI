"""Stateless Shopify GraphQL reader. Node owns OAuth, persistence and entitlements."""
import logging
import re
import time
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from .transport import ProviderError, post_json
from .values import money, timestamp

API_VERSION = '2026-10'
SCOPES = {'read_products', 'read_orders', 'read_inventory', 'read_locations'}
MONEY = '{ shopMoney { amount currencyCode } }'
PAGE = 'pageInfo { hasNextPage endCursor }'
LOCATION = 'location { id } quantities(names: ["on_hand"]) { name quantity }'
VARIANTS = '''query Catalog($after: String) {
 productVariants(first: 10, after: $after, sortKey: ID) {
  nodes { id title sku barcode price product { id title status }
   inventoryItem { id tracked inventoryLevels(first: 20) {
    nodes { ''' + LOCATION + ''' } ''' + PAGE + ''' } } }
  ''' + PAGE + ''' } }'''
LEVELS = '''query Levels($id: ID!, $after: String) {
 inventoryItem(id: $id) { inventoryLevels(first: 100, after: $after) {
 nodes { ''' + LOCATION + ''' } ''' + PAGE + ''' } } }'''
LINE = 'id name sku quantity currentQuantity variant { id } priceAfterAllDiscountsBeforeTaxesSet ' + MONEY
ORDER_FIELDS = '''id createdAt updatedAt processedAt cancelledAt closed test currencyCode
 displayFinancialStatus displayFulfillmentStatus
 currentSubtotalPriceSet ''' + MONEY + ''' currentShippingPriceSet ''' + MONEY + '''
 currentTotalPriceSet ''' + MONEY + ''' currentTotalTaxSet ''' + MONEY + '''
 currentTotalAdditionalFeesSet ''' + MONEY + ''' currentTotalDutiesSet ''' + MONEY + '''
 currentTotalDiscountsSet ''' + MONEY + ''' totalPriceSet ''' + MONEY + ''' totalRefundedSet ''' + MONEY + '''
 transactions { kind status processedAt }
 lineItems(first: 20) { nodes { ''' + LINE + ''' } ''' + PAGE + ''' }'''
ORDERS = 'query Orders($after: String, $query: String!) { orders(first: 5, after: $after, sortKey: UPDATED_AT, query: $query) { nodes { ' + ORDER_FIELDS + ' } ' + PAGE + ' } }'
LINES = 'query Lines($id: ID!, $after: String) { order(id: $id) { lineItems(first: 100, after: $after) { nodes { ' + LINE + ' } ' + PAGE + ' } } }'


def shop_domain(value):
    if value.startswith('https://'):
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ProviderError('STORE_INVALID_SHOPIFY_DOMAIN')
        host = parsed.hostname
    else:
        host = value
    if not isinstance(host, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com', host):
        raise ProviderError('STORE_INVALID_SHOPIFY_DOMAIN')
    return host


def gid(value, kind):
    if not isinstance(value, str) or not re.fullmatch(r'gid://shopify/' + kind + r'/[1-9][0-9]{0,19}', value):
        raise ProviderError('STORE_INVALID_DATA')
    return value


def connection(value):
    if not isinstance(value, dict) or not isinstance(value.get('nodes'), list) or not isinstance(value.get('pageInfo'), dict):
        raise ProviderError('STORE_PAGINATION_UNVERIFIED')
    more, cursor = value['pageInfo'].get('hasNextPage'), value['pageInfo'].get('endCursor')
    if not isinstance(more, bool) or more and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096):
        raise ProviderError('STORE_PAGINATION_UNVERIFIED')
    return value['nodes'], more, cursor


def valid_gtin(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:\d{8}|\d{12}|\d{13}|\d{14})', value) or not int(value):
        return None
    check = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(value[:-1])))
    return value if (10 - check % 10) % 10 == int(value[-1]) else None


class Shopify:
    def __init__(self, url, token, fetch=post_json, include_test_orders=False):
        self.host, self.token, self.fetch = shop_domain(url), token, fetch
        if not isinstance(token, str) or not 10 <= len(token) <= 4096:
            raise ProviderError('STORE_ACCESS_DENIED')
        self.requests = 0
        self.deadline = time.monotonic() + 45
        self.include_tests = include_test_orders

    def call(self, query, variables=None):
        self.requests += 1
        if self.requests > 32 or time.monotonic() > self.deadline:
            raise ProviderError('STORE_LIMIT_EXCEEDED')
        data = self.fetch('https://' + self.host + '/admin/api/' + API_VERSION + '/graphql.json',
                          {'query': query, 'variables': variables or {}}, {'X-Shopify-Access-Token': self.token})
        if not isinstance(data, dict):
            raise ProviderError('STORE_INVALID_DATA')
        if data.get('errors'):
            errors = data['errors']
            if not isinstance(errors, list):
                raise ProviderError('STORE_INVALID_DATA')
            codes = {e['extensions']['code'] for e in errors if isinstance(e, dict)
                     and isinstance(e.get('extensions'), dict)
                     and isinstance(e['extensions'].get('code'), str)}
            operation = re.match(r'\s*query\s+([A-Za-z_][A-Za-z0-9_]*)', query)
            for error in errors[:3]:
                if not isinstance(error, dict):
                    continue
                extensions = error.get('extensions')
                code = extensions.get('code') if isinstance(extensions, dict) else None
                # Report the rejection, never the response data, variables or headers.
                # Fixed selections and validated IDs/dates are the only query inputs.
                def safe(value):
                    text = str(value).replace(self.token, '[REDACTED]')
                    text = re.sub(r'shp[a-z]*_[A-Za-z0-9_-]+', '[REDACTED]', text)
                    return ' '.join(text.split())[:500]
                logging.getLogger('KEEL_STORE_ADAPTER').warning(
                    'Shopify GraphQL rejected operation=%s api=%s code=%s path=%s message=%s',
                    operation.group(1) if operation else 'unknown', API_VERSION,
                    safe(code or 'UNKNOWN'), safe(error.get('path', [])),
                    safe(error.get('message', 'No message returned')))
            raise ProviderError('STORE_RATE_LIMITED' if 'THROTTLED' in codes else 'STORE_SHOPIFY_QUERY_ERROR')
        if not isinstance(data.get('data'), dict):
            raise ProviderError('STORE_INVALID_DATA')
        return data['data']

    def verify(self):
        data = self.call('query Verify { shop { id currencyCode myshopifyDomain plan { partnerDevelopment } } currentAppInstallation { accessScopes { handle } } }')
        shop = data.get('shop') or {}
        scopes = {s['handle'] for s in data.get('currentAppInstallation', {}).get('accessScopes', [])}
        if not SCOPES <= scopes:
            raise ProviderError('STORE_SHOPIFY_SCOPES_REQUIRED')
        if shop.get('myshopifyDomain') != self.host or not re.fullmatch('[A-Z]{3}', shop.get('currencyCode', '')):
            raise ProviderError('STORE_INVALID_DATA')
        return {'contractVersion': 3, 'verified': True, 'provider': 'shopify', 'url': 'https://' + self.host,
                'shopId': gid(shop['id'], 'Shop'), 'currency': shop['currencyCode'], 'scopes': sorted(scopes),
                'developmentStore': shop.get('plan', {}).get('partnerDevelopment') is True,
                'historyAccess': 'all' if 'read_all_orders' in scopes else 'recent'}

    def products(self, cursor, currency):
        data = self.call(VARIANTS, {'after': cursor})
        nodes, more, end = connection(data.get('productVariants'))
        result = []
        for raw in nodes:
            name = raw['product']['title'] + ('' if raw.get('title') in (None, 'Default Title') else ' — ' + raw['title'])
            if not isinstance(name, str) or not name.strip() or len(name) > 500:
                raise ProviderError('STORE_INVALID_DATA')
            sku = raw.get('sku') or None
            if sku and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', sku):
                raise ProviderError('STORE_INVALID_SKU')
            stock = raw.get('inventoryItem')
            if not stock:
                raise ProviderError('STORE_INVALID_DATA')
            levels = stock.get('inventoryLevels')
            locations, seen_cursors = [], set()
            while True:
                entries, next_page, level_cursor = connection(levels)
                for level in entries:
                    quantities = [q['quantity'] for q in level.get('quantities', []) if q.get('name') == 'on_hand']
                    quantity = quantities[0] if stock['tracked'] and len(quantities) == 1 else None
                    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 2147483647):
                        raise ProviderError('STORE_UNSUPPORTED_STOCK')
                    locations.append({'externalId': gid(level['location']['id'], 'Location'), 'quantity': quantity})
                if len(locations) > 500:
                    raise ProviderError('STORE_LIMIT_EXCEEDED')
                if not next_page:
                    break
                if level_cursor in seen_cursors:
                    raise ProviderError('STORE_PAGINATION_UNVERIFIED')
                seen_cursors.add(level_cursor)
                levels = self.call(LEVELS, {'id': stock['id'], 'after': level_cursor})['inventoryItem']['inventoryLevels']
            if len({l['externalId'] for l in locations}) != len(locations):
                raise ProviderError('STORE_PAGINATION_UNVERIFIED')
            if raw['product'].get('status') not in {'ACTIVE', 'DRAFT', 'ARCHIVED'}:
                raise ProviderError('STORE_INVALID_DATA')
            active = raw['product']['status'] == 'ACTIVE'
            result.append({'externalId': gid(raw['id'], 'ProductVariant'), 'active': active, 'parentExternalId': gid(raw['product']['id'], 'Product'), 'name': name, 'sku': sku,
                           'price': str(money(raw['price'])), 'currency': currency, 'gtin': valid_gtin(raw.get('barcode')),
                           'inventory': {'state': 'unmanaged', 'quantity': None, 'stockStatus': None,
                                         'lowStockThreshold': None, 'stockOwnerExternalId': None}, 'locations': locations if active else []})
        return {'contractVersion': 3, 'items': result, 'hasMore': more, 'nextCursor': end if more else None}

    def orders(self, cursor, since, until, history_access='recent'):
        filters = ['updated_at:<=' + timestamp(until)]
        if since:
            filters.append('updated_at:>=' + timestamp(since))
        # Shopify itself enforces the default order-history permission window.
        data = self.call(ORDERS, {'after': cursor, 'query': ' '.join(filters)})
        nodes, more, end = connection(data.get('orders'))
        items = []
        for raw in nodes:
            if raw.get('test') and not self.include_tests:
                continue
            lines, next_page, after = connection(raw.get('lineItems'))
            seen = set()
            while next_page:
                if after in seen or len(lines) >= 500:
                    raise ProviderError('STORE_LIMIT_EXCEEDED')
                seen.add(after)
                extra, next_page, after = connection(self.call(LINES, {'id': raw['id'], 'after': after})['order']['lineItems'])
                lines.extend(extra)
            items.append(normalize_order(raw, lines))
        return {'contractVersion': 3, 'items': items, 'hasMore': more, 'nextCursor': end if more else None}


def normalize_order(raw, lines):
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
