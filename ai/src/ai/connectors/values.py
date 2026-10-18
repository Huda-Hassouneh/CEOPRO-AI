"""Strict provider values shared by catalog, stock and order mapping."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .transport import ProviderError

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

