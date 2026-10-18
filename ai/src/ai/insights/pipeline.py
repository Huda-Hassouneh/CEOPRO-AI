"""
KEEL - Cross-Signal Insight Pipeline (I/O layer for cross_signal.py).

Gathers each product's current reading across four independent, already-
computed signals - pricing (products/competitor_prices, same tables
rag/structured_summaries.py's own market-pricing narrative already reads),
sentiment (sentiment_results, product-level with a business-wide fallback
when a product has no analyzed reviews of its own yet), sales trend
(invoices/invoice_items, the platform's real internal sales record), and
demand forecast (demand_forecasts, forecasting/pipeline.py's own output) -
into one ProductSignals per product, then hands them to cross_signal.py's
pure rule engine.

Read-only across module boundaries by design: per src/infrastructure/
DATA_OWNERSHIP_AND_CONTRACTS.md's ownership matrix, the AI Advisor/Chatbot
is an explicitly allowed READER of every one of these tables, and this
module never writes to any of them - it only synthesizes a chatbot-facing
narrative (via rag/structured_summaries.py's own write path into its own
rag_documents_metadata/rag_document_chunks tables), exactly the same
boundary rag/structured_summaries.py's other generators already respect.

Every query here is batched across all of a tenant's products in one
round trip (not one query per product) - the same N+1 discipline already
established in this codebase (see rag/structured_summaries.py::
generate_sentiment_trends_summary()'s own docstring for the identical
fix applied to per-competitor sentiment).
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.ai.insights.assortment_reduce import detect_reduce_candidate_insights
from src.ai.insights.category_gap import detect_category_gap_insights
from src.ai.insights.causal_chain import detect_causal_price_sales_insight, detect_price_drop_events
from src.ai.insights.cross_signal import Insight, ProductSignals, detect_insights
from src.ai.core.business_time import window_start
from src.ai.insights import sales as canonical_sales

SALES_TREND_WINDOW_DAYS = 30

# How far back to look for competitor price-drop events and the tenant's
# own matching daily sales history. Long enough to contain a real event
# plus a full COMPARISON_WINDOW_DAYS (causal_chain.py) on both sides of
# it; short enough that a years-old price change never gets correlated
# against today's sales.
CAUSAL_LOOKBACK_DAYS = 180


def _load_price_gaps(conn, tenant_id: str) -> Dict[str, float]:
    """{product_id: price_gap_pct}, positive = priced above the market average.
    Same source query shape as rag/structured_summaries.py::
    generate_market_pricing_summary() - only the most recent scraped price
    per competitor mapping, averaged across every mapped competitor."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.product_id, p.current_price, AVG(latest.scraped_price) AS avg_competitor_price
            FROM products p
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id
            JOIN tenant_competitors tc ON tc.tenant_id=cpm.tenant_id AND tc.global_competitor_id=cpm.global_competitor_id
            LEFT JOIN data_sources ds ON ds.tenant_id=cpm.tenant_id AND ds.source_id=cpm.source_id
            JOIN LATERAL (
                SELECT cpr.scraped_price,cpr.currency,cpr.is_available,cpr.is_exact_data,cpr.source_status,cpr.observed_at
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC,cpr.competitor_price_id DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
              AND cpm.is_active AND NOT cpm.tracking_paused AND cpm.comparison_confirmed AND tc.is_tracked
              AND (cpm.source_id IS NULL OR (ds.is_active AND ds.policy_status='ALLOWED'))
              AND latest.currency=p.currency AND latest.is_available AND latest.is_exact_data
              AND latest.source_status='ALLOWED' AND latest.scraped_price>0
              AND latest.observed_at >= now()-interval '30 days' AND latest.observed_at<=now()
            GROUP BY p.product_id, p.current_price;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    gaps = {}
    for product_id, current_price, avg_competitor_price in rows:
        current_price = float(current_price)
        avg_competitor_price = float(avg_competitor_price)
        if avg_competitor_price > 0:
            gaps[str(product_id)] = (current_price - avg_competitor_price) / avg_competitor_price * 100
    return gaps


def _load_product_sentiment(conn, tenant_id: str) -> "tuple[Dict[str, float], Optional[float]]":
    """Returns ({product_id: sentiment_score}, business_wide_sentiment_score) -
    product-level scores come from subject_type='PRODUCT' reviews only.
    Falls back to the tenant's overall business sentiment (one extra,
    cheap query) for a product with no analyzed reviews of its own -
    still a real signal, just less specific, and only ever used when the
    product-specific one is genuinely unavailable."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.product_id, LOWER(sr.sentiment_label), COUNT(*),
                   AVG(sr.positive_probability), AVG(sr.negative_probability)
            FROM reviews r
            JOIN sentiment_results sr ON sr.tenant_id=r.tenant_id AND sr.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.review_date BETWEEN now()-interval '30 days' AND now() AND r.safety_status='SAFE' AND r.source_status='ALLOWED' AND r.subject_type = 'PRODUCT' AND r.product_id IS NOT NULL
            GROUP BY r.product_id, sr.sentiment_label;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    totals: Dict[str, dict] = {}
    for product_id, _label, count, avg_pos, avg_neg in rows:
        key = str(product_id)
        bucket = totals.setdefault(key, {"total": 0, "pos_sum": 0.0, "neg_sum": 0.0})
        bucket["total"] += int(count)
        bucket["pos_sum"] += float(avg_pos or 0) * int(count)
        bucket["neg_sum"] += float(avg_neg or 0) * int(count)

    scores = {
        product_id: round((bucket["pos_sum"] - bucket["neg_sum"]) / bucket["total"], 4)
        for product_id, bucket in totals.items()
        if bucket["total"] > 0
    }

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT LOWER(sr.sentiment_label), COUNT(*), AVG(sr.positive_probability), AVG(sr.negative_probability)
            FROM reviews r
            JOIN sentiment_results sr ON sr.tenant_id=r.tenant_id AND sr.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.review_date BETWEEN now()-interval '30 days' AND now() AND r.safety_status='SAFE' AND r.source_status='ALLOWED' AND r.subject_type = 'BUSINESS'
            GROUP BY sr.sentiment_label;
            """,
            (tenant_id,),
        )
        business_rows = cursor.fetchall()

    business_total = sum(int(count) for _label, count, _p, _n in business_rows)
    business_score = None
    if business_total > 0:
        pos_sum = sum(float(avg_pos or 0) * int(count) for _label, count, avg_pos, _n in business_rows)
        neg_sum = sum(float(avg_neg or 0) * int(count) for _label, count, _p, avg_neg in business_rows)
        business_score = round((pos_sum - neg_sum) / business_total, 4)

    return scores, business_score


