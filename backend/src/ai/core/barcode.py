"""Product barcodes (EAN-8, UPC-A, EAN-13, GTIN-14) with the GS1 check digit.

A barcode is the one reliable key for finding a product's market price in public
price databases (market_scraper/price_lookup), so a typo must be refused when it is
entered rather than silently producing "no price found" later."""
import re
from typing import Optional

VALID_LENGTHS = (8, 12, 13, 14)
_SEPARATORS = re.compile(r"[\s\-]")


def _check_digit_ok(digits: str) -> bool:
    body, check = digits[:-1], int(digits[-1])
    # GS1: from the right of the body, weights alternate 3, 1, 3, 1 ...
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalize_barcode(value: Optional[str]) -> Optional[str]:
    """Digits only, or None for an empty value. Raises ValueError for text that
    is not a valid EAN/UPC/GTIN (wrong length, non-digits, bad check digit)."""
    if value is None:
        return None
    text = _SEPARATORS.sub("", str(value))
    if not text:
        return None
    if not text.isdigit() or len(text) not in VALID_LENGTHS:
        raise ValueError("barcode must be 8, 12, 13 or 14 digits (EAN/UPC/GTIN)")
    if not _check_digit_ok(text):
        raise ValueError("barcode check digit is wrong - please re-check the number")
    return text
