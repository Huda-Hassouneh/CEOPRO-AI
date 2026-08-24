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
#
# Fix: strip each code and drop empties. EXTRACTION_CURRENCY_CODES="JOD, EGP"
# (with a space after the comma, which is how people actually type env vars)
# previously produced the literal code " EGP" - re.escape()'d as-is into the
# alternation - which then never matched real text. Silent failure, no error
# raised anywhere.
DEFAULT_CURRENCY_CODES = ["JOD", "EGP", "SAR", "AED", "QAR", "KWD", "BHD", "OMR", "MAD", "TND", "DZD", "USD", "EUR", "ZAR"]
CURRENCY_CODES = [
    c.strip() for c in os.getenv("EXTRACTION_CURRENCY_CODES", ",".join(DEFAULT_CURRENCY_CODES)).split(",") if c.strip()
]

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

# Arabic currency *words* (as opposed to ISO codes/symbols above). Only
# words that map unambiguously to a single code in this platform's
# supported set are included. "ريال" (riyal) is deliberately excluded -
# it's shared by SAR/QAR/OMR/YER and can't be resolved from the word alone;
# doing that correctly needs the tenant's country context, not a regex, so
# it stays a documented gap rather than a guess baked into extraction.
ARABIC_CURRENCY_WORDS = {
    "دينار أردني": "JOD",
    "دينار": "JOD",
    "جنيه مصري": "EGP",
    "جنيه": "EGP",
    "درهم إماراتي": "AED",
    "درهم": "AED",
}

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
# Arabic currency-word patterns, both orderings ("50 دينار" and "دينار 50").
# Longest words first in the alternation so "دينار أردني" matches whole
# rather than stopping at "دينار".
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