def _load_sales_trends(conn, tenant_id: str) -> Dict[str, dict]:
    return canonical_sales.trends(conn,tenant_id,window_start(conn,SALES_TREND_WINDOW_DAYS),
                                  window_start(conn,SALES_TREND_WINDOW_DAYS,periods=2))


def _load_latest_forecasts(conn, tenant_id: str) -> Dict[str, dict]:
    """{product_id: {"expected_demand": float, "horizon_days": int}} - the
    most recent forecast per product only (a product can accumulate many
    forecast rows as horizon_days requests repeat)."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                df.product_id, df.expected_demand, df.forecast_target_date, df.created_at
            FROM demand_forecasts df
            WHERE df.tenant_id = %s AND df.forecast_target_date >= CURRENT_DATE
              AND df.created_at>=now()-interval '30 days' AND df.created_at<=now()
            ORDER BY df.product_id, df.created_at DESC,df.forecast_id DESC;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    forecasts = {}
    for product_id, expected_demand, target_date, created_at in rows:
        created_date = created_at.date() if hasattr(created_at, "date") else created_at
        horizon_days = 1 if target_date and created_date else 0  # each row is a target-day prediction, never a period total
        if horizon_days > 0:
            forecasts[str(product_id)] = {"expected_demand": float(expected_demand), "horizon_days": horizon_days}
    return forecasts


def _forecast_trend_pct(expected_demand: float, horizon_days: int, recent_units: Optional[float]) -> Optional[float]:
    """
    Compares the forecast against what the product's OWN recent sales
    pace alone would predict for a period of the same length - a genuine
    cross-check between the forecasting module's model output and the
    sales module's raw recent trend, not just two unrelated numbers
    placed side by side. None when there's no recent sales pace to
    project from (can't meaningfully say a forecast is "higher" or
    "lower" than an undefined baseline).
    """
    if recent_units is None or recent_units <= 0:
        return None
    daily_rate = recent_units / SALES_TREND_WINDOW_DAYS
    projected_at_current_rate = daily_rate * horizon_days
    if projected_at_current_rate <= 0:
        return None
    return (expected_demand - projected_at_current_rate) / projected_at_current_rate * 100


def load_product_signals(conn, tenant_id: str) -> List[ProductSignals]:
    """Assembles one ProductSignals per active product from four
    independently-sourced, batched queries above."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, COALESCE(product_name->>'en', product_name->>'ar', product_name::text)
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        products = cursor.fetchall()

    price_gaps = _load_price_gaps(conn, tenant_id)
    product_sentiment, business_sentiment = _load_product_sentiment(conn, tenant_id)
    sales_trends = _load_sales_trends(conn, tenant_id)
    forecasts = _load_latest_forecasts(conn, tenant_id)

    all_signals = []
    for product_id, name in products:
        key = str(product_id)
        sales = sales_trends.get(key, {})
        forecast = forecasts.get(key)
        forecast_trend = None
        if forecast is not None:
            forecast_trend = _forecast_trend_pct(
                forecast["expected_demand"], forecast["horizon_days"], sales.get("recent_units")
            )

        all_signals.append(ProductSignals(
            product_id=key,
            product_name=name,
            price_gap_pct=price_gaps.get(key),
            sentiment_score=product_sentiment.get(key, business_sentiment),
            sales_trend_pct=sales.get("trend_pct"),
            forecast_trend_pct=forecast_trend,
        ))
    return all_signals


