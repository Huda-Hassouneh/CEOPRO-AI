"""
CEOPRO AI - Structured Data → RAG Vector DB Bridge.

The real fix for the actual gap found this session: rag/pipeline.py::
ingest_pending_documents() only ever ingests files a human uploaded to
MinIO - it has never seen a scraped review, a sentiment score, or a sales
number, because rag_documents_metadata structurally requires a real
storage_bucket_path (a file). Every other structured signal in this
platform (competitor pricing/sentiment, the tenant's own sales history,
the discovered competitor landscape) was invisible to the chatbot's own
retrieval - reachable only through a separate, hand-built function
(pricing/forecasting's own render_recommendations()-style code) bolted
onto the answer afterward, never through vector search itself.

This module closes that gap the RAG-native way: real narrative text
summaries of structured data, written as real .txt files to the SAME
ceopro-rag-knowledge bucket a human upload would use, registered as real
rag_documents_metadata rows, and ingested through the EXACT SAME
rag.pipeline.ingest_pending_documents() every other document uses - no
parallel ingestion path, no new chunking/embedding logic. A question like
"how has sentiment about my top competitor trended" is now answerable by
ordinary hybrid retrieval, the same as a question about an uploaded PDF.

Chosen deliberately as ONE HALF of the hybrid design (the other half,
exact current numbers injected directly into the prompt rather than
retrieved, is structured_context.py): a narrative summary is the right
shape for retrieval - qualitative, thematic, "what's been happening" -
but an LLM asked for an EXACT number should never have to trust that
semantic search happened to retrieve the one chunk with the precise
right figure. See structured_context.py's own docstring for that half.

Each summary type is a stable "slot" (one document per tenant per type,
identified by a fixed synthetic file_name under `_generated/`) - a
regeneration OVERWRITES that slot's content and flips processed_status
back to 'Pending' (the exact re-ingestion trigger replace_document_
chunks() already documents), rather than ever accumulating a new document
row per run. Call regenerate_all_structured_summaries() on a schedule
(e.g. after a scraping/sentiment run, or nightly) - each generator only
ever reads real, already-persisted data, never invents a number.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ai.rag.pipeline import DEFAULT_BUCKET, ingest_pending_documents
from src.ai.sentiment.data_access import load_aggregate_sentiment_by_competitor
from src.ai.sentiment.pipeline import get_subject_sentiment_summary

logger = logging.getLogger("CEOPRO_AI_RAG_STRUCTURED_SUMMARIES")

SLOT_SALES_HISTORY = "sales_history"
SLOT_COMPETITOR_LANDSCAPE = "competitor_landscape"
SLOT_SENTIMENT_TRENDS = "sentiment_trends"
SLOT_MARKET_PRICING = "market_pricing"

ALL_SLOTS = (SLOT_SALES_HISTORY, SLOT_COMPETITOR_LANDSCAPE, SLOT_SENTIMENT_TRENDS, SLOT_MARKET_PRICING)


def _object_key(slot: str) -> str:
    return f"_generated/{slot}.txt"


def _upsert_summary_document(conn, minio_client, tenant_id: str, slot: str, text: str, bucket: str) -> str:
    """
    Writes `text` to this slot's stable MinIO object (overwriting any
    previous content - MinIO's put_object is already an overwrite, not an
    append) and either flips the existing document row back to 'Pending'
    (a re-generation) or creates it fresh (the first generation for this
    tenant/slot). Either way, ingest_pending_documents() picks it up on
    its next run through the exact same path a real upload would.

    A single INSERT ... ON CONFLICT DO UPDATE, not a SELECT-then-INSERT/
    UPDATE: this is called from analysis_worker.py::analyze_tenant() on
    every market.analysis.requested event, and Redis consumer groups only
    guarantee exclusivity per MESSAGE, not per tenant - two scrapes
    finishing close together for the same tenant can be popped by two
    different worker processes concurrently. A check-then-act SELECT
    followed by a separate INSERT has a real race window there: both
    workers can see no existing row and both INSERT, producing two
    rag_documents_metadata rows pointing at the same MinIO object key,
    which ingest_pending_documents() then chunks/embeds twice - silently
    duplicated retrieval context for the chatbot. The atomic upsert
    (backed by migration 20260911010000's unique index on
    (tenant_id, storage_bucket_path)) closes that window: whichever
    worker's write loses the race updates the same row instead of
    creating a second one.
    """
    import io
    payload = text.encode("utf-8")
    object_key = _object_key(slot)
    minio_client.put_object(bucket, object_key, io.BytesIO(payload), length=len(payload), content_type="text/plain")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rag_documents_metadata
                (tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type, processed_status)
            VALUES (%s, %s, %s, %s, 'text/plain', 'Pending')
            ON CONFLICT (tenant_id, storage_bucket_path) DO UPDATE
                SET file_size_bytes = EXCLUDED.file_size_bytes,
                    processed_status = 'Pending'
            RETURNING document_id;
            """,
            (tenant_id, f"{slot}.txt", object_key, len(payload)),
        )
        document_id = str(cursor.fetchone()[0])
    conn.commit()
    return document_id


