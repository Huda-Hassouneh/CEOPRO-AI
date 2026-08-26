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

import os
DECIMAL_STYLE = os.getenv("EXTRACTION_DECIMAL_STYLE", "auto").strip().lower()


def to_ascii_digits(raw: str) -> str:
    """Arabic-Indic / Extended Arabic-Indic digits and Arabic separators -> ASCII."""
    return raw.translate(_DIGIT_TRANSLATION)


def normalize_number_string(raw: str) -> Optional[str]:
    """
    Best-effort normalization of a numeral string to a canonical ASCII
    numeric string ("1234.56"). Returns a STRING, not a float: these
    values feed NUMERIC(12,4) columns, and a float round-trip risks the
    binary-rounding precision loss NUMERIC columns exist to avoid.
    Returns None if the string can't be confidently parsed.
    """
    s = to_ascii_digits(raw).strip()
    if not s or not re.search(r"\d", s):
        return None

    has_dot, has_comma = "." in s, "," in s

    if has_dot and has_comma:
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma and DECIMAL_STYLE != "period":
        s = _resolve_single_separator(s, ",")
    elif has_dot and DECIMAL_STYLE == "comma":
        s = _resolve_single_separator(s, ".")

    try:
        float(s)
    except ValueError:
        return None
    return s


def _resolve_single_separator(s: str, sep: str) -> str:
    """
    Exactly one separator character is present, possibly repeated
    ("1,234,567"). If every group after the first split is exactly 3
    digits long, it reads as thousands-grouping; a single occurrence
    followed by 1-2 digits reads as decimal. DECIMAL_STYLE forces one
    reading instead of guessing.
    """
    parts = s.split(sep)

    if DECIMAL_STYLE in ("comma", "period"):
        return f"{''.join(parts[:-1])}.{parts[-1]}"

    if len(parts) == 2 and len(parts[1]) in (1, 2):
        return f"{parts[0]}.{parts[1]}"
    if all(len(p) == 3 for p in parts[1:]):
        return "".join(parts)

    return f"{''.join(parts[:-1])}.{parts[-1]}"