def _load_competitor_price_histories(conn, tenant_id: str) -> Dict["tuple[str, str]", list]:
    """
    {(product_id, competitor_name): [(observed_date, price), ...]} sorted
    ascending by date - the real, append-only price-observation history
    (competitor_prices, one row per scrape) causal_chain.py needs to find
    genuine price-DROP EVENTS, as opposed to _load_price_gaps()' single
    latest-observation snapshot above. One batched query across every
    product/competitor pairing for the tenant, ordered so no in-Python
    re-sort is needed per group.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT cpm.product_id, gc.competitor_name, cpr.observed_at::date, cpr.scraped_price, cpm.mapping_id
            FROM competitor_product_mappings cpm
            JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN competitor_prices cpr ON cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
            JOIN products p ON p.tenant_id=cpm.tenant_id AND p.product_id=cpm.product_id
            JOIN tenant_competitors tc ON tc.tenant_id=cpm.tenant_id AND tc.global_competitor_id=cpm.global_competitor_id
            LEFT JOIN data_sources ds ON ds.tenant_id=cpm.tenant_id AND ds.source_id=cpm.source_id
            WHERE cpm.is_active AND NOT cpm.tracking_paused AND cpm.comparison_confirmed AND tc.is_tracked
              AND p.deleted_at IS NULL AND cpr.currency=p.currency AND cpr.scraped_price>0
              AND cpr.is_available AND cpr.is_exact_data AND cpr.source_status='ALLOWED' AND cpr.observed_at<=now()
              AND (cpm.source_id IS NULL OR (ds.is_active AND ds.policy_status='ALLOWED'))
              AND cpm.tenant_id = %(tenant_id)s
              AND cpr.observed_at >= %(since)s
            ORDER BY cpm.product_id, cpm.mapping_id, cpr.observed_at ASC,cpr.competitor_price_id ASC;
            """,
            {"tenant_id": tenant_id, "since": datetime.now(timezone.utc) - timedelta(days=CAUSAL_LOOKBACK_DAYS)},
        )
        rows = cursor.fetchall()

    histories: Dict["tuple[str, str]", list] = {}
    for product_id, competitor_name, observed_date, price, mapping_id in rows:
        key = (str(product_id), competitor_name, str(mapping_id))
        histories.setdefault(key, []).append((observed_date, float(price)))
    return histories


def _load_daily_sales_series(conn, tenant_id: str) -> Dict[str, Dict]:
    return canonical_sales.daily(conn,tenant_id,datetime.now(timezone.utc)-timedelta(days=CAUSAL_LOOKBACK_DAYS))


def generate_causal_insights_for_tenant(conn, tenant_id: str) -> List[Insight]:
    """
    The event-timing half of insight detection (see causal_chain.py's own
    docstring for how this differs from cross_signal.py's current-
    snapshot correlations): for every product/competitor pairing with at
    least two real price observations, checks whether a genuine
    competitor price-drop event was followed by a real decline in the
    tenant's own sales pace for that product - the vision's own "sales
    fell after a competitor cut their price" example.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, COALESCE(product_name->>'en', product_name->>'ar', product_name::text)
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id,),
        )
        product_names = {str(product_id): name for product_id, name in cursor.fetchall()}

    price_histories = _load_competitor_price_histories(conn, tenant_id)
    daily_sales_by_product = _load_daily_sales_series(conn, tenant_id)

    insights = []
    for (product_id, competitor_name, mapping_id), history in price_histories.items():
        if len(history) < 2:
            continue
        daily_sales = daily_sales_by_product.get(product_id)
        if not daily_sales:
            continue
        events = detect_price_drop_events(history)
        if not events:
            continue
        insight = detect_causal_price_sales_insight(
            product_id, product_names.get(product_id, "this product"), competitor_name, events, daily_sales,
        )
        if insight is not None:
            insight.rule_id="competitor_price_drop:"+mapping_id
            insight.facts["mapping_id"]=mapping_id
            insights.append(insight)
    return insights


def generate_insights_for_tenant(conn, tenant_id: str, max_insights: int = 5) -> List[Insight]:
    """The one function rag/structured_summaries.py's strategic-insights
    slot (and, via that, the chatbot) actually calls. Merges every
    detection type - current-snapshot (cross_signal.py), event-timing
    (causal_chain.py), real competitor-catalog category gaps
    (category_gap.py), and reduce/discontinue candidates
    (assortment_reduce.py) - before ranking and capping together, so the
    single strongest finding surfaces regardless of which detector found
    it. One detector's own query failing (e.g. no market_observations yet
    for a brand-new tenant) never blocks the others - each already
    degrades to [] on its own, per its own docstring."""
    signals = load_product_signals(conn, tenant_id)
    snapshot_insights = detect_insights(signals, max_insights=max_insights)
    causal_insights = generate_causal_insights_for_tenant(conn, tenant_id)
    category_gap_insights = detect_category_gap_insights(conn, tenant_id, max_insights=2)
    reduce_insights = detect_reduce_candidate_insights(conn, tenant_id, max_insights=1)

    combined = sorted(
        snapshot_insights + causal_insights + category_gap_insights + reduce_insights,
        key=lambda insight: insight.confidence, reverse=True,
    )
    return combined[:max_insights]
