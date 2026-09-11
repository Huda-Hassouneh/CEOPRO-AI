"""
CEOPRO AI - Live Structured Facts for the RAG Chatbot Prompt.

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
from typing import Optional

from src.ai.sentiment.pipeline import get_subject_sentiment_summary


def build_structured_facts_block(conn, tenant_id: str) -> str:
    """
    Real, current facts only - every line cites its own source table so
    the LLM's provenance discipline (llm_client.py's SYSTEM_PROMPT
    already instructs it to cite the table/field a number came from) has
    something concrete to point at. Returns "" (never a placeholder
    string) when nothing is available yet - answer_query() treats an
    empty block the same as empty retrieved context.
    """
    lines = []

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
            SELECT COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS name,
                   p.current_price, p.currency, latest.scraped_price
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
            ORDER BY ABS(p.current_price - latest.scraped_price) DESC
            LIMIT 5;
            """,
            (tenant_id,),
        )
        price_rows = cursor.fetchall()
    if price_rows:
        lines.append("Current largest price gaps vs. the most recent competitor observation (source: products.current_price vs. latest competitor_prices.scraped_price):")
        for name, own_price, currency, competitor_price in price_rows:
            lines.append(f"- {name}: you {float(own_price):.2f} {currency} vs. competitor {float(competitor_price):.2f} {currency}.")

    return "\n".join(lines)
