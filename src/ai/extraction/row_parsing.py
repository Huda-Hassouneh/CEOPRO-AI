"""
CEOPRO AI - Typed-Column Row Parsing (Track One Pipeline Strategy).
Isolates pre-mapped column cell values for direct type casting, falling
back to regex extraction for unmapped headers.
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
    raw_fields: Dict[str, str] = field(default_factory=dict)
    fallback_entities: List[ExtractedEntity] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)


def parse_mapped_row(
    row: Dict[str, object],
    header_mapping: Dict[str, str],
    tenant_id: str,
) -> RowParseResult:
    result = RowParseResult(tenant_id=tenant_id)
    for source_header, cell_value in row.items():
        if cell_value is None or str(cell_value).strip() == "":
            continue
        canonical_field = header_mapping.get(source_header)
        if canonical_field and canonical_field in FIELD_PARSERS:
            parsed, confidence = _parse_typed_cell(canonical_field, cell_value)
            if parsed is not None:
                result.typed_fields[canonical_field] = parsed
                result.field_confidence[canonical_field] = confidence
                result.raw_fields[canonical_field] = str(cell_value).strip()
                continue
        result.unmapped_columns.append(source_header)
        cell_text = str(cell_value)
        for entity in extract_all(cell_text):
            result.fallback_entities.append(entity)
            result.field_confidence[f"{source_header}:{entity.entity_type}"] = 0.5
    return result


def _parse_typed_cell(canonical_field: str, cell_value: object) -> Tuple[Optional[str], float]:
    """Returns (normalized_value, confidence)."""
    field_type = FIELD_PARSERS[canonical_field]
    raw = str(cell_value).strip()

    if field_type in ("money", "percent"):
        return normalize_number_string(raw), 1.0

    if field_type == "integer":
        ascii_raw = to_ascii_digits(raw)
        try:
            return str(int(ascii_raw)), 1.0
        except ValueError:
            pass
        try:
            as_float = float(ascii_raw)
        except ValueError:
            return None, 0.0
        return str(round(as_float)), 0.7

    if field_type == "date":
        if "/" in raw:
            return normalize_slash_date(raw), 1.0
        return to_ascii_digits(raw), 1.0

    if field_type == "text":
        return raw, 1.0

    return None, 0.0
