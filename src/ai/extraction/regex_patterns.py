"""
CEOPRO AI - Rule-Based Information Extraction.
Provides pattern-shaped token extractors for MONEY, PERCENT, DISCOUNT,
DATE, PHONE, EMAIL, INVOICE_ID, and ORDER_ID. Covers structurally regular
entities using regular expressions designed for multilingual parity
accepting ASCII, Arabic-Indic, and Extended Persian digit systems.
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from src.ai.extraction.numerals import DIGIT_CLASS, normalize_number_string, to_ascii_digits

DEFAULT_CURRENCY_CODES = ["JOD", "EGP", "SAR", "AED", "QAR", "KWD", "BHD", "OMR", "MAD", "TND", "DZD", "USD", "EUR", "ZAR"]
CURRENCY_CODES = [
    c.strip() for c in os.getenv("EXTRACTION_CURRENCY_CODES", ",".join(DEFAULT_CURRENCY_CODES)).split(",") if c.strip()
]

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

ARABIC_CURRENCY_WORDS = {
    "دينار أردني": "JOD",
    "دينار": "JOD",
    "جنيه مصري": "EGP",
    "جنيه": "EGP",
    "درهم إماراتي": "AED",
    "درهم": "AED",
}

DATE_DAY_FIRST = os.getenv("EXTRACTION_DATE_DAY_FIRST", "true").strip().lower() in ("1", "true", "yes")


@dataclass
class ExtractedEntity:
    entity_type: str
    text: str
    start: int
    end: int
    normalized_value: str = None

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "normalized_value": self.normalized_value,
        }


_SEP = r".,\u066B\u066C"
_NUMERAL = rf"[{DIGIT_CLASS}]+(?:[{_SEP}][{DIGIT_CLASS}]+)*"

_CURRENCY_CODE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(c) for c in CURRENCY_CODES) + r")\b")
_MONEY_WITH_CODE_AFTER_PATTERN = re.compile(
    rf"(?P<amount>{_NUMERAL})\s*(?P<currency>" + "|".join(re.escape(c) for c in CURRENCY_CODES) + r")\b"
)
_MONEY_WITH_CODE_BEFORE_PATTERN = re.compile(
    r"\b(?P<currency>" + "|".join(re.escape(c) for c in CURRENCY_CODES) + rf")\s+(?P<amount>{_NUMERAL})\b"
)
_MONEY_WITH_SYMBOL_PATTERN = re.compile(rf"(?P<symbol>[$€£])\s?(?P<amount>{_NUMERAL})")
_ARABIC_WORDS_SORTED = sorted(ARABIC_CURRENCY_WORDS, key=len, reverse=True)
_MONEY_WITH_ARABIC_WORD_AFTER_PATTERN = re.compile(
    rf"(?P<amount>{_NUMERAL})\s*(?P<word>" + "|".join(re.escape(w) for w in _ARABIC_WORDS_SORTED) + r")"
)
_MONEY_WITH_ARABIC_WORD_BEFORE_PATTERN = re.compile(
    r"(?P<word>" + "|".join(re.escape(w) for w in _ARABIC_WORDS_SORTED) + rf")\s+(?P<amount>{_NUMERAL})"
)

_PERCENT_PATTERN = re.compile(rf"\b({_NUMERAL})\s?%")
_DISCOUNT_PATTERN = re.compile(
    rf"({_NUMERAL})\s?%\s*(?:off|discount)|discount of ({_NUMERAL})\s?%", re.IGNORECASE
)
_DISCOUNT_PATTERN_AR = re.compile(rf"({_NUMERAL})\s?%?\s*(?:خصم|تخفيض)|(?:خصم|تخفيض)\s*({_NUMERAL})\s?%?")
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_PATTERN = re.compile(
    rf"(?<!\w)(\+?[{DIGIT_CLASS}]{{1,3}}[\s.-]?)?(\(?[{DIGIT_CLASS}]{{2,4}}\)?[\s.-]?){{2,4}}[{DIGIT_CLASS}]{{2,4}}(?!\w)"
)
_INVOICE_ID_PATTERN = re.compile(
    rf"\b(?:INVOICE|INV)\s?[-#]?\s?((?=[A-Z{DIGIT_CLASS}]*[{DIGIT_CLASS}])[A-Z{DIGIT_CLASS}]{{3,}})\b", re.IGNORECASE
)
_ORDER_ID_PATTERN = re.compile(
    rf"\b(?:ORDER|ORD)\s?[-#]?\s?((?=[A-Z{DIGIT_CLASS}]*[{DIGIT_CLASS}])[A-Z{DIGIT_CLASS}]{{3,}})\b", re.IGNORECASE
)
_SLASH_DATE_PATTERN = re.compile(rf"\b([{DIGIT_CLASS}]{{1,4}})[/-]([{DIGIT_CLASS}]{{1,2}})[/-]([{DIGIT_CLASS}]{{1,4}})\b")


def normalize_slash_date(raw_text: str) -> Optional[str]:
    """Resolves day-first vs month-first ambiguity based on configuration. Returns ISO format."""
    m = _SLASH_DATE_PATTERN.search(to_ascii_digits(raw_text))
    if not m:
        return None
    g1, g2, g3 = m.group(1), m.group(2), m.group(3)
    if len(g1) == 4:
        return f"{g1}-{g2.zfill(2)}-{g3.zfill(2)}"
    if len(g3) == 4:
        if DATE_DAY_FIRST:
            return f"{g3}-{g2.zfill(2)}-{g1.zfill(2)}"
        return f"{g3}-{g1.zfill(2)}-{g2.zfill(2)}"
    return None


def extract_money(text: str) -> List[ExtractedEntity]:
    """MONEY: amount + currency, in any supported order/notation (code, symbol, Arabic word)."""
    entities: List[ExtractedEntity] = []

    for m in _MONEY_WITH_CODE_AFTER_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        currency = m.group("currency")
        norm = f"{amount} {currency}" if amount is not None else None
        entities.append(ExtractedEntity("MONEY", m.group(0), m.start(), m.end(), norm))

    for m in _MONEY_WITH_CODE_BEFORE_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        currency = m.group("currency")
        norm = f"{amount} {currency}" if amount is not None else None
        entities.append(ExtractedEntity("MONEY", m.group(0), m.start(), m.end(), norm))

    for m in _MONEY_WITH_SYMBOL_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        currency = CURRENCY_SYMBOLS.get(m.group("symbol"))
        norm = f"{amount} {currency}" if amount is not None and currency else None
        entities.append(ExtractedEntity("MONEY", m.group(0), m.start(), m.end(), norm))

    for m in _MONEY_WITH_ARABIC_WORD_AFTER_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        currency = ARABIC_CURRENCY_WORDS.get(m.group("word"))
        norm = f"{amount} {currency}" if amount is not None and currency else None
        entities.append(ExtractedEntity("MONEY", m.group(0), m.start(), m.end(), norm))

    for m in _MONEY_WITH_ARABIC_WORD_BEFORE_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        currency = ARABIC_CURRENCY_WORDS.get(m.group("word"))
        norm = f"{amount} {currency}" if amount is not None and currency else None
        entities.append(ExtractedEntity("MONEY", m.group(0), m.start(), m.end(), norm))

    return entities


def extract_currency(text: str) -> List[ExtractedEntity]:
    """CURRENCY: a bare, standalone currency code."""
    return [
        ExtractedEntity("CURRENCY", m.group(0), m.start(), m.end(), m.group(0))
        for m in _CURRENCY_CODE_PATTERN.finditer(text)
    ]


def extract_percent(text: str) -> List[ExtractedEntity]:
    """PERCENT: a bare numeral followed by '%'."""
    entities = []
    for m in _PERCENT_PATTERN.finditer(text):
        norm = normalize_number_string(m.group(1))
        entities.append(ExtractedEntity("PERCENT", m.group(0), m.start(), m.end(), norm))
    return entities


def extract_discount(text: str) -> List[ExtractedEntity]:
    """DISCOUNT: '<n>% off' / 'discount of <n>%' in English, and the Arabic خصم/تخفيض equivalents."""
    entities = []
    for pattern in (_DISCOUNT_PATTERN, _DISCOUNT_PATTERN_AR):
        for m in pattern.finditer(text):
            amount_raw = m.group(1) or m.group(2)
            norm = f"{normalize_number_string(amount_raw)}%" if amount_raw else None
            entities.append(ExtractedEntity("DISCOUNT", m.group(0), m.start(), m.end(), norm))
    return entities


def extract_email(text: str) -> List[ExtractedEntity]:
    """EMAIL: standard address shape."""
    return [
        ExtractedEntity("EMAIL", m.group(0), m.start(), m.end(), m.group(0).lower())
        for m in _EMAIL_PATTERN.finditer(text)
    ]


def extract_phone(text: str) -> List[ExtractedEntity]:
    """PHONE: digit runs shaped like a phone number, ASCII or Arabic-Indic digits."""
    entities = []
    for m in _PHONE_PATTERN.finditer(text):
        matched = m.group(0)
        digit_count = len(re.findall(rf"[{DIGIT_CLASS}]", matched))
        if digit_count < 6:
            continue
        norm = re.sub(r"[^\d+]", "", to_ascii_digits(matched))
        entities.append(ExtractedEntity("PHONE", matched, m.start(), m.end(), norm))
    return entities


def extract_invoice_id(text: str) -> List[ExtractedEntity]:
    """INVOICE_ID: 'INVOICE'/'INV' followed by an alphanumeric id containing at least one digit."""
    entities = []
    for m in _INVOICE_ID_PATTERN.finditer(text):
        norm = to_ascii_digits(m.group(1)).upper()
        entities.append(ExtractedEntity("INVOICE_ID", m.group(0), m.start(), m.end(), norm))
    return entities


def extract_order_id(text: str) -> List[ExtractedEntity]:
    """ORDER_ID: 'ORDER'/'ORD' followed by an alphanumeric id containing at least one digit."""
    entities = []
    for m in _ORDER_ID_PATTERN.finditer(text):
        norm = to_ascii_digits(m.group(1)).upper()
        entities.append(ExtractedEntity("ORDER_ID", m.group(0), m.start(), m.end(), norm))
    return entities


def extract_date(text: str) -> List[ExtractedEntity]:
    """DATE: slash/dash-separated numeric dates, day-first or month-first per EXTRACTION_DATE_DAY_FIRST."""
    entities = []
    for m in _SLASH_DATE_PATTERN.finditer(to_ascii_digits(text)):
        norm = normalize_slash_date(m.group(0))
        entities.append(ExtractedEntity("DATE", m.group(0), m.start(), m.end(), norm))
    return entities


def extract_all(text: str) -> List[ExtractedEntity]:
    """Runs every per-type extractor over `text` and returns all matches, in document order."""
    entities: List[ExtractedEntity] = []
    entities.extend(extract_money(text))
    entities.extend(extract_currency(text))
    entities.extend(extract_percent(text))
    entities.extend(extract_discount(text))
    entities.extend(extract_email(text))
    entities.extend(extract_phone(text))
    entities.extend(extract_invoice_id(text))
    entities.extend(extract_order_id(text))
    entities.extend(extract_date(text))
    return sorted(entities, key=lambda e: e.start)
