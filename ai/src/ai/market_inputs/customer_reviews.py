"""
Customer reviews the business imports from a file (CSV/XLSX).

Found in first-customer acceptance testing: the reviews table - and so the
whole sentiment pipeline, the dashboard's market-sentiment card and the
assistant's "what do customers say" answers - was only ever fed by the
competitor scraper. A business could not analyse its OWN customers'
feedback (Google Maps/Facebook/booking-site exports, a feedback form, a
WhatsApp survey pasted into a sheet), and nothing at all worked where
scraping isn't available. This imports them as MANUAL, ALLOWED reviews:
about a specific product when the product column matches one of the
tenant's products by name, otherwise about the business itself.

Header detection is deliberately vocabulary-based in English, Arabic and
French (no fixed template required), and a re-import of the same file is
de-duplicated per tenant via (source_id, external_review_id).
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from dateutil import parser as date_parser

from src.ai.extraction import job_management
from src.ai.extraction.numerals import normalize_number_string, to_ascii_digits

REVIEWS_SOURCE_TYPE = "REVIEWS_UPLOAD"
MAX_TEXT_LENGTH = 5000

_HEADER_SYNONYMS: Dict[str, List[str]] = {
    "text": ["review", "review text", "comment", "comments", "feedback", "text", "message", "opinion", "body",
             "المراجعة", "مراجعة", "التعليق", "تعليق", "الرأي", "رأي", "ملاحظات",
             "avis", "commentaire", "commentaires", "texte", "message"],
    "rating": ["rating", "stars", "star rating", "score", "rate", "التقييم", "تقييم", "النجوم", "note", "étoiles", "etoiles"],
    "date": ["date", "review date", "created", "created at", "posted", "time", "التاريخ", "تاريخ", "date de l'avis", "date avis"],
    "product": ["product", "product name", "item", "service", "menu item", "sku", "المنتج", "منتج", "الخدمة", "produit", "article"],
    "platform": ["platform", "source", "channel", "site", "website", "المنصة", "المصدر", "القناة", "plateforme", "canal"],
    "reviewer": ["reviewer", "name", "customer", "customer name", "author", "user", "الاسم", "العميل", "اسم العميل", "client", "nom", "auteur"],
}


def _normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (value or "").strip().lower())


def map_headers(headers: List[str]) -> Dict[str, str]:
    """canonical field -> the file's own header."""
    mapping: Dict[str, str] = {}
    normalized = {_normalize_header(h): h for h in headers if h}
    for field_name, synonyms in _HEADER_SYNONYMS.items():
        for synonym in synonyms:
            if synonym in normalized and normalized[synonym] not in mapping.values():
                mapping[field_name] = normalized[synonym]
                break
    return mapping


def parse_rating(raw) -> Optional[float]:
    """'4', '4.5', '4,5', '٤', '4/5', '8/10', '★★★★' -> 0..5 scale, else None."""
    if raw is None:
        return None
    text = to_ascii_digits(str(raw)).strip()
    if not text:
        return None
    if set(text) <= {"★", "☆", "*", " "}:  # star glyphs: count the filled ones
        return float(min(5, text.count("★") + text.count("*")))
    out_of = 5.0
    match = re.match(r"^\s*([\d.,]+)\s*/\s*(\d+)\s*$", text)
    if match:
        text, out_of = match.group(1), float(match.group(2))
    number = normalize_number_string(text)
    if number is None:
        return None
    value = float(number)
    if out_of != 5.0 and out_of > 0:
        value = value / out_of * 5
    elif 5 < value <= 10:
        value = value / 2  # a 10-point scale without "/10"
    if value < 0 or value > 5:
        return None
    return round(value, 2)


def parse_review_date(raw, day_first: bool) -> Optional[datetime]:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = to_ascii_digits(str(raw)).strip()
        try:
            # Year-first (ISO, "2026-09-02", "2026/09/02") is never day-first:
            # dateutil's dayfirst=True would read it as 9 February.
            if re.match(r"^\d{4}[-/.]", text):
                parsed = date_parser.parse(text, yearfirst=True, dayfirst=False)
            else:
                parsed = date_parser.parse(text, dayfirst=day_first)
        except (ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed > datetime.now(timezone.utc) or parsed.year < 2000:
        return None
    return parsed


@dataclass
class ReviewImportSummary:
    rows: int = 0
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    linked_to_products: int = 0
    unmatched_products: List[str] = field(default_factory=list)
    missing_columns: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rows": self.rows, "imported": self.imported, "duplicates": self.duplicates,
            "skipped": self.skipped, "linked_to_products": self.linked_to_products,
            "unmatched_products": self.unmatched_products[:20], "missing_columns": self.missing_columns,
        }


