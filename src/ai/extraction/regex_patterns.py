"""
CEOPRO AI - Rule-Based Information Extraction (spec S15).
"NER may use: Pretrained multilingual transformer. EntityRuler. Regex
patterns. Fuzzy matching. Domain-specific rules." This module implements the
regex/rule tier - the spec's own explicitly-sanctioned low-resource option,
not a fallback bolted on afterward. No trained model, no GPU.

Covers the structurally-regular entity types from spec S15's target list
(MONEY, CURRENCY, PERCENT, DISCOUNT, DATE, PHONE, EMAIL, INVOICE_ID,
ORDER_ID). Free-form entity types that need world knowledge or a trained
model to extract reliably (ORG, PERSON, GPE, ADDRESS) are out of scope here.
PRODUCT/SUPPLIER/COMPETITOR are handled separately in catalog_matching.py,
since those are look-ups against known names, not pattern matches.

Bilingual by design, not by afterthought: every numeral-bearing pattern
accepts ASCII, Arabic-Indic, and Extended Arabic-Indic digits (numerals.py),
and DISCOUNT/INVOICE_ID/ORDER_ID each have an Arabic trigger-word variant
alongside the English one, since real MENA business text code-switches
mid-sentence rather than staying in one language.
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from src.ai.extraction.numerals import DIGIT_CLASS, normalize_number_string, to_ascii_digits

# Spec S9's supported currency list, made configuration-driven (spec S9: "The
# actual supported currency list must be configuration-driven") rather than
# hardcoded into extraction logic.
DEFAULT_CURRENCY_CODES = ["JOD", "EGP", "SAR", "AED", "QAR", "KWD", "BHD", "OMR", "MAD", "TND", "DZD", "USD", "EUR", "ZAR"]
CURRENCY_CODES = os.getenv("EXTRACTION_CURRENCY_CODES", ",".join(DEFAULT_CURRENCY_CODES)).split(",")

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

# DD/MM/YYYY vs MM/DD/YYYY is genuinely ambiguous from the string alone.
# Day-first is the default because the platform's initial market is
# MENA/Jordan (companies.timezone defaults to 'Asia/Amman', init_schema.sql
# Table 1) - a locale assumption, not a fact, so it's configuration-driven
# the same way currency codes and decimal style are.
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


# A number in any supported digit system, with any run of separator
# characters ('.', ',', or the Arabic decimal/thousands separators) between
# digit groups. Deliberately permissive at the regex level - "12345",
# "1,234", "1.234,56", "١٫٥" all match - because splitting decimal from
# thousands is a semantic question numerals.normalize_number_string()
# answers, not something the matching regex should guess at.
_SEP = r".,\u066B\u066C"
_NUMERAL = rf"[{DIGIT_CLASS}]+(?:[{_SEP}][{DIGIT_CLASS}]+)*"

_CURRENCY_CODE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(c) for c in CURRENCY_CODES) + r")\b")
_MONEY_WITH_CODE_AFTER_PATTERN = re.compile(
    rf"(?P<amount>{_NUMERAL})\s*(?P<currency>" + "|".join(re.escape(c) for c in CURRENCY_CODES) + r")\b"
)
# Currency-code-before-amount ("JOD 18.00", "SAR 500") is at least as common
# as code-after ("18.00 JOD") for the MENA currencies this platform targets
# (spec S9) - both orderings need their own pattern, not just one.
_MONEY_WITH_CODE_BEFORE_PATTERN = re.compile(
    rf"\b(?P<currency>" + "|".join(re.escape(c) for c in CURRENCY_CODES) + rf")\s+(?P<amount>{_NUMERAL})\b"
)
_MONEY_WITH_SYMBOL_PATTERN = re.compile(rf"(?P<symbol>[$€£])\s?(?P<amount>{_NUMERAL})")
_PERCENT_PATTERN = re.compile(rf"\b({_NUMERAL})\s?%")
_DISCOUNT_PATTERN = re.compile(
    rf"({_NUMERAL})\s?%\s*(?:off|discount)|discount of ({_NUMERAL})\s?%", re.IGNORECASE
)
# خصم / تخفيض = "discount" in Arabic. No \b anchors here - Unicode word
# boundaries around Arabic script get unreliable next to attached prefixes
# (و/ف/ب/ال), so this matches the literal word directly instead.
_DISCOUNT_PATTERN_AR = re.compile(rf"({_NUMERAL})\s?%?\s*(?:خصم|تخفيض)|(?:خصم|تخفيض)\s*({_NUMERAL})\s?%?")

_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Loosened from a bare digit-run matcher: now also validated in
# extract_phone() by total digit count (7-15, the E.164 range) and by
# requiring either formatting punctuation/a leading '+', or enough digits
# (9+) to be unambiguous - an unformatted 7-8 digit blob is more often an
# ID, quantity, or partial amount than a phone number.
_PHONE_PATTERN = re.compile(
    rf"(?<!\w)(\+?[{DIGIT_CLASS}]{{1,3}}[\s.-]?)?(\(?[{DIGIT_CLASS}]{{2,4}}\)?[\s.-]?){{2,4}}[{DIGIT_CLASS}]{{2,4}}(?!\w)"
)

#   1. Alternation order matters here: with IGNORECASE, "INV" (tried first)
#      matches as a prefix of the plain word "invoice" itself ("INV" + "oice"
#      as the "ID"), so the longer alternative must come first.
#   2. The ID group requires a digit ((?=[A-Z...]*[digit])) - without it,
#      [A-Z0-9]{3,} case-insensitively matches any ordinary 3+ letter word
#      ("amount", "today", ...) as a fake ID. Real invoice/order IDs always
#      contain a digit; both bugs were confirmed via ast-level testing, not
#      assumed - see AI_PROGRESS.md.
_INVOICE_ID_PATTERN = re.compile(
    rf"\b(?:INVOICE|INV)\s?[-#]?\s?((?=[A-Z{DIGIT_CLASS}]*[{DIGIT_CLASS}])[A-Z{DIGIT_CLASS}]{{3,}})\b", re.IGNORECASE
)
_ORDER_ID_PATTERN = re.compile(
    rf"\b(?:ORDER|ORD)\s?[-#]?\s?((?=[A-Z{DIGIT_CLASS}]*[{DIGIT_CLASS}])[A-Z{DIGIT_CLASS}]{{3,}})\b", re.IGNORECASE
)
# فاتورة / فاتوره = "invoice", طلب = "order", رقم = "number" (optional
# connector, e.g. "فاتورة رقم 1234"). The ID itself may be Latin, digits, or
# both ("INV-1234", "١٢٣٤") since a MENA invoice number is frequently a
# Latin/numeric code embedded in an Arabic sentence.
_INVOICE_ID_PATTERN_AR = re.compile(rf"(?:فاتورة|فاتوره)\s*(?:رقم)?\s*[-#:]?\s*([A-Za-z{DIGIT_CLASS}]{{3,}})")
_ORDER_ID_PATTERN_AR = re.compile(rf"(?:طلب)\s*(?:رقم)?\s*[-#:]?\s*([A-Za-z{DIGIT_CLASS}]{{3,}})")

_DATE_ISO_PATTERN = re.compile(rf"\b([{DIGIT_CLASS}]{{4}}-[{DIGIT_CLASS}]{{2}}-[{DIGIT_CLASS}]{{2}})\b")
_DATE_SLASH_PATTERN = re.compile(rf"\b([{DIGIT_CLASS}]{{1,2}}/[{DIGIT_CLASS}]{{1,2}}/[{DIGIT_CLASS}]{{2,4}})\b")


def _matches_to_entities(pattern: re.Pattern, text: str, entity_type: str, group: int = 0) -> List[ExtractedEntity]:
    entities = []
    for m in pattern.finditer(text):
        matched_text = m.group(group) if group else m.group(0)
        if matched_text is None:
            continue
        entities.append(ExtractedEntity(entity_type=entity_type, text=matched_text, start=m.start(group), end=m.end(group)))
    return entities


def extract_money(text: str) -> List[ExtractedEntity]:
    entities = []
    for pattern in (_MONEY_WITH_CODE_AFTER_PATTERN, _MONEY_WITH_CODE_BEFORE_PATTERN):
        for m in pattern.finditer(text):
            amount = normalize_number_string(m.group("amount"))
            if amount is None:
                continue
            entities.append(
                ExtractedEntity(
                    entity_type="MONEY", text=m.group(0), start=m.start(), end=m.end(),
                    normalized_value=f"{amount} {m.group('currency')}",
                )
            )
    for m in _MONEY_WITH_SYMBOL_PATTERN.finditer(text):
        amount = normalize_number_string(m.group("amount"))
        if amount is None:
            continue
        currency = CURRENCY_SYMBOLS.get(m.group("symbol"), m.group("symbol"))
        entities.append(
            ExtractedEntity(
                entity_type="MONEY", text=m.group(0), start=m.start(), end=m.end(),
                normalized_value=f"{amount} {currency}",
            )
        )
    return entities


def extract_currency(text: str) -> List[ExtractedEntity]:
    return _matches_to_entities(_CURRENCY_CODE_PATTERN, text, "CURRENCY", group=1)


def extract_percent(text: str) -> List[ExtractedEntity]:
    entities = []
    for m in _PERCENT_PATTERN.finditer(text):
        value = normalize_number_string(m.group(1))
        if value is None:
            continue
        entities.append(
            ExtractedEntity(entity_type="PERCENT", text=m.group(0), start=m.start(), end=m.end(), normalized_value=f"{value}%")
        )
    return entities


def extract_discount(text: str) -> List[ExtractedEntity]:
    entities = []
    for pattern in (_DISCOUNT_PATTERN, _DISCOUNT_PATTERN_AR):
        for m in pattern.finditer(text):
            raw_value = next((g for g in m.groups() if g), None)
            value = normalize_number_string(raw_value) if raw_value else None
            if value is None:
                continue
            entities.append(
                ExtractedEntity(entity_type="DISCOUNT", text=m.group(0), start=m.start(), end=m.end(), normalized_value=f"{value}%")
            )
    return entities


def extract_email(text: str) -> List[ExtractedEntity]:
    # Email local/domain parts are ASCII by platform convention even in
    # otherwise Arabic text, so no digit/script normalization is needed here.
    return _matches_to_entities(_EMAIL_PATTERN, text, "EMAIL")


def extract_phone(text: str) -> List[ExtractedEntity]:
    entities = []
    for m in _PHONE_PATTERN.finditer(text):
        raw = m.group(0).strip()
        digits_only = re.sub(rf"[^{DIGIT_CLASS}]", "", raw)
        digit_count = len(digits_only)
        if digit_count < 7 or digit_count > 15:  # outside the E.164 range
            continue
        has_separator = bool(re.search(r"[\s.\-()]", raw))
        has_plus = raw.startswith("+")
        if not has_separator and not has_plus and digit_count < 9:
            # An unbroken, unformatted short digit run reads more like an
            # ID, quantity, or partial amount than a phone number.
            continue
        entities.append(
            ExtractedEntity(entity_type="PHONE", text=raw, start=m.start(), end=m.end(), normalized_value=to_ascii_digits(digits_only))
        )
    return entities


def extract_invoice_id(text: str) -> List[ExtractedEntity]:
    # normalized_value is the bare alphanumeric ID, ASCII-digit + uppercase -
    # a canonical form for looking up invoices.invoice_number regardless of
    # source language, digit system, or formatting ("INV-1234", "فاتورة رقم
    # ١٢٣٤", "invoice #1234" all normalize the same way).
    entities = []
    for pattern in (_INVOICE_ID_PATTERN, _INVOICE_ID_PATTERN_AR):
        for m in pattern.finditer(text):
            entities.append(
                ExtractedEntity(
                    entity_type="INVOICE_ID", text=m.group(0), start=m.start(), end=m.end(),
                    normalized_value=to_ascii_digits(m.group(1)).upper(),
                )
            )
    return entities


def extract_order_id(text: str) -> List[ExtractedEntity]:
    entities = []
    for pattern in (_ORDER_ID_PATTERN, _ORDER_ID_PATTERN_AR):
        for m in pattern.finditer(text):
            entities.append(
                ExtractedEntity(
                    entity_type="ORDER_ID", text=m.group(0), start=m.start(), end=m.end(),
                    normalized_value=to_ascii_digits(m.group(1)).upper(),
                )
            )
    return entities


def _normalize_slash_date(raw: str) -> str:
    """
    Best-effort ISO (YYYY-MM-DD) normalization for a DD/MM/YYYY or
    MM/DD/YYYY string (any supported digit system), per DATE_DAY_FIRST.
    Falls back to the ASCII-digit form of the raw text when the order can't
    be a valid date under the assumed locale - e.g. "13/05/2026" can't be
    MM/DD, so if DATE_DAY_FIRST is False this is correctly left
    unnormalized rather than silently guessing wrong.
    """
    ascii_raw = to_ascii_digits(raw)
    parts = ascii_raw.split("/")
    if len(parts) != 3:
        return ascii_raw

    first, second, year_part = parts
    day_part, month_part = (first, second) if DATE_DAY_FIRST else (second, first)

    try:
        day, month, year = int(day_part), int(month_part), int(year_part)
    except ValueError:
        return ascii_raw

    if year < 100:
        year += 2000 if year < 70 else 1900

    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ascii_raw

    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_date(text: str) -> List[ExtractedEntity]:
    entities = []
    for m in _DATE_ISO_PATTERN.finditer(text):
        entities.append(
            ExtractedEntity(
                entity_type="DATE", text=m.group(1), start=m.start(1), end=m.end(1),
                normalized_value=to_ascii_digits(m.group(1)),
            )
        )
    for m in _DATE_SLASH_PATTERN.finditer(text):
        raw = m.group(1)
        entities.append(
            ExtractedEntity(
                entity_type="DATE", text=raw, start=m.start(1), end=m.end(1),
                normalized_value=_normalize_slash_date(raw),
            )
        )
    return entities


EXTRACTORS = {
    "MONEY": extract_money,
    "CURRENCY": extract_currency,
    "PERCENT": extract_percent,
    "DISCOUNT": extract_discount,
    "EMAIL": extract_email,
    "PHONE": extract_phone,
    "INVOICE_ID": extract_invoice_id,
    "ORDER_ID": extract_order_id,
    "DATE": extract_date,
}


def extract_all(text: str) -> List[ExtractedEntity]:
    entities = []
    for extractor in EXTRACTORS.values():
        entities.extend(extractor(text))
    return sorted(entities, key=lambda e: e.start)
