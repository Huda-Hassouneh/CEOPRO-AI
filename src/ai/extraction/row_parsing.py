"""
CEOPRO AI - Typed-Column Row Parsing (Track One Pipeline Strategy).
Optimizes structured document ingestion by isolating pre-mapped column cell values. 
Bypasses unconstrained regex heuristics to preserve structural data types, while 
gracefully falling back to a lower-confidence regex tier for unmapped headers.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.ai.extraction.numerals import normalize_number_string, to_ascii_digits
from src.ai.extraction.regex_patterns import ExtractedEntity, normalize_slash_date, extract_all

FIELD_PARSERS = {
    "amount_raw": "money",
    "unit_price": "money",
    "quantity": "integer",
    "discount_pct": "percent",
    "transaction_date": "date",
    "email": "text",
    "phone": "text",
    "product_name": "text",
    "competitor_name": "text",
    "invoice_id": "text",
    "order_id": "text",
}


@dataclass
class RowParseResult:
    tenant_id: str
    typed_fields: Dict[str, Optional[str]] = field(default_factory=dict)
    field_confidence: Dict[str, float] = field(default_factory=dict)
    # Provenance: the untouched cell text behind each typed_fields entry,
    # keyed the same way. Kept alongside the normalized value so a value
    # can always be traced back to what the source file actually said -
    # normalization (money/date/integer parsing) is lossy by nature and
    # the normalized value alone can't answer "what did the cell say".
    raw_fields: Dict[str, str] = field(default_factory=dict)
    # Provenance: the exact source column header (as uploaded, e.g. "الكمية"
    # or "Qty") behind each typed_fields entry, keyed the same way. Without
    # this, a value can be traced to "what it said" (raw_fields) but not to
    # "which column of the original file it came from" - both are needed
    # for the full original-file -> row/column -> normalized-value chain.
    header_mapping: Dict[str, str] = field(default_factory=dict)
    fallback_entities: List[ExtractedEntity] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)


def parse_mapped_row(
    row: Dict[str, object],
    header_mapping: Dict[str, str],
    tenant_id: str,
    decimal_style: Optional[str] = None,
    day_first: Optional[bool] = None,
) -> RowParseResult:
    """
    Parses a cellular database or spreadsheet row. Employs direct programmatic type casting 
    for known mappings, preventing loss of precision on numbers or ambiguous locale strings.

    decimal_style/day_first override the global env-var defaults for this
    call only - pass the caller's resolved per-tenant locale (see
    locale_config.py) when known. Both default to None, which preserves
    existing global behavior exactly for any caller that doesn't pass them.
    """
    result = RowParseResult(tenant_id=tenant_id)
    for source_header, cell_value in row.items():
        if cell_value is None or str(cell_value).strip() == "":
            continue
        canonical_field = header_mapping.get(source_header)
        if canonical_field and canonical_field in FIELD_PARSERS:
            parsed, confidence = _parse_typed_cell(
                canonical_field, cell_value, decimal_style, day_first
            )
            if parsed is not None:
                result.typed_fields[canonical_field] = parsed
                result.field_confidence[canonical_field] = confidence
                result.raw_fields[canonical_field] = str(cell_value).strip()
                result.header_mapping[canonical_field] = source_header
                continue
        result.unmapped_columns.append(source_header)
        cell_text = str(cell_value)
        for entity in extract_all(cell_text, decimal_style, day_first):
            result.fallback_entities.append(entity)
            result.field_confidence[f"{source_header}:{entity.entity_type}"] = 0.5
    return result


def _parse_typed_cell(
    canonical_field: str,
    cell_value: object,
    decimal_style: Optional[str] = None,
    day_first: Optional[bool] = None,
) -> Tuple[Optional[str], float]:
    """
    Returns (normalized_value, confidence). Confidence is 1.0 for a clean,
    unambiguous parse and lower when the parse required a judgment call
    the source data didn't make explicit - callers should treat anything
    below 1.0 as worth surfacing for review, not as a fully-verified field.
    """
    field_type = FIELD_PARSERS[canonical_field]
    raw = str(cell_value).strip()

    if field_type in ("money", "percent"):
        return normalize_number_string(raw, decimal_style), 1.0

    if field_type == "integer":
        ascii_raw = to_ascii_digits(raw)
        # Try an exact integer parse first - the common, unambiguous case.
        try:
            return str(int(ascii_raw)), 1.0
        except ValueError:
            pass
        # Falls back to float only for non-integer-looking input (e.g. a
        # quantity cell that actually contains "1.5"). Previously this
        # went through int(float(ascii_raw)), which silently truncated
        # 1.5 -> 1 with no signal anything was lost. Rounding instead of
        # truncating is still an approximation, so it's flagged with
        # reduced confidence rather than presented as a clean parse - the
        # untouched "1.5" survives separately in raw_fields regardless.
        try:
            as_float = float(ascii_raw)
        except ValueError:
            return None, 0.0
        return str(round(as_float)), 0.7

    if field_type == "date":
        if "/" in raw:
            return normalize_slash_date(raw, day_first), 1.0
        return to_ascii_digits(raw), 1.0

    if field_type == "text":
        return raw, 1.0

    return None, 0.0