def generate_sales_history_summary(conn, tenant_id: str, window_days: int = 90) -> str:
    """
    Real narrative built from invoices/invoice_items (the platform's
    actual internal sales record - see PENDING_ACTIONS.md #31 for why
    this is invoices/invoice_items, not a transactions table that doesn't
    exist in Final_schema.sql): total revenue and top products by revenue
    over the window, each line citing its own real source columns so the
    LLM's own provenance discipline (llm_client.py's SYSTEM_PROMPT) can
    cite exactly where a number came from.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(DISTINCT i.invoice_id), COALESCE(SUM(i.total_amount), 0)
            FROM invoices i
            WHERE i.tenant_id = %s AND i.issue_date >= %s;
            """,
            (tenant_id, since),
        )
        invoice_count, total_revenue = cursor.fetchone()

        cursor.execute(
            """
            SELECT COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS name,
                   SUM(ii.quantity) AS units_sold, SUM(ii.total_price) AS revenue
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %s AND i.issue_date >= %s
            GROUP BY p.product_id, p.product_name
            ORDER BY revenue DESC
            LIMIT 10;
            """,
            (tenant_id, since),
        )
        top_products = cursor.fetchall()

    lines = [
        f"Internal sales history, last {window_days} days (source: invoices/invoice_items table):",
        f"- {invoice_count} invoices, total revenue {float(total_revenue):.2f} (source: invoices.total_amount, summed).",
    ]
    if top_products:
        lines.append("Top-selling products by revenue in this period (source: invoice_items, joined to products):")
        for name, units, revenue in top_products:
            lines.append(f"- {name}: {int(units)} units sold, {float(revenue):.2f} revenue.")
    else:
        lines.append("No invoice line items recorded in this period (source: invoice_items table, empty for this window).")

    return "\n".join(lines)


