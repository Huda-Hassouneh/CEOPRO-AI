"""
CEOPRO AI - The Canonical Import Template Contract.

Single source of truth for "what does CEOPRO's official template look
like" - used identically by CSV, XLSX, and PDF-table detection, so all
three formats are judged against the same fields/order/requiredness
instead of three independently-drifting definitions.

This is a genuinely different question from template_detection.py's
existing HEADER_SYNONYMS fuzzy matcher, which answers "does this file
look plausibly CEOPRO-shaped" across many languages/spellings/aliases -
useful and kept (renamed RECOGNIZED) as the best-effort tier for files
that DON'T use this template. TEMPLATE_COMPLIANT (this module) answers
a narrower, stricter question: "did the user use our actual distributed
template" - matched by canonical field name only (case/whitespace/
underscore-normalized, via the same normalize_header() as the fuzzy
matcher, so trivial formatting differences don't cost compliance), never
by synonym translation. A file recognized via a synonym ("Item" for
"product_name") is a RECOGNIZED-tier file, not TEMPLATE_COMPLIANT - it
was never given the chance to literally match the template's own header
text, so the stronger guarantee doesn't apply to it.

Money/amount fields are deliberately plain numeric in this template, with
currency broken out into its own column, rather than accepting a combined
"24.50 JOD" cell - normalize_number_string() (numerals.py) has no currency-
symbol handling at all, so a combined cell is a real, avoidable source of
parse failure. Separating them removes an entire class of failure for a
template CEOPRO controls the shape of.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from src.ai.extraction.template_detection import normalize_header
from src.ai.extraction.row_parsing import FIELD_PARSERS

CURRENT_TEMPLATE_VERSION = "1.0"
TEMPLATE_ID = "ceopro_sales_transaction_import"


@dataclass(frozen=True)
class TemplateFieldSpec:
    canonical_name: str  # must be a FIELD_PARSERS key
    required: bool
    description: str
    example_value: str


# Order here is the template's own column order (used to generate the
# actual CSV/XLSX template files) - not required for a match (row dicts
# are keyed by header text, not position), only for how the distributed
# template file itself is laid out.
TEMPLATE_FIELDS: List[TemplateFieldSpec] = [
    TemplateFieldSpec("product_name", True, "The product or line item name.", "Premium Olive Oil 1L"),
    TemplateFieldSpec("quantity", True, "Units sold, a whole number.", "3"),
    TemplateFieldSpec("unit_price", True, "Price per unit, numeric only - no currency symbol/code in this cell.", "24.50"),
    TemplateFieldSpec("currency", True, "3-letter ISO currency code (e.g. JOD, USD, SAR).", "JOD"),
    TemplateFieldSpec("transaction_date", True, "Date of the transaction, YYYY-MM-DD preferred.", "2026-08-30"),
    TemplateFieldSpec("discount_pct", False, "Discount percentage applied, if any.", "10"),
    TemplateFieldSpec("invoice_id", False, "Invoice number/reference, if available.", "INV-20458"),
    TemplateFieldSpec("order_id", False, "Order number/reference, if available.", "ORD-99231"),
    TemplateFieldSpec("email", False, "Customer email, if collected.", "customer@example.com"),
    TemplateFieldSpec("phone", False, "Customer phone, if collected.", "+962791234567"),
    TemplateFieldSpec("competitor_name", False, "A competitor mentioned in this record, if relevant.", "Rival Store"),
    TemplateFieldSpec(
        "amount_raw", False,
        "Total line amount, if independently available (not required to equal "
        "quantity * unit_price - both are kept for cross-checking).",
        "66.15",
    ),
]

# Sanity check at import time, same convention as template_detection.py's
# own HEADER_SYNONYMS check - this contract can never silently reference a
# field row_parsing.py doesn't actually know how to parse.
_unknown_fields = {f.canonical_name for f in TEMPLATE_FIELDS} - set(FIELD_PARSERS)
if _unknown_fields:
    raise ValueError(f"TEMPLATE_FIELDS references fields not in FIELD_PARSERS: {_unknown_fields}")

TEMPLATE_HEADER_ROW: List[str] = [f.canonical_name for f in TEMPLATE_FIELDS]
REQUIRED_TEMPLATE_FIELDS: Set[str] = {f.canonical_name for f in TEMPLATE_FIELDS if f.required}
OPTIONAL_TEMPLATE_FIELDS: Set[str] = {f.canonical_name for f in TEMPLATE_FIELDS if not f.required}
EXAMPLE_ROW: Dict[str, str] = {f.canonical_name: f.example_value for f in TEMPLATE_FIELDS}

_CANONICAL_NAME_LOOKUP: Dict[str, str] = {
    normalize_header(f.canonical_name): f.canonical_name for f in TEMPLATE_FIELDS
}


def match_canonical_template(headers: List[str]) -> Optional[Dict[str, str]]:
    """
    Returns a {source_header: canonical_field} mapping if `headers`
    literally is the CEOPRO template (every required field present under
    its own canonical name, case/whitespace/underscore-normalized only -
    no synonym translation), or None if it isn't.

    Extra headers not in TEMPLATE_FIELDS at all are tolerated (carried as
    unmapped/side information, still preserved raw - see
    ingestion_pipeline.py) rather than disqualifying compliance; column
    order doesn't matter, since matching is by header text, not position.
    """
    mapping: Dict[str, str] = {}
    for header in headers:
        canonical = _CANONICAL_NAME_LOOKUP.get(normalize_header(header))
        if canonical:
            mapping[header] = canonical

    matched_fields = set(mapping.values())
    if REQUIRED_TEMPLATE_FIELDS - matched_fields:
        return None
    return mapping