def import_reviews(conn, tenant_id: str, headers: List[str], rows: List[dict], day_first: bool = True) -> ReviewImportSummary:
    summary = ReviewImportSummary(rows=len(rows))
    mapping = map_headers(headers)
    if "text" not in mapping:
        summary.missing_columns = ["review text"]
        summary.skipped = len(rows)
        return summary

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT product_id, product_name FROM products WHERE tenant_id = %s AND deleted_at IS NULL;",
            (tenant_id,),
        )
        products_by_name = {}
        for product_id, names in cursor.fetchall():
            for name in (names or {}).values() if isinstance(names, dict) else [names]:
                if isinstance(name, str) and name.strip():
                    products_by_name[name.strip().casefold()] = str(product_id)

    source_id = job_management.resolve_or_create_data_source(conn, tenant_id, REVIEWS_SOURCE_TYPE, "Customer reviews import")
    unmatched = set()
    for row in rows:
        text = str(row.get(mapping["text"]) or "").strip()
        if not text:
            summary.skipped += 1
            continue
        text = text[:MAX_TEXT_LENGTH]
        rating = parse_rating(row.get(mapping["rating"])) if "rating" in mapping else None
        review_date = parse_review_date(row.get(mapping["date"]), day_first) if "date" in mapping else None
        platform = (str(row.get(mapping["platform"]) or "").strip() if "platform" in mapping else "") or "Imported file"
        reviewer = (str(row.get(mapping["reviewer"]) or "").strip() if "reviewer" in mapping else "") or None
        product_label = str(row.get(mapping["product"]) or "").strip() if "product" in mapping else ""
        product_id = products_by_name.get(product_label.casefold()) if product_label else None
        if product_label and product_id is None:
            unmatched.add(product_label)

        external_id = hashlib.sha256("|".join([
            review_date.isoformat() if review_date else "", str(rating or ""), text, reviewer or "", product_label.casefold(), platform.casefold(),
        ]).encode("utf-8")).hexdigest()[:40]
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO reviews
                    (tenant_id, product_id, source_platform, reviewer_name, review_text, review_rating, review_date,
                     subject_type, source_status, collection_method, source_id, external_review_id)
                VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()), %s, 'ALLOWED', 'MANUAL', %s, %s)
                ON CONFLICT (tenant_id, source_id, external_review_id)
                    WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
                DO NOTHING
                RETURNING review_id;
                """,
                (tenant_id, product_id, platform[:50], reviewer[:150] if reviewer else None, text, rating, review_date,
                 "PRODUCT" if product_id else "BUSINESS", source_id, external_id),
            )
            inserted = cursor.fetchone()
        if inserted is None:
            summary.duplicates += 1
            continue
        summary.imported += 1
        if product_id:
            summary.linked_to_products += 1
    summary.unmatched_products = sorted(unmatched)
    return summary


def list_reviews(conn, tenant_id: str, limit: int = 50) -> list:
    """The tenant's own (non-competitor) reviews, newest first, with the
    sentiment the model assigned once analysed."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.review_id, r.review_date, r.source_platform, r.reviewer_name, r.review_text, r.review_rating,
                   localized_text(p.product_name), s.sentiment_label
            FROM reviews r
            LEFT JOIN products p ON p.tenant_id = r.tenant_id AND p.product_id = r.product_id
            LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.subject_type IN ('BUSINESS', 'PRODUCT')
            ORDER BY r.review_date DESC
            LIMIT %s;
            """,
            (tenant_id, limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "review_id": str(review_id), "review_date": review_date.isoformat() if review_date else None,
            "platform": platform, "reviewer": reviewer, "text": text,
            "rating": float(rating) if rating is not None else None, "product_name": product_name,
            "sentiment": (label or "").lower() or None,
        }
        for review_id, review_date, platform, reviewer, text, rating, product_name, label in rows
    ]
