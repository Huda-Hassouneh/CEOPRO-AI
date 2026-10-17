"""Product barcodes (EAN-8, UPC-A, EAN-13, GTIN-14) with the GS1 check digit.

A barcode is the one reliable key for finding a product's market price in public
price databases (market_scraper/price_lookup), so a typo must be refused when it is
entered rather than silently producing "no price found" later."""
import re
from decimal import Decimal, InvalidOperation
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


def parse_barcode_cell(value: object) -> Optional[str]:
    """A barcode as it arrives in a spreadsheet cell, or None when it cannot be
    trusted as one (the caller then leaves the barcode out; it is optional).

    Spreadsheets mangle barcodes: Excel turns 3017620422003 into 3017620422003.0
    or 3.017620422003E+12, and drops the leading zero of a UPC-A. So: undo number
    formatting, then accept the digits only if the GS1 check digit holds - if it
    does not, try restoring leading zeros to each valid length. The check digit
    is what makes that repair safe: a wrong guess almost never validates."""
    text = _SEPARATORS.sub("", str(value or "")).lstrip("'")
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text) and any(c in text for c in ".eE"):
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
        if number != number.to_integral_value():
            return None
        text = str(int(number))
    if not text.isdigit() or len(text) > max(VALID_LENGTHS):
        return None
    for length in sorted({len(text)} | {n for n in VALID_LENGTHS if n > len(text)}):
        if length not in VALID_LENGTHS:
            continue
        candidate = text.zfill(length)
        if _check_digit_ok(candidate):
            return candidate
    return None