def generate_competitor_landscape_summary(conn, tenant_id: str) -> str:
    """
    Real narrative from tenant_competitors/global_competitors - which
    competitors are actually confirmed, their tier (product-overlap
    breadth) and scope, and the closest ones by real distance_km when
    known (company_geo_profile.py/classify_competitor()'s own fields).
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, tc.tier, tc.competitor_scope, tc.product_match_rate,
                   tc.distance_km, gc.city
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE
            ORDER BY (tc.distance_km IS NULL), tc.distance_km ASC, gc.competitor_name ASC
            LIMIT 20;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return "Competitor landscape (source: tenant_competitors/global_competitors tables): no confirmed, tracked competitors yet."

    tier_counts: dict = {}
    lines = ["Confirmed, tracked competitors (source: tenant_competitors joined to global_competitors):"]
    for name, tier, scope, match_rate, distance_km, city in rows:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        distance_text = f", {float(distance_km):.1f}km away" if distance_km is not None else ""
        city_text = f" ({city})" if city else ""
        match_text = f"{float(match_rate):.0%} of your catalog overlaps with theirs" if match_rate is not None else "overlap not yet computed"
        lines.append(f"- {name}{city_text}: {tier} tier, {scope}, {match_text}{distance_text}.")

    summary_line = ", ".join(f"{count} {tier}" for tier, count in sorted(tier_counts.items()))
    lines.insert(1, f"Tier breakdown (source: tenant_competitors.tier): {summary_line}.")
    return "\n".join(lines)


def generate_sentiment_trends_summary(conn, tenant_id: str) -> str:
    """
    Real narrative from sentiment_results. The overall business figure
    still reuses sentiment/pipeline.py::get_subject_sentiment_summary()
    (the exact same aggregate the dedicated sentiment module itself
    produces - never a re-derived number) since that's a single call.

    Per-competitor figures use load_aggregate_sentiment_by_competitor()
    instead of calling get_subject_sentiment_summary() once per tracked
    competitor - a real N+1 fixed here (one batched query for every
    competitor's sentiment instead of one round trip each, on every RAG
    summary regeneration). This also means the per-competitor path no
    longer writes an evidence_records row per competitor per
    regeneration - see load_aggregate_sentiment_by_competitor()'s own
    docstring for why that side effect belongs to a direct, user-facing
    query, not a background narrative-summary loop.
    """
    lines = ["Sentiment trends (source: sentiment_results, aggregated via sentiment/pipeline.py):"]

    business = get_subject_sentiment_summary(conn, tenant_id, "BUSINESS")
    if business["status"] == "OK":
        counts = business["label_counts"]
        lines.append(
            f"- Overall business sentiment: score {business['sentiment_score']:.2f} "
            f"({counts.get('positive', 0)} positive, {counts.get('neutral', 0)} neutral, "
            f"{counts.get('negative', 0)} negative reviews analyzed)."
        )
    else:
        lines.append("- Overall business sentiment: no analyzed reviews yet.")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT tc.global_competitor_id, gc.competitor_name
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id,),
        )
        competitors = cursor.fetchall()

    by_competitor = load_aggregate_sentiment_by_competitor(conn, tenant_id)
    for competitor_id, name in competitors:
        result = by_competitor.get(str(competitor_id))
        if result and result["analyzed_count"] > 0:
            counts = result["label_counts"]
            lines.append(
                f"- {name}: sentiment score {result['sentiment_score']:.2f} "
                f"({counts.get('positive', 0)} positive, {counts.get('neutral', 0)} neutral, "
                f"{counts.get('negative', 0)} negative reviews analyzed)."
            )

    return "\n".join(lines)


def generate_market_pricing_summary(conn, tenant_id: str) -> str:
    """
    Real narrative comparing this tenant's own current_price against the
    most recent real scraped competitor_prices for the same product -
    the actual price-gap signal, sourced from the canonical pricing
    tables, not re-derived or guessed.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS name,
                   p.current_price, p.currency,
                   AVG(latest.scraped_price) AS avg_competitor_price, COUNT(latest.scraped_price) AS competitor_count
            FROM products p
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id
            JOIN LATERAL (
                SELECT cpr.scraped_price
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            GROUP BY p.product_id, p.product_name, p.current_price, p.currency
            ORDER BY name
            LIMIT 20;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return "Market pricing comparison (source: products.current_price vs. competitor_prices): no real competitor price observations yet."

    lines = ["Your price vs. observed competitor prices (source: products.current_price vs. latest competitor_prices.scraped_price):"]
    for name, own_price, currency, avg_competitor_price, competitor_count in rows:
        own_price = float(own_price)
        avg_competitor_price = float(avg_competitor_price)
        gap_pct = ((own_price - avg_competitor_price) / avg_competitor_price * 100) if avg_competitor_price else 0.0
        direction = "higher" if gap_pct > 0 else "lower" if gap_pct < 0 else "the same as"
        lines.append(
            f"- {name}: your price {own_price:.2f} {currency} vs. avg competitor price "
            f"{avg_competitor_price:.2f} {currency} ({int(competitor_count)} observation(s)) - "
            f"you are {abs(gap_pct):.0f}% {direction} the market."
        )
    return "\n".join(lines)


_GENERATORS = {
    SLOT_SALES_HISTORY: generate_sales_history_summary,
    SLOT_COMPETITOR_LANDSCAPE: generate_competitor_landscape_summary,
    SLOT_SENTIMENT_TRENDS: generate_sentiment_trends_summary,
    SLOT_MARKET_PRICING: generate_market_pricing_summary,
}


def regenerate_all_structured_summaries(
    conn, minio_client, tenant_id: str, bucket: str = DEFAULT_BUCKET,
) -> dict:
    """
    Regenerates every summary slot's narrative text, upserts each into the
    real document/MinIO pipeline, then runs the SAME ingest_pending_
    documents() every uploaded file goes through - one call, real
    chunking/embedding, and the tenant's retrieval index cache is
    invalidated exactly the way a real upload already invalidates it.
    One slot's generator failing never blocks the others - the same
    "one bad item must not sink the batch" discipline used throughout
    this codebase's own ingestion paths.
    """
    document_ids = {}
    for slot, generator in _GENERATORS.items():
        try:
            text = generator(conn, tenant_id)
            document_ids[slot] = _upsert_summary_document(conn, minio_client, tenant_id, slot, text, bucket)
        except Exception as e:  # noqa: BLE001 - one slot's failure must not block the others
            logger.error("failed to regenerate structured summary slot=%s tenant=%s: %s", slot, tenant_id, e)
            document_ids[slot] = None

    processed_count = ingest_pending_documents(conn, minio_client, tenant_id, bucket=bucket)
    return {"document_ids": document_ids, "chunks_ingested_for": processed_count}
