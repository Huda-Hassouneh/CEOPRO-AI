"""
KEEL - Structured Data → RAG Vector DB Bridge.

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
from src.market_scraper.pos_erp_presets import ALL_PRESETS, CONNECTION_MECHANISMS
from src.ai.core.quantities import format_quantity

logger = logging.getLogger("CEOPRO_AI_RAG_STRUCTURED_SUMMARIES")

SLOT_SALES_HISTORY = "sales_history"
SLOT_COMPETITOR_LANDSCAPE = "competitor_landscape"
SLOT_SENTIMENT_TRENDS = "sentiment_trends"
SLOT_MARKET_PRICING = "market_pricing"
SLOT_DEMAND_FORECAST = "demand_forecast"
SLOT_STRATEGIC_INSIGHTS = "strategic_insights"
SLOT_PLATFORM_HELP = "platform_help"
SLOT_POS_ERP_SYSTEMS = "pos_erp_systems"
SLOT_TROUBLESHOOTING_HELP = "troubleshooting_help"

ALL_SLOTS = (
    SLOT_SALES_HISTORY, SLOT_COMPETITOR_LANDSCAPE, SLOT_SENTIMENT_TRENDS, SLOT_MARKET_PRICING,
    SLOT_DEMAND_FORECAST, SLOT_STRATEGIC_INSIGHTS, SLOT_PLATFORM_HELP, SLOT_POS_ERP_SYSTEMS,
    SLOT_TROUBLESHOOTING_HELP,
)


def _object_key(slot: str, tenant_id: str) -> str:
    from uuid import UUID
    tenant = str(UUID(str(tenant_id)))
    if slot not in ALL_SLOTS:
        raise ValueError("Unknown summary slot")
    return f"_generated/{tenant}/{slot}.txt"


def _upsert_summary_document(conn, minio_client, tenant_id: str, slot: str, text: str, bucket: str) -> str:
    """
    Writes `text` to this slot's stable MinIO object (overwriting any
    previous content - MinIO's put_object is already an overwrite, not an
    append) and either flips the existing document row back to 'Pending'
    (a re-generation) or creates it fresh (the first generation for this
    tenant/slot). Either way, ingest_pending_documents() picks it up on
    its next run through the exact same path a real upload would.

    Skips the MinIO write and the re-ingestion trigger entirely when
    `text` is byte-identical to what's already stored for this slot
    (content_hash, migration 20260911020000) - regenerate_all_structured_
    summaries() runs on every market.analysis.requested event, and it's
    common for only one or two of the four slots to have actually
    changed since the last run (e.g. only sentiment changed this time).
    Re-uploading and re-embedding unchanged text on every single scrape
    event was a real, avoidable cost this closes. A document with no
    stored hash yet (pre-migration row, or truly the first generation)
    always regenerates - unchanged is never assumed without real
    evidence, only detected from an actual matching hash.

    The real INSERT/UPDATE path is a single atomic INSERT ... ON CONFLICT
    DO UPDATE, not a SELECT-then-INSERT/UPDATE: this is called from
    analysis_worker.py::analyze_tenant() on every market.analysis.
    requested event, and Redis consumer groups only guarantee exclusivity
    per MESSAGE, not per tenant - two scrapes finishing close together
    for the same tenant can be popped by two different worker processes
    concurrently. A check-then-act SELECT followed by a separate INSERT
    has a real race window there: both workers can see no existing row
    and both INSERT, producing two rag_documents_metadata rows pointing
    at the same MinIO object key, which ingest_pending_documents() then
    chunks/embeds twice - silently duplicated retrieval context for the
    chatbot. The atomic upsert (backed by migration 20260911010000's
    unique index on (tenant_id, storage_bucket_path)) closes that window:
    whichever worker's write loses the race updates the same row instead
    of creating a second one. The unchanged-content short-circuit above
    only ever SKIPS that write path on a real hash match - two
    concurrent writers with genuinely DIFFERENT new content still both
    fall through to it exactly as before, so it doesn't reopen that race.
    """
    import hashlib
    import io

    payload = text.encode("utf-8")
    content_hash = hashlib.sha256(payload).hexdigest()
    object_key = _object_key(slot, tenant_id)
    # Serialize same-tenant regeneration and relocation of an old shared key.
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));", (f"summary:{tenant_id}:{slot}",))

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT document_id, content_hash, processed_status FROM rag_documents_metadata "
            "WHERE tenant_id = %s AND storage_bucket_path = %s;",
            (tenant_id, object_key),
        )
        existing = cursor.fetchone()
    # Only skip when the identical text was actually ingested: a 'Failed' row with a
    # matching hash would otherwise never be retried while its content stays unchanged.
    if existing and existing[1] == content_hash and existing[2] == "Processed":
        conn.commit()
        return str(existing[0])

    minio_client.put_object(bucket, object_key, io.BytesIO(payload), length=len(payload), content_type="text/plain")

    # Reuse this tenant's legacy metadata only after its new object was written.
    # Never delete the shared legacy object: other tenants may still reference it.
    if not existing:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rag_documents_metadata SET storage_bucket_path=%s, file_size_bytes=%s, "
                "processed_status='Pending', content_hash=%s WHERE tenant_id=%s AND storage_bucket_path=%s "
                "RETURNING document_id;",
                (object_key, len(payload), content_hash, tenant_id, f"_generated/{slot}.txt"),
            )
            relocated = cursor.fetchone()
        if relocated:
            conn.commit()
            return str(relocated[0])


    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO rag_documents_metadata
                (tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type, processed_status, content_hash)
            VALUES (%s, %s, %s, %s, 'text/plain', 'Pending', %s)
            ON CONFLICT (tenant_id, storage_bucket_path) DO UPDATE
                SET file_size_bytes = EXCLUDED.file_size_bytes,
                    processed_status = 'Pending',
                    content_hash = EXCLUDED.content_hash
            RETURNING document_id;
            """,
            (tenant_id, f"{slot}.txt", object_key, len(payload), content_hash),
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
            lines.append(f"- {name}: {format_quantity(units)} units sold, {float(revenue):.2f} revenue.")
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
                   tc.distance_km, gc.city, tc.confidence_label, gc.category_path
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE
            ORDER BY tc.confidence_score DESC NULLS LAST, (tc.distance_km IS NULL), tc.distance_km ASC, gc.competitor_name ASC
            LIMIT 20;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return "Competitor landscape (source: tenant_competitors/global_competitors tables): no confirmed, tracked competitors yet."

    tier_counts: dict = {}
    lines = ["Confirmed, tracked competitors (source: tenant_competitors joined to global_competitors):"]
    for name, tier, scope, match_rate, distance_km, city, confidence_label, category_path in rows:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        distance_text = f", {float(distance_km):.1f}km away" if distance_km is not None else ""
        city_text = f" ({city})" if city else ""
        match_text = f"{float(match_rate):.0%} of your catalog overlaps with theirs" if match_rate is not None else "overlap not yet computed"
        confidence_text = f", {confidence_label} confidence" if confidence_label else ""
        category_text = f", category {' > '.join(p.replace('_', ' ') for p in category_path)}" if category_path else ""
        lines.append(f"- {name}{city_text}: {tier} tier, {scope}, {match_text}{distance_text}{confidence_text}{category_text}.")

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


