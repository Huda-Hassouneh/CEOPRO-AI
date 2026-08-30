"""
CEOPRO AI - Header Recognition (the RECOGNIZED tier).

This module implements exactly one of the four tiers ingestion_pipeline.py
now orchestrates (see its own module docstring for the full picture):
fuzzy, multi-language header-synonym matching for files that look
plausibly CEOPRO-shaped without literally using the distributed template.
It does NOT decide TEMPLATE_COMPLIANT (that's template_contract.py's exact-
match against the actual published template) or TRUSTED_MAPPING (a
caller-supplied mapping for DB/API/POS/ERP integrations, decided entirely
by the caller before this module is ever consulted) - ingestion_pipeline.py
tries those two first and only falls through to detect_template() here if
neither applies. Kept deliberately separate from template_contract.py
(rather than one module doing all tier detection) to avoid a circular
import - this module doesn't know the canonical template exists, and
template_contract.py doesn't know this fuzzy matcher exists; both are
consulted, in order, by ingestion_pipeline.py alone.

Zero-cost, zero-schema-change: pure header-string matching against a
synonym table. No ML model, no external service, no new tables.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set

from src.ai.extraction.row_parsing import FIELD_PARSERS


class TemplateMode(Enum):
    """
    The single enum used throughout extraction/ for which of the four
    tiers a row/file was processed under - ordered here from strongest to
    weakest guarantee:

    TEMPLATE_COMPLIANT - headers exactly match the published canonical
        template (template_contract.py). The 0%-data-loss guarantee tier.
    TRUSTED_MAPPING - caller (DB/API/POS/ERP integration) supplied an
        explicit field mapping directly, bypassing header matching
        entirely because the caller already knows its own schema with
        certainty. Also guarantee-eligible, for the same reason.
    RECOGNIZED - this module's fuzzy, multi-language synonym match
        (formerly named STRICT). Best-effort, high-quality, NOT guarantee-
        eligible - the header text wasn't a literal template match, so the
        mapping is a heuristic, not a certainty.
    FALLBACK - no trustworthy column structure at all; routed through
        extract_entities() (regex + catalog matching) per cell/row,
        lowest-confidence best-effort.

    Only RECOGNIZED and FALLBACK are ever returned by detect_template()
    in this module - TEMPLATE_COMPLIANT and TRUSTED_MAPPING are assigned
    directly by ingestion_pipeline.py before detect_template() is even
    called, per the tier order above.
    """
    TEMPLATE_COMPLIANT = "TEMPLATE_COMPLIANT"
    TRUSTED_MAPPING = "TRUSTED_MAPPING"
    RECOGNIZED = "RECOGNIZED"
    FALLBACK = "FALLBACK"


# Canonical field -> every header spelling we recognise as meaning that
# field. Keys must be a subset of FIELD_PARSERS (row_parsing.py) - that's
# the single source of truth for what a "mapped" field is. Extend this
# list as real customer files reveal new spellings; it's the only place
# that needs editing to widen STRICT-mode coverage.
HEADER_SYNONYMS: Dict[str, List[str]] = {
    "amount_raw": [
        "amount", "amount raw", "total", "grand total", "total_ttc", "net amount",
        "المبلغ", "الإجمالي",
    ],
    "unit_price": [
        "unit price", "price", "unitprice", "prix_unitaire", "prix unitaire",
        "سعر الوحدة", "السعر",
    ],
    "quantity": [
        "quantity", "qty", "qty.", "qte", "الكمية", "الكميه", "كمية",
    ],
    "discount_pct": ["discount", "discount %", "discount_pct", "خصم", "نسبة الخصم"],
    "transaction_date": ["date", "transaction date", "invoice date", "التاريخ", "تاريخ"],
    "email": ["email", "e-mail", "email address", "البريد الإلكتروني"],
    "phone": ["phone", "phone number", "mobile", "الهاتف", "رقم الهاتف"],
    "product_name": ["product", "product name", "item", "item name", "اسم المنتج", "المنتج"],
    "competitor_name": ["competitor", "competitor name", "المنافس"],
    "invoice_id": [
        "invoice", "invoice id", "invoice number", "invoice no", "num_facture",
        "رقم الفاتورة",
    ],
    "order_id": ["order", "order id", "order number", "order no", "رقم الطلب"],
}

# Every entry above is an assumption, not a confirmed customer format,
# until checked off here. Entries added on request without a real sample
# file to verify against are marked ASSUMED; move an entry to CONFIRMED
# only once it's checked against an actual CEOPRO export or a real
# POS/ERP export header row.
HEADER_SYNONYM_STATUS: Dict[str, str] = {
    "total_ttc": "ASSUMED (requested - common French/Maghreb invoicing term, not verified against a real export)",
    "net amount": "ASSUMED (requested, not verified against a real export)",
    "prix_unitaire": "ASSUMED (requested - French for 'unit price', not verified against a real export)",
    "prix unitaire": "ASSUMED (requested, not verified against a real export)",
    "qte": "ASSUMED (requested - common French abbreviation for 'quantité', not verified against a real export)",
    "num_facture": "ASSUMED (requested - French for 'invoice number', not verified against a real export)",
    "الكميه": "ASSUMED (requested - alternate Arabic spelling of quantity, not verified against a real export)",
}

# Sanity check at import time: every key above must be a real FIELD_PARSERS
# field, so this table can never silently drift from row_parsing.py.
_unknown = set(HEADER_SYNONYMS) - set(FIELD_PARSERS)
if _unknown:
    raise ValueError(f"HEADER_SYNONYMS references fields not in FIELD_PARSERS: {_unknown}")

# The minimum canonical fields a file must cover to be trusted as
# RECOGNIZED rather than routed to fallback. Deliberately a small,
# high-confidence core (not every FIELD_PARSERS key) - a file missing
# "discount_pct" is still very plausibly a real sales record; a file
# missing "product_name" and "unit_price" is not.
RECOGNIZED_MODE_REQUIRED_FIELDS: Set[str] = {"product_name", "quantity", "unit_price"}

# Fraction of *non-required* recognised headers still needed to call it
# RECOGNIZED once the required core is met - guards against a file that has
# the 3 required headers by coincidence but is otherwise a completely
# different format with noise in every other column.
RECOGNIZED_MODE_MIN_COVERAGE = 0.5


def normalize_header(raw_header: str) -> str:
    """
    Underscores are folded to spaces before whitespace collapse, so
    snake_case headers ("product_name", "unit_price" - Final_schema.sql's
    own column-naming convention, and a common shape for anything
    exported from a database/API rather than typed by hand in a
    spreadsheet) match the same way their space-separated spelling would.
    Applied identically to both sides of the lookup in
    build_header_mapping() below, so HEADER_SYNONYMS entries that already
    happen to contain an underscore (e.g. "total_ttc", "prix_unitaire")
    still match correctly - they normalize to the same string their
    space-separated counterpart already does.
    """
    return re.sub(r"\s+", " ", raw_header.strip().lower().replace("_", " "))


def build_header_mapping(headers: List[str]) -> Dict[str, str]:
    """
    Maps each raw source header to its canonical FIELD_PARSERS field, via
    HEADER_SYNONYMS. Unrecognised headers are simply absent from the
    result - callers (parse_mapped_row) already treat an unmapped header
    as "goes to fallback regex extraction for that column", so no
    explicit sentinel is needed here.
    """
    lookup: Dict[str, str] = {}
    for canonical_field, synonyms in HEADER_SYNONYMS.items():
        for synonym in synonyms:
            lookup[normalize_header(synonym)] = canonical_field

    mapping: Dict[str, str] = {}
    for header in headers:
        canonical = lookup.get(normalize_header(header))
        if canonical:
            mapping[header] = canonical
    return mapping


@dataclass
class TemplateDetectionResult:
    mode: TemplateMode
    header_mapping: Dict[str, str] = field(default_factory=dict)
    matched_fields: Set[str] = field(default_factory=set)
    missing_required_fields: Set[str] = field(default_factory=set)
    coverage_ratio: float = 0.0


def detect_template(headers: List[str]) -> TemplateDetectionResult:
    """
    Decides RECOGNIZED vs FALLBACK for a file's header row (an empty
    mapping in FALLBACK mode signals "no columns are trustworthy as typed -
    extract from raw cell/row text instead"). This is only ONE tier of
    ingestion_pipeline.py's four - see this module's own docstring and
    TemplateMode's docstring for the full tier order and why
    TEMPLATE_COMPLIANT/TRUSTED_MAPPING are decided elsewhere, before this
    function is even called.
    """
    header_mapping = build_header_mapping(headers)
    matched_fields = set(header_mapping.values())
    missing_required = RECOGNIZED_MODE_REQUIRED_FIELDS - matched_fields

    recognised_count = len(header_mapping)
    total_headers = len(headers) or 1
    coverage_ratio = recognised_count / total_headers

    if not missing_required and coverage_ratio >= RECOGNIZED_MODE_MIN_COVERAGE:
        return TemplateDetectionResult(
            mode=TemplateMode.RECOGNIZED,
            header_mapping=header_mapping,
            matched_fields=matched_fields,
            missing_required_fields=missing_required,
            coverage_ratio=coverage_ratio,
        )

    return TemplateDetectionResult(
        mode=TemplateMode.FALLBACK,
        header_mapping={},
        matched_fields=matched_fields,
        missing_required_fields=missing_required,
        coverage_ratio=coverage_ratio,
    )
