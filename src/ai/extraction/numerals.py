"""
CEOPRO AI - Numeral Normalization.
Text arriving at this platform can write the same number in genuinely
different, ambiguous ways: ASCII digits or Arabic-Indic (١٢٣) or Extended
Arabic-Indic/Persian (۱۲۳) digits, and a decimal/thousands separator that
could be '.', ',', the Arabic decimal separator '٫' (U+066B), or the Arabic
thousands separator '٬' (U+066C). "1,5" and "1.234" are each valid readings
under more than one locale - there is no regex that resolves that correctly
100% of the time, only a documented, configurable heuristic.
"""

import os
import re
from typing import Optional

_DIGIT_TRANSLATION = str.maketrans({
    "\u0660": "0", "\u0661": "1", "\u0662": "2", "\u0663": "3", "\u0664": "4",
    "\u0665": "5", "\u0666": "6", "\u0667": "7", "\u0668": "8", "\u0669": "9",
    "\u06F0": "0", "\u06F1": "1", "\u06F2": "2", "\u06F3": "3", "\u06F4": "4",
    "\u06F5": "5", "\u06F6": "6", "\u06F7": "7", "\u06F8": "8", "\u06F9": "9",
    "\u066B": ".",  # ARABIC DECIMAL SEPARATOR
    "\u066C": ",",  # ARABIC THOUSANDS SEPARATOR
})

DIGIT_CLASS = "0-9\u0660-\u0669\u06F0-\u06F9"

# Global fallback when no per-tenant decimal_style is supplied by the
# caller (see locale_config.py for the per-tenant resolution path).
DECIMAL_STYLE = os.getenv("EXTRACTION_DECIMAL_STYLE", "auto").strip().lower()


def to_ascii_digits(raw: str) -> str:
    """Arabic-Indic / Extended Arabic-Indic digits and Arabic separators -> ASCII."""
    return raw.translate(_DIGIT_TRANSLATION)


def normalize_number_string(raw: str, decimal_style: Optional[str] = None) -> Optional[str]:
    """
    Best-effort normalization of a numeral string to a canonical ASCII
    numeric string ("1234.56"). Returns a STRING, not a float: these
    values feed NUMERIC(12,4) columns, and a float round-trip risks the
    binary-rounding precision loss NUMERIC columns exist to avoid.
    Returns None if the string can't be confidently parsed.

    decimal_style overrides the global EXTRACTION_DECIMAL_STYLE env var
    for this call only - pass the caller's resolved per-tenant style
    (see locale_config.py) when known. None (the default) preserves
    existing global behavior exactly - no caller is required to change.
    """
    style = (decimal_style or DECIMAL_STYLE).strip().lower()
    s = to_ascii_digits(raw).strip()
    if not s or not re.search(r"\d", s):
        return None

    has_dot, has_comma = "." in s, "," in s

    if has_dot and has_comma:
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma:
        s = _resolve_single_separator(s, ",", style)
    elif has_dot:
        s = _resolve_single_separator(s, ".", style)

    try:
        float(s)
    except ValueError:
        return None
    return s


def _resolve_single_separator(s: str, sep: str, style: str) -> str:
    """
    Exactly one separator character is present, possibly repeated
    ("1,234,567"). style="comma"/"period" names which character IS the
    decimal separator in this locale - if sep matches it, treat as
    decimal; if sep is the OTHER character, it's a thousands-grouping
    mark under this locale and gets stripped, never read as decimal.
    style="auto" (or unset) falls back to shape-based guessing: every
    group after the first split being exactly 3 digits reads as
    thousands-grouping; a single occurrence followed by 1-2 digits reads
    as decimal.
    """
    parts = s.split(sep)

    if style in ("comma", "period"):
        decimal_char = "," if style == "comma" else "."
        if sep == decimal_char:
            return f"{''.join(parts[:-1])}.{parts[-1]}"
        return "".join(parts)  # sep is the thousands-grouping mark under this locale

    if len(parts) == 2 and len(parts[1]) in (1, 2):
        return f"{parts[0]}.{parts[1]}"
    if all(len(p) == 3 for p in parts[1:]):
        return "".join(parts)

    return f"{''.join(parts[:-1])}.{parts[-1]}"
