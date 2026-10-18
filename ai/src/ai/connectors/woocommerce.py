"""WooCommerce REST v3 mapping; no billing, database or canonical writes."""
import base64
import re
import time
from urllib.parse import urlencode, urlsplit, urlunsplit
from .transport import ProviderError, get_json
from .values import identifier, money, timestamp
from .inventory import normalize_inventory
from .orders import normalize_order

def store_url(value):
    u = urlsplit(value)
    if (u.scheme != 'https' or not u.hostname or u.port not in (None, 443) or u.username or u.password
            or u.query or u.fragment or '%' in u.path or '\\' in value or '..' in u.path.split('/')):
        raise ProviderError('INVALID_STORE_URL')
    return urlunsplit(('https', u.hostname.lower(), u.path.rstrip('/'), '', ''))

class WooCommerce:
    def __init__(self, url, key=None, secret=None, fetch=get_json):
        self.url, self.fetch = store_url(url), fetch
        self.requests = 0
        self.deadline = time.monotonic() + 40
        self.authorization = None
        if key is not None:
            if not re.fullmatch(r'ck_[a-fA-F0-9]{40}', key) or not re.fullmatch(r'cs_[a-fA-F0-9]{40}', secret or ''):
                raise ProviderError('STORE_ACCESS_DENIED')
            self.authorization = 'Basic ' + base64.b64encode((key + ':' + secret).encode()).decode()

    def call(self, path, params=None):
        if time.monotonic() >= self.deadline:
            raise ProviderError('STORE_TIMEOUT')
        self.requests += 1
        if self.requests > 32:
            raise ProviderError('STORE_LIMIT_EXCEEDED')
        return self.fetch(self.url + '/wp-json/' + path + ('?' + urlencode(params) if params else ''), self.authorization)

    def detect(self):
        data, _ = self.call('')
        return {'supported': isinstance(data, dict) and 'wc/v3' in data.get('namespaces', []), 'provider': 'woocommerce', 'url': self.url}

    def verify(self):
        self.page('products', 1, limit=1)
        self.page('orders', 1, limit=1)
        setting, _ = self.call('wc/v3/settings/general/woocommerce_currency')
        currency = setting.get('value') if isinstance(setting, dict) else None
        if not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
            raise ProviderError('STORE_INVALID_DATA')
        return {'contractVersion': 2, 'verified': True, 'currency': currency, 'provider': 'woocommerce', 'url': self.url}

    def page(self, path, page, since=None, until=None, limit=20, exclude=None):
        params = {'page': page, 'per_page': limit, 'orderby': 'modified' if path.startswith('orders') else 'id', 'order': 'asc', 'dates_are_gmt': 'true'}
        if since:
            params['modified_after'] = timestamp(since)
        if until:
            params['modified_before'] = timestamp(until)
        if exclude:
            params['exclude'] = ','.join(identifier(value) for value in exclude)
        data, headers = self.call('wc/v3/' + path, params)
        if not isinstance(data, list) or len(data) > limit:
            raise ProviderError('STORE_INVALID_DATA')
        total = next((v for k, v in headers.items() if k.lower() == 'x-wp-totalpages'), None)
        if total is None or not str(total).isdigit():
            raise ProviderError('STORE_PAGINATION_UNVERIFIED')
        if int(total) > 50000:
            raise ProviderError('STORE_LIMIT_EXCEEDED')
        return data, page < int(total)

    def product(self, raw, currency, parent=None):
        name = raw.get('name') or (parent or {}).get('name')
        if parent:
            name = parent['name'] + ' — ' + ' / '.join(str(a.get('option', '')) for a in raw.get('attributes', []))
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ProviderError('STORE_INVALID_DATA')
        sku = raw.get('sku') or None
        if sku and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', sku):
            raise ProviderError('STORE_INVALID_SKU')
        return {'externalId': identifier(raw['id']), 'name': name, 'sku': sku,
                'price': str(money(raw.get('price') or '0')), 'currency': currency,
                'inventory': normalize_inventory(raw, parent)}

    def products(self, page, currency, since, until):
        data, more = self.page('products', page, since, until)
        result = []
        for raw in data:
            if raw.get('type') == 'variable':
                variation_page = 1
                while True:
                    variants, next_page = self.page('products/' + identifier(raw['id']) + '/variations', variation_page)
                    result.extend(self.product(v, currency, raw) for v in variants if v.get('price') not in (None, ''))
                    if not next_page:
                        break
                    variation_page += 1
                    if variation_page > 20:
                        raise ProviderError('STORE_LIMIT_EXCEEDED')
            elif raw.get('type') in ('simple', 'variation') and raw.get('price') not in (None, ''):
                result.append(self.product(raw, currency))
            if len(result) > 500:
                raise ProviderError('STORE_LIMIT_EXCEEDED')
        return {'contractVersion': 2, 'items': result, 'hasMore': more}

    def order(self, raw):
        return normalize_order(raw, self.call)

    def orders(self, page, since, until, exclude=None):
        # Consume the first remaining page; a moving lower bound and tie-ID
        # exclusions avoid offset skips as other orders leave the fixed window.
        data, more = self.page('orders', 1, since, until, exclude=exclude)
        if any(str(order.get('id')) in (exclude or []) for order in data):
            raise ProviderError('STORE_PAGINATION_UNVERIFIED')
        return {'contractVersion': 2, 'items': [self.order(o) for o in data], 'hasMore': more}
