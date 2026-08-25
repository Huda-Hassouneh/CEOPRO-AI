"""
CEOPRO AI - Typed-Column Row Parsing (Track One Pipeline Strategy).
Optimizes structured document ingestion by isolating pre-mapped column cell values. 
Bypasses unconstrained regex heuristics to preserve structural data types, while 
gracefully falling back to a lower-confidence regex tier for unmapped headers.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
    fallback_entities: List[ExtractedEntity] = field(default_factory=list)
    unmapped_columns: List[str] = field(default_factory=list)


def parse_mapped_row(
    row: Dict[str, object],
    header_mapping: Dict[str, str],
    tenant_id: str,
) -> RowParseResult:
    """
    Parses a cellular database or spreadsheet row. Employs direct programmatic type casting 
    for known mappings, preventing loss of precision on numbers or ambiguous locale strings.
    """
    result = RowParseResult(tenant_id=tenant_id)

    for source_header, cell_value in row.items():
        if cell_value is None or str(cell_value).strip() == "":
            continue

        canonical_field = header_mapping.get(source_header)

        if canonical_field and canonical_field in FIELD_PARSERS:
            parsed = _parse_typed_cell(canonical_field, cell_value)
            if parsed is not None:
                result.typed_fields[canonical_field] = parsed
                result.field_confidence[canonical_field] = 1.0
                continue

        result.unmapped_columns.append(source_header)
        cell_text = str(cell_value)
        for entity in extract_all(cell_text):
            result.fallback_entities.append(entity)
            result.field_confidence[f"{source_header}:{entity.entity_type}"] = 0.5

    return result


def _parse_typed_cell(canonical_field: str, cell_value: object) -> Optional[str]:
    field_type = FIELD_PARSERS[canonical_field]
    raw = str(cell_value).strip()

    if field_type in ("money", "percent"):
        return normalize_number_string(raw)

    if field_type == "integer":
        ascii_raw = to_ascii_digits(raw)
        try:
            return str(int(float(ascii_raw)))
        except ValueError:
            return None

    if field_type == "date":
        if "/" in raw:
            return normalize_slash_date(raw)
        return to_ascii_digits(raw)

    if field_type == "text":
        return raw

    return None
