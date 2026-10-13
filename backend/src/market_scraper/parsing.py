"""Pure parsing helpers shared by market-source spiders."""

import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

RATING_VALUES = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "د.أ": "JOD"}


def clean_text(value: Optional[str]) -> Optional[str]:
    """Collapse HTML whitespace and preserve a missing value as None."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def parse_price(value: str) -> tuple[float, str]:
    """Return an exact two-decimal amount and ISO currency from display text."""
    text = clean_text(value)
    if not text:
        raise ValueError("price is missing")

    currency = next((code for symbol, code in CURRENCY_SYMBOLS.items() if symbol in text), None)
    if currency is None:
        raise ValueError(f"unsupported currency in price: {text!r}")

    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"price amount is missing: {text!r}")
    try:
        amount = Decimal(match.group().replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"invalid price: {text!r}") from exc
    if amount < 0:
        raise ValueError("price cannot be negative")
    return float(amount), currency


def parse_rating(classes: Iterable[str]) -> Optional[int]:
    """Translate Books-to-Scrape's word-valued star class into an integer."""
    return next((RATING_VALUES[name] for name in classes if name in RATING_VALUES), None)


def parse_stock_quantity(value: Optional[str]) -> Optional[int]:
    """Extract a stock count when the source publishes one."""
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"(\d+)\s+available", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None
