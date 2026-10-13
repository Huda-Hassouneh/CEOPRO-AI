"""
KEEL - Live Structured Facts for the RAG Chatbot Prompt.

The other half of the hybrid design (structured_summaries.py is the
first half - narrative text embedded into the vector DB for qualitative
retrieval). This module answers a different need: an LLM asked for an
EXACT current number (today's price gap, this week's sentiment score)
should never have to rely on semantic search having retrieved the one
chunk with the precise right figure - a well-documented RAG failure mode
for numeric precision. build_structured_facts_block() queries the real,
current data directly and hands it to llm_client.py as a second,
separately-labeled prompt section, injected fresh on every question,
never chunked, never embedded, never stale between summary regenerations.

Deliberately small and fast: this runs on every single chat question
(unlike structured_summaries.py's regenerate_all_structured_summaries(),
meant for a schedule/webhook), so it stays to a handful of cheap,
indexed queries - not a full report.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.ai.insights.pipeline import generate_insights_for_tenant
from src.ai.sentiment.pipeline import get_subject_sentiment_summary
from src.ai.core.money import format_money_text as format_money
from src.ai.core.quantities import format_quantity
from src.ai.core.business_time import window_start

# How far back a real observed competitor listing/price/post still counts
# as "recent" enough to mention - old enough to catch a genuine recent
# event, short enough that this never surfaces something stale as if it
# just happened.
RECENT_COMPETITOR_ACTIVITY_WINDOW_DAYS = 30


def _build_competitor_activity_block(conn, tenant_id: str) -> list:
    """
    Real, direct links to what was actually observed on a tracked
    competitor's own page - the answer to "can you show me proof" and
    "why did my sales drop" questions that name a specific competitor.
    Confidence-gated the same way structured_context.py's own competitor-
    name block already is: only STRATEGIC/RELEVANT tier (never an
    unevaluated CANDIDATE - "absolutely sure it's a real competitor" is
    exactly what that tier gate already means), and only safety_status =
    'SAFE' (a QUARANTINED observation was held back by the platform's own
    safety review for a reason, never surfaced here as real evidence).

    market_observations.canonical_url (populated by the real scraper/
    social collectors - market_repository.py::save_market_record()) was,
    until this, stored and never read anywhere in ai/ - this is the real
    fix for that: a link that already existed, just never reached the
    chatbot. This is a real observed snapshot (a listing, a price, a
    page), never a confirmed "marketing campaign" classification this
    platform has no data to actually support - SYSTEM_PROMPT's own
    "Competitor activity and direct links" paragraph is what keeps the
    model from overstating what this line actually proves.
    """
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_COMPETITOR_ACTIVITY_WINDOW_DAYS)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, mo.product_name, mo.category, mo.canonical_url, mo.observed_at
            FROM market_observations mo
            JOIN competitor_product_mappings cpm
                ON cpm.tenant_id = mo.tenant_id AND cpm.mapping_id = mo.mapping_id
            JOIN tenant_competitors tc
                ON tc.tenant_id = cpm.tenant_id AND tc.global_competitor_id = cpm.global_competitor_id
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE mo.tenant_id = %(tenant_id)s
              AND tc.tier IN ('STRATEGIC', 'RELEVANT') AND tc.is_tracked = TRUE
              AND mo.safety_status = 'SAFE'
              AND mo.observed_at >= %(since)s
            ORDER BY mo.observed_at DESC
            LIMIT 5;
            """,
            {"tenant_id": tenant_id, "since": since},
        )
        rows = cursor.fetchall()

    if not rows:
        return []

    lines = [
        "Recently observed competitor activity, with a direct link to what was seen (source: "
        "market_observations, only from confirmed RELEVANT/STRATEGIC-tier tracked competitors, "
        f"last {RECENT_COMPETITOR_ACTIVITY_WINDOW_DAYS} days) - only mention one of these if it's "
        "actually relevant to the current question; always include the link when you cite one:"
    ]
    for competitor_name, product_name, category, canonical_url, observed_at in rows:
        category_text = f" ({category})" if category else ""
        lines.append(
            f"- {competitor_name}: \"{product_name}\"{category_text}, observed on "
            f"{observed_at.date().isoformat()}. Link: {canonical_url}"
        )
    return lines


SALES_WINDOW_DAYS = 30