def _plain_confidence_label(confidence_score: Optional[float]) -> str:
    """
    Translates a raw 0-1 confidence_score into a plain qualitative phrase -
    never surfaces the number itself. Mirrors llm_client.py's SYSTEM_PROMPT
    instruction to talk about forecast confidence in plain, everyday terms
    rather than a statistic, applied here at the source so a jargon-free
    phrase is the only thing that ever reaches the vector DB/chatbot in
    the first place, rather than relying solely on the LLM to translate it
    correctly on every single call.
    """
    if confidence_score is None:
        return "an early, rough estimate since we don't have much sales history yet"
    if confidence_score >= 0.7:
        return "a solid estimate based on your own sales history"
    if confidence_score >= 0.4:
        return "a reasonable estimate, and it will get more accurate as more sales come in"
    return "an early, rough estimate since we don't have much sales history yet"


def generate_demand_forecast_summary(conn, tenant_id: str) -> str:
    """
    Real narrative from demand_forecasts (forecasting/pipeline.py's own
    output) - the fix for "forecasts never reach the chatbot" (run_forecast()
    computes and persists expected_demand/confidence bounds, but nothing
    downstream of the forecasting consumer ever surfaced it). Deliberately
    does NOT reuse run_forecast()'s own `explanation` field verbatim - that
    field is intentionally technical (cites the model name, MASE/RMSE, and
    which baselines it beat, for a human data-science audit trail - see
    forecasting/pipeline.py's own docstring) and would violate the Extreme
    Simplicity product principle the moment it reached a merchant. Only the
    plain-language shape of the forecast (expected units, a plain-English
    range, a plain confidence phrase via _plain_confidence_label()) is
    written here.

    One row per product (its most recent forecast, DISTINCT ON product_id
    ordered by created_at DESC) - a product can accumulate many forecast
    rows over time as horizon_days requests repeat, and only the latest is
    ever the current answer.

    Real bug fix: evidence_records.forecast_id is NEVER actually set for a
    forecasting evidence row - forecasting/pipeline.py::run_forecast()
    writes the real forecast_id inside source_record_ids (a JSONB blob:
    {"forecast_id": ..., "product_id": ...}), not the forecast_id column,
    which stays NULL. The previous join here (`er.forecast_id =
    df.forecast_id`) could therefore never match anything -
    confidence_score has silently been NULL for every forecast summary
    ever generated, meaning _plain_confidence_label() always fell back to
    "an early, rough estimate" regardless of the model's real confidence.
    Fixed by joining on the real location instead.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS name,
                df.expected_demand, df.confidence_range_lower, df.confidence_range_upper,
                df.forecast_target_date, er.confidence_score
            FROM demand_forecasts df
            JOIN products p ON p.tenant_id = df.tenant_id AND p.product_id = df.product_id
            LEFT JOIN evidence_records er ON er.tenant_id = df.tenant_id
                AND er.source_module = 'ai.forecasting'
                AND (er.source_record_ids->>'forecast_id')::uuid = df.forecast_id
            WHERE df.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY df.product_id, df.created_at DESC
            LIMIT 20;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return "Demand forecast (source: demand_forecasts): no forecast has been generated yet for any product."

    lines = ["Demand forecast for your products (source: demand_forecasts, generated automatically from your sales history):"]
    for name, expected_demand, lower, upper, target_date, confidence_score in rows:
        range_text = f" (likely between {int(lower)} and {int(upper)} units)" if lower is not None and upper is not None else ""
        confidence_value = float(confidence_score) if confidence_score is not None else None
        lines.append(
            f"- {name}: about {format_quantity(round(float(expected_demand)))} units expected in total between now and {target_date.isoformat()}{range_text}. "
            f"This is {_plain_confidence_label(confidence_value)}."
        )
    return "\n".join(lines)


def generate_strategic_insights_summary(conn, tenant_id: str) -> str:
    """
    The cross-signal insight layer: rather than the chatbot only being
    able to answer about pricing, sentiment, sales, or forecasts one at a
    time when directly asked, this generator (src.ai.insights.pipeline)
    correlates them together - e.g. "your price is above the market AND
    sales are falling AND demand is forecast to keep falling" is one
    actionable insight, not three separate facts the user has to notice
    and connect themselves. Written into its own RAG slot (retrievable by
    any "how is my business doing"/"any advice" style question) and ALSO
    injected into structured_context.py's always-on facts block (see that
    module) so the top insights surface proactively on every question,
    not only when explicitly asked for - the real requirement this closes.
    """
    from src.ai.insights.pipeline import generate_insights_for_tenant

    insights = generate_insights_for_tenant(conn, tenant_id)
    if not insights:
        return (
            "Strategic insights (source: cross-signal analysis of your pricing, sentiment, sales, and "
            "forecasts): nothing stands out yet - either there isn't enough data across these signals "
            "yet, or everything currently looks healthy."
        )

    lines = ["Strategic insights - patterns found by cross-checking your pricing, customer sentiment, sales, and demand forecasts together:"]
    for insight in insights:
        lines.append(f"- {insight.message}")
    return "\n".join(lines)


def generate_platform_help_summary(conn=None, tenant_id: str = None) -> str:
    """
    Closes a real, direct product gap: the chatbot could only ever answer
    questions about a tenant's own business data (sales, competitors,
    pricing, forecasts) - a question about the PLATFORM itself ("how do I
    add a product", "how do I connect my database") had nothing to
    retrieve, ever, because no platform-help content existed anywhere in
    this codebase. Every capability named below is a real, currently
    implemented endpoint (src/ai/main.py) - nothing here is aspirational,
    written for the same audience SYSTEM_PROMPT targets (an ordinary shop
    owner), not as API documentation. Screen-by-screen directions ("which
    button do I press") come from rag/product_guide.py instead, whose
    labels are checked against the interface's own translations.

    conn/tenant_id accepted (unused) only so this fits _GENERATORS' shared
    (conn, tenant_id) -> str call signature alongside every other slot
    generator, and can be regenerated by the exact same scheduled call
    (regenerate_all_structured_summaries(), already run automatically
    after every scrape/forecast event) without a special case.

    Also carries the platform's own identity/mission (source:
    MASTER_SPEC_v4.md Section 3, "SYSTEM DEFINITION" - the real,
    authoritative project spec, not marketing copy invented for this
    prompt) - closes the other half of the same product gap: a user
    asking "who are you" or "what is this platform" used to have nothing
    grounded to answer from either, same as "how do I use this".
    """
    return (
        "Who KEEL is - answer a question about the platform's own identity or purpose "
        "using this: KEEL is an AI-powered business intelligence platform built for small "
        "and medium-sized businesses in many countries. It combines a business's own data "
        "(products, sales, stock, documents, customer reviews) with competitor and market "
        "information, and turns them into clear insights, demand forecasts and "
        "recommendations - on the Command Center dashboard, on each product's page, and "
        "through this chat - so an owner decides with real information instead of guesswork.\n\n"
        "What KEEL can do (for step-by-step directions, use only the 'How to do this in "
        "KEEL' section when it is provided):\n"
        "- Upload a file: a sales, product or inventory export (.csv, .xlsx, .xlsm) or a PDF. "
        "Rows are validated, nothing is silently dropped, and sales become part of every "
        "screen. PDFs and documents also teach this assistant.\n"
        "- Connect your own system: read-only database connections for systems that support it.\n"
        "- Products: every product has its own page with its sales, demand forecast, stock "
        "advice, competitor prices and reviews; sales can also be recorded by hand.\n"
        "- Demand forecasting: a 30-day forecast for every product with sales history, updated "
        "automatically after new sales, with restock advice.\n"
        "- Competitor discovery and tracking: competitors that compete with the whole business "
        "or on specific products, their recorded prices, and price changes.\n"
        "- Price recommendations: compares a product's price with recent competitor prices, "
        "within price-change and margin limits.\n"
        "- Marketing: guided campaign creation with ready-to-post copy.\n"
        "- Reports: sales and financial summaries you can export.\n"
        "- The dashboard (Command Center): today's sales, trends, and the next actions to take."
    )


_CATEGORY_LABELS = {
    "pharmacy_pos": "Pharmacy POS/ERP",
    "general_pos": "General POS/ERP",
    "enterprise_erp": "Enterprise/Regional ERP",
}

_MECHANISM_EXPLAINER = {
    "generic_api": (
        "REST API - the system has its own web API. The business gives us a URL plus an "
        "access key/token, and we pull their data through it on a schedule, via "
        "POST /onboarding/connect/api."
    ),
    "generic_database": (
        "DB Connector - the system doesn't have a usable API for us, so instead we get "
        "read-only access to the business's own database and pull data with a SQL query "
        "(we never write to it), via POST /onboarding/connect/database."
    ),
    "vendor_direct_request": (
        "Direct request to vendor - neither a REST API nor database access is confirmed to "
        "exist yet for this system. Before it can be connected at all, someone has to "
        "contact the vendor and ask for API access, a webhook, or a scheduled data export - "
        "this is a to-do, not a connector that works today."
    ),
}


def generate_pos_erp_summary(conn=None, tenant_id: str = None) -> str:
    """
    Real, named POS/ERP/e-commerce systems and exactly how each one would
    connect - generated directly from market_scraper/pos_erp_presets.py
    (the single source of truth also used by onboarding_connector_hint())
    rather than hand-written prose, so this can never drift out of sync
    with that module. Closes the gap the platform-help slot above
    deliberately left generic ("connect your own POS/ERP system's API") -
    a question naming a SPECIFIC vendor ("can you connect Foodics",
    "does Odoo work", "how do I connect SAP Business One") had nothing
    more specific than that generic sentence to retrieve, until now.

    conn/tenant_id accepted (unused) for the same _GENERATORS shared-
    signature reason SLOT_PLATFORM_HELP's generator already documents -
    this content is identical for every tenant, not a per-tenant query.

    Deliberately still honest about what ISN'T known even for a
    generic_api/generic_database vendor: no field mappings are pre-built
    for any of them (see onboarding_connector_hint()'s own docstring) -
    the real field names still have to come from that vendor's own docs
    once a tenant has an actual account, never guessed here.
    """
    lines = [
        "Named POS/ERP/e-commerce systems this platform knows about, and exactly how each "
        "one would connect (source: market_scraper/pos_erp_presets.py - real vendor names, "
        "researched via web search, not guessed).\n",
        "There are three ways a system can connect, and only two of them work today:\n",
    ]
    for mechanism in CONNECTION_MECHANISMS:
        lines.append(f"- {_MECHANISM_EXPLAINER[mechanism]}")
    lines.append(
        "\nImportant limit that applies to every vendor below, even ones with a real REST "
        "API or DB Connector: no field mappings are pre-built for any of them. Knowing a "
        "system has a REST API is not the same as knowing its exact field names - those "
        "still have to come from that vendor's own API docs once there's an actual account "
        "with them, never guessed at that level.\n"
    )

    by_category: dict = {}
    for preset in ALL_PRESETS.values():
        by_category.setdefault(preset["category"], []).append(preset)

    for category, label in _CATEGORY_LABELS.items():
        presets = by_category.get(category)
        if not presets:
            continue
        lines.append(f"\n{label}:")
        for preset in sorted(presets, key=lambda p: p["display_name"]):
            countries = ", ".join(preset["confirmed_countries"]) if preset["confirmed_countries"] else "region not independently confirmed"
            mechanism_word = {
                "generic_api": "REST API",
                "generic_database": "DB Connector",
                "vendor_direct_request": "direct request to vendor needed - not connectable yet",
            }[preset["connection_mechanism"]]
            confidence_note = "" if preset["verified_live"] else " (general industry knowledge, not independently re-confirmed via live search)"
            lines.append(
                f"- {preset['display_name']} ({preset['vendor_of']}), confirmed operating in: "
                f"{countries}. Connection: {mechanism_word}.{confidence_note} {preset['mechanism_note']}"
            )

    return "\n".join(lines)


def generate_troubleshooting_help_summary(conn=None, tenant_id: str = None) -> str:
    """
    Closes the last piece of the "app help" gap: platform_help answers
    "how do I use this" and pos_erp_systems answers "can you connect
    system X", but neither one told the chatbot what to say when
    something actually goes wrong - a failed upload, a connector that
    won't connect, a chat answer that returns an error. Every condition
    named below is a REAL, currently-implemented behavior (extraction.py/
    onboarding.py/rag/routers/rag.py - quoted from their own real
    validation logic and status codes, not invented), written in the same
    plain, jargon-free, shop-owner-facing voice generate_platform_help_
    summary() already uses, not as API/error-code documentation.

    conn/tenant_id accepted (unused) for the same _GENERATORS shared-
    signature reason every other slot generator already documents - this
    content is identical for every tenant, not a per-tenant query.
    """
    return (
        "If something isn't working (source: this platform's own real upload, connection, and "
        "chat error handling - src/ai/routers/extraction.py, onboarding.py, rag.py) - answer a "
        "question about a problem or error message using this, the same way you'd answer a "
        "question about the tenant's own business data. Always reassure first, then explain "
        "plainly what likely happened and what to do next - never repeat a raw error code or "
        "technical message back at the user.\n\n"
        "Uploading a file didn't work:\n"
        "- Only .csv, .xlsx, .xlsm, and .pdf files are read - any other file type is rejected "
        "before anything is processed, with nothing lost or half-saved.\n"
        "- There's a maximum file size; a file larger than that is rejected outright rather than "
        "partially read.\n"
        "- If a file's actual content doesn't match what its name says it is (for example, a "
        "file renamed to look like a spreadsheet that isn't really one), it's rejected rather "
        "than processed incorrectly.\n"
        "- If the file itself is fine but some individual rows in it have a problem, those "
        "specific rows are skipped and reported - the rest of the file is still saved. A whole "
        "upload almost never fails outright just because of a few bad rows.\n"
        "- Reassurance worth giving here: nothing is ever silently thrown away. Every row that "
        "couldn't be read is reported back with the reason, so it can be fixed and re-uploaded "
        "if needed.\n\n"
        "Connecting your own database or system directly didn't work:\n"
        "- The most common reason is a mistyped host, port, or login detail, or a query/field "
        "mapping that doesn't quite match what the connection expects - double-checking those "
        "details and trying again resolves most connection problems.\n"
        "- A connection can be checked at any time to see whether it's actually linked yet.\n\n"
        "The chat itself gave an error or didn't respond:\n"
        "- This means the AI reasoning step itself had a temporary problem (a busy or momentarily "
        "unreachable service), not that the tenant's own data was lost or wrong - trying the same "
        "question again shortly almost always works.\n"
        "- If a specific competitor or piece of data seems to be missing from an answer, it may "
        "simply not have been collected yet, or it was automatically held back by the platform's "
        "own safety review rather than shown - this is a real, deliberate safeguard, not a bug.\n\n"
        "In every case: a real problem is reported honestly, with a real, specific reason - never "
        "a vague 'something went wrong' with nothing else to go on, and never a guessed answer in "
        "place of the real error."
    )


_GENERATORS = {
    SLOT_SALES_HISTORY: generate_sales_history_summary,
    SLOT_COMPETITOR_LANDSCAPE: generate_competitor_landscape_summary,
    SLOT_SENTIMENT_TRENDS: generate_sentiment_trends_summary,
    SLOT_MARKET_PRICING: generate_market_pricing_summary,
    SLOT_DEMAND_FORECAST: generate_demand_forecast_summary,
    SLOT_STRATEGIC_INSIGHTS: generate_strategic_insights_summary,
    SLOT_PLATFORM_HELP: generate_platform_help_summary,
    SLOT_POS_ERP_SYSTEMS: generate_pos_erp_summary,
    SLOT_TROUBLESHOOTING_HELP: generate_troubleshooting_help_summary,
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
            try:
                conn.rollback()  # a failed query leaves the transaction aborted, failing every later slot
            except Exception:  # noqa: BLE001
                pass

    processed_count = ingest_pending_documents(conn, minio_client, tenant_id, bucket=bucket)
    return {"document_ids": document_ids, "chunks_ingested_for": processed_count}
