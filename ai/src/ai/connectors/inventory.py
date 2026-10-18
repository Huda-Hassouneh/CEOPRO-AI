"""Stock observations, never inferred from availability or deducted from orders."""
from .values import identifier
from .transport import ProviderError

def whole(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2147483647:
        raise ProviderError('STORE_UNSUPPORTED_STOCK')
    return value

def normalize_inventory(raw, parent=None):
    managed = raw.get('manage_stock')
    if managed is not None and not isinstance(managed, bool) and managed != 'parent':
        raise ProviderError('STORE_UNSUPPORTED_STOCK')
    shared = bool(parent and parent.get('manage_stock') is True and managed is not True)
    status = raw.get('stock_status')
    if status not in (None, 'instock', 'outofstock', 'onbackorder'):
        raise ProviderError('STORE_UNSUPPORTED_STOCK')
    quantity = raw.get('stock_quantity')
    threshold = raw.get('low_stock_amount')
    # Null means the provider did not supply an individual threshold. Do not
    # invent a safety stock or fetch a global threshold for every catalog row.
    return {'state': 'shared' if shared or managed == 'parent' else 'managed' if managed is True else 'unmanaged',
            'quantity': whole(quantity) if managed is True and quantity is not None else None,
            'stockStatus': status,
            'lowStockThreshold': whole(threshold) if threshold not in (None, '') else None,
            'stockOwnerExternalId': identifier(parent['id']) if shared else None}