def _build_sales_block(conn, tenant_id: str) -> list:
    """
    "How were sales this month / what sold best?" is the most common owner
    question, and no other always-on line answers it: the sales narrative in
    structured_summaries.py is a retrieved document, so it only helps when
    semantic search happens to rank it. Same windows and revenue definition
    as the dashboard revenue card (dashboard/metrics.py: invoices.total_amount
    by issue_date, last 30 days vs the 30 days before), so the assistant and
    the dashboard never disagree.
    """
    now = datetime.now(timezone.utc)
    recent_start = window_start(conn, SALES_WINDOW_DAYS)
    prior_start = window_start(conn, SALES_WINDOW_DAYS, periods=2)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT currency,
                   COALESCE(SUM(total_amount) FILTER (WHERE issue_date >= %(recent)s), 0),
                   COUNT(*) FILTER (WHERE issue_date >= %(recent)s),
                   COALESCE(SUM(total_amount) FILTER (WHERE issue_date < %(recent)s), 0)
            FROM invoices
            WHERE tenant_id = %(tenant)s AND issue_date >= %(prior)s
            GROUP BY currency
            ORDER BY 2 DESC;
            """,
            {"tenant": tenant_id, "recent": recent_start, "prior": prior_start},
        )
        totals = cursor.fetchall()
        cursor.execute(
            """
            SELECT localized_text(p.product_name) AS name,
                   i.currency, SUM(ii.quantity) AS units, SUM(ii.total_price) AS revenue
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
            WHERE ii.tenant_id = %s AND i.issue_date >= %s
            GROUP BY p.product_id, p.product_name, i.currency
            ORDER BY revenue DESC
            LIMIT 5;
            """,
            (tenant_id, recent_start),
        )
        top_products = cursor.fetchall()
    if not totals:
        return []
    lines = [f"Sales in the last {SALES_WINDOW_DAYS} days (source: invoices.total_amount by issue_date, same as the dashboard revenue card):"]
    for currency, recent, invoice_count, prior in totals:
        lines.append(
            f"- Revenue {format_money(recent, currency)} {currency} from {invoice_count} invoices; "
            f"the {SALES_WINDOW_DAYS} days before: {format_money(prior, currency)} {currency}."
        )
    if top_products:
        lines.append(f"Top products by revenue in the last {SALES_WINDOW_DAYS} days (source: invoice_items joined to products):")
        for name, currency, units, revenue in top_products:
            lines.append(f"- {name}: {format_money(revenue, currency)} {currency} from {format_quantity(units)} units.")
    return lines


def build_structured_facts_block(conn, tenant_id: str) -> str:
    """
    Real, current facts only - every line cites its own source table so
    the LLM's provenance discipline (llm_client.py's SYSTEM_PROMPT
    already instructs it to cite the table/field a number came from) has
    something concrete to point at. Returns "" (never a placeholder
    string) when nothing is available yet - answer_query() treats an
    empty block the same as empty retrieved context.
    """
    lines = _build_sales_block(conn, tenant_id)

    business_sentiment = get_subject_sentiment_summary(conn, tenant_id, "BUSINESS")
    if business_sentiment["status"] == "OK":
        lines.append(
            f"Current overall sentiment score (source: sentiment_results, business-wide aggregate): "
            f"{business_sentiment['sentiment_score']:.2f} "
            f"(sample size: {business_sentiment['sample_size']['analyzed_count']} analyzed reviews)."
        )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT tier, COUNT(*) FROM tenant_competitors
            WHERE tenant_id = %s AND is_tracked = TRUE
            GROUP BY tier;
            """,
            (tenant_id,),
        )
        tier_rows = cursor.fetchall()
    if tier_rows:
        tier_text = ", ".join(f"{count} {tier}" for tier, count in tier_rows)
        lines.append(f"Current tracked competitor count by tier (source: tenant_competitors.tier): {tier_text}.")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.competitor_name, tc.tier, gc.website_url, tc.distance_km, gc.rating, gc.review_count,
                   tc.branch_count, gc.address
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE AND tc.tier IN ('STRATEGIC', 'RELEVANT')
            ORDER BY tc.tier = 'STRATEGIC' DESC, tc.relevance_score DESC NULLS LAST, gc.competitor_name ASC
            LIMIT 15;
            """,
            (tenant_id,),
        )
        competitor_rows = cursor.fetchall()
    if competitor_rows:
        # The real fix for "who are my competitors?" getting only a bare
        # tier count back: a competitor's own NAME already exists (real,
        # persisted - global_competitors.competitor_name/website_url) the
        # moment discovery registers it, regardless of whether it was ever
        # actually scraped for a price. This is injected here (always-on,
        # never chunked, never dependent on semantic search having ranked
        # the right RAG chunk highly enough) rather than relying only on
        # structured_summaries.py::generate_competitor_landscape_summary()'s
        # retrieved narrative - the guarantee this module's own docstring
        # already promises for exact numbers applies just as much to a
        # simple "name a competitor" question.
        lines.append(
            "Your actual tracked competitors by name (source: global_competitors.competitor_name, "
            "joined via tenant_competitors) - cite these real names directly when asked who your "
            "competitors are, rather than only stating a count or tier:"
        )
        for name, tier, website_url, distance, rating, reviews, branches, address in competitor_rows:
            details = [f"{tier} tier"]
            if distance is not None:
                details.append(f"{distance:.1f} km away")
            if address:
                details.append(address)
            if rating is not None:
                details.append(f"rated {float(rating):.1f}/5" + (f" from {reviews} public reviews" if reviews else ""))
            if branches and branches > 1:
                details.append(f"{branches} branches in the area")
            site_text = f" ({website_url})" if website_url else ""
            lines.append(f"- {name}{site_text}: {'; '.join(details)}.")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FILTER (WHERE NOT is_tracked), COUNT(*) FILTER (WHERE distance_km <= 1),
                   COUNT(*) FILTER (WHERE distance_km <= 3), MAX(last_seen_at)
            FROM tenant_competitors WHERE tenant_id = %s AND discovery_method IS NOT NULL;
            """,
            (tenant_id,),
        )
        suggested, within_1, within_3, refreshed = cursor.fetchone()
    if refreshed is not None:
        lines.append(
            f"Market scan (source: public map listings and web search, last refreshed {refreshed.date().isoformat()}): "
            f"{within_1} competing businesses within 1 km and {within_3} within 3 km; "
            f"{suggested} more found but not tracked."
        )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT localized_text(p.product_name) AS name,
                   p.current_price, p.currency, latest.scraped_price, gc.competitor_name
            FROM products p
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id
            LEFT JOIN global_competitors gc ON gc.global_competitor_id = cpm.global_competitor_id
            JOIN LATERAL (
                SELECT cpr.scraped_price
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                ORDER BY cpr.observed_at DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY ABS(p.current_price - latest.scraped_price) DESC
            LIMIT 5;
            """,
            (tenant_id,),
        )
        price_rows = cursor.fetchall()
    if price_rows:
        lines.append(
            "Largest price gaps between your current price and a competitor's latest recorded price (source: your "
            "product prices and KEEL competitor tracking). Each line names the competitor whose price it is - "
            "never attribute a price to any other competitor:"
        )
        for name, own_price, currency, competitor_price, competitor_name in price_rows:
            who = competitor_name or "a tracked competitor (name not recorded)"
            lines.append(f"- {name}: you charge {float(own_price):.2f} {currency}; {who} charges {float(competitor_price):.2f} {currency}.")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                localized_text(p.product_name) AS name,
                df.expected_demand, df.forecast_target_date
            FROM demand_forecasts df
            JOIN products p ON p.tenant_id = df.tenant_id AND p.product_id = df.product_id
            WHERE df.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY df.product_id, df.created_at DESC
            LIMIT 5;
            """,
            (tenant_id,),
        )
        forecast_rows = cursor.fetchall()
    if forecast_rows:
        lines.append("Current demand forecasts, most recent per product (source: demand_forecasts):")
        for name, expected_demand, target_date in forecast_rows:
            lines.append(f"- {name}: about {format_quantity(expected_demand)} units expected in total between now and {target_date.isoformat()}.")

    # Proactive cross-signal insights (src.ai.insights) - injected on every
    # single question, not only when explicitly asked for "advice" or
    # "recommendations": the whole point of automating this synthesis is
    # that the chatbot can weave a relevant strategic observation into any
    # answer without the user having to know to ask for it separately.
    # Capped small (top 3, not all 5 generate_insights_for_tenant() can
    # return) since this block is injected on every question regardless
    # of relevance to what was actually asked - keep it a nudge, not a
    # wall of unrelated text competing with the real answer.
    insights = generate_insights_for_tenant(conn, tenant_id, max_insights=3)
    if insights:
        lines.append("Proactive insights worth mentioning if relevant (source: cross-signal analysis of pricing, sentiment, sales, and forecasts):")
        for insight in insights:
            lines.append(f"- {insight.message}")

    lines.extend(_build_competitor_activity_block(conn, tenant_id))

    return "\n".join(lines)
