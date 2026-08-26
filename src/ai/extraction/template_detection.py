"""
CEOPRO AI - Template Detection.
Decides, once per uploaded file (from its header row), whether to route
through the strict typed path or the fallback regex/catalog path.
Zero-cost, zero-schema-change: pure header-string matching against a
synonym table.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set

from src.ai.extraction.row_parsing import FIELD_PARSERS


class TemplateMode(Enum):
    STRICT = "STRICT"
    FALLBACK = "FALLBACK"


HEADER_SYNONYMS: Dict[str, List[str]] = {
    "amount_raw": ["amount", "amount raw", "total", "grand total", "المبلغ", "الإجمالي"],
    "unit_price": ["unit price", "price", "unitprice", "سعر الوحدة", "السعر"],
    "quantity": ["quantity", "qty", "qty.", "الكمية", "كمية"],
    "discount_pct": ["discount", "discount %", "discount_pct", "خصم", "نسبة الخصم"],
    "transaction_date": ["date", "transaction date", "invoice date", "التاريخ", "تاريخ"],
    "email": ["email", "e-mail", "email address", "البريد الإلكتروني"],
    "phone": ["phone", "phone number", "mobile", "الهاتف", "رقم الهاتف"],
    "product_name": ["product", "product name", "item", "item name", "اسم المنتج", "المنتج"],
    "competitor_name": ["competitor", "competitor name", "المنافس"],
    "invoice_id": ["invoice", "invoice id", "invoice number", "invoice no", "رقم الفاتورة"],
    "order_id": ["order", "order id", "order number", "order no", "رقم الطلب"],
}

_unknown = set(HEADER_SYNONYMS) - set(FIELD_PARSERS)
if _unknown:
    raise ValueError(f"HEADER_SYNONYMS references fields not in FIELD_PARSERS: {_unknown}")

STRICT_MODE_REQUIRED_FIELDS: Set[str] = {"product_name", "quantity", "unit_price"}
STRICT_MODE_MIN_COVERAGE = 0.5


def _normalize_header(raw_header: str) -> str:
    return re.sub(r"\s+", " ", raw_header.strip().lower())


def build_header_mapping(headers: List[str]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for canonical_field, synonyms in HEADER_SYNONYMS.items():
        for synonym in synonyms:
            lookup[_normalize_header(synonym)] = canonical_field

    mapping: Dict[str, str] = {}
    for header in headers:
        canonical = lookup.get(_normalize_header(header))
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
    header_mapping = build_header_mapping(headers)
    matched_fields = set(header_mapping.values())
    missing_required = STRICT_MODE_REQUIRED_FIELDS - matched_fields

    recognised_count = len(header_mapping)
    total_headers = len(headers) or 1
    coverage_ratio = recognised_count / total_headers

    if not missing_required and coverage_ratio >= STRICT_MODE_MIN_COVERAGE:
        return TemplateDetectionResult(
            mode=TemplateMode.STRICT,
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
