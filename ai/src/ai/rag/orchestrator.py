"""
KEEL - Business Copilot Intent-Driven Tool Orchestration (Phase 2).

Extends the exact pattern business_tools.py already established (a real
keyword gate deciding whether to run extra queries for THIS question,
not every question) to the broader tool registry in rag/tools.py. This
is deliberately still NOT a general LLM planning/tool-calling loop - see
RAG_BUSINESS_COPILOT_ARCHITECTURE.md's "what this pass deliberately did
not build" section for why a real agentic loop is real future work, not
something safely added alongside everything else in this pass. What this
module adds over business_tools.py is breadth (more intent categories,
not just financial) using the same cheap, deterministic, always-inspectable
approach.

Each intent category below maps to ONE OR MORE tools from rag/tools.py's
TOOL_REGISTRY, called ONLY when the question's own text matches that
category's keywords - never every tool for every question (this
feature's own explicit requirement). Every block this module produces is
tagged with a SOURCE TYPE label (TENANT_BUSINESS_DATA vs.
CEOPRO_APPLICATION_KNOWLEDGE) so the prompt - and, downstream, the
frontend - can distinguish the user's own company data from KEEL's
self-knowledge, never presenting one as the other (B8/B9 in the
originating request).

Tool inputs here are always either none, or the tenant_id/query_text the
orchestrator already has - never a value invented from free text (e.g. no
attempt here to guess a specific product_id from "how is my iPhone case
doing" - see RAG_BUSINESS_COPILOT_ARCHITECTURE.md for why per-product
tools like get_pricing_recommendation/get_product_forecast are not wired
into this automatic gate: they need a real product_id, and guessing one
from free text risks calling a tool on the WRONG product and presenting
that as the tenant's own data, which is worse than not answering).
"""
from typing import List, Tuple

from src.ai.rag import tools as _tools

_APPLICATION_HELP_KEYWORDS = (
    "how do i", "how to", "where do i", "where can i", "how can i add",
    "كيف أضيف", "كيف يمكنني", "أين أجد", "وين ألقى",
)

_TOP_PRODUCTS_KEYWORDS = (
    "best selling", "best-selling", "top product", "top selling", "most sold",
    "أفضل مبيعا", "الأكثر مبيعا",
)

_INVENTORY_KEYWORDS = (
    "low stock", "out of stock", "restock", "reorder", "running low",
    "المخزون منخفض", "نفذ من المخزون", "إعادة الطلب",
)

_COMPETITOR_KEYWORDS = (
    "competitor", "competitors", "who is my competitor", "strongest competitor",
    "منافس", "منافسين", "المنافس",
)

_DEMAND_FORECAST_KEYWORDS = (
    "forecast", "demand", "predicted sales", "future sales",
    "توقع", "التوقعات", "الطلب المتوقع",
)

_MARKETING_KEYWORDS = (
    "campaign", "marketing performance", "ad performance",
    "حملة", "الحملة التسويقية", "أداء التسويق",
)

_ROOT_CAUSE_KEYWORDS = (
    "why did", "why is", "why are", "why has", "what caused", "what happened to",
    # "Where did my profits go?" is the canonical worked example from this
    # feature's own originating request - it asks the same root-cause
    # question as "why did my profit change" without the word "why". A
    # verification pass caught this exact phrase NOT triggering the
    # root-cause tool (only the always-on financial gate fired, which
    # reports what changed but not why) - a real gap on the one phrasing
    # explicitly named in the request, fixed narrowly rather than
    # open-endedly widening this keyword list.
    "where did", "where has", "where's my profit", "where is my profit",
    "لماذا", "ليش", "شو صار", "وين راح", "راح وين",
)


def _matches(lowered: str, keywords: tuple) -> bool:
    return any(keyword in lowered for keyword in keywords)


def _format_application_matches(matches: list) -> str:
    lines = []
    for match in matches[:3]:
        steps = " -> ".join(match["action_steps"])
        lines.append(f"- {match['name']} (route: {match['route']}): {steps}")
    return "How to do this in KEEL (source: application knowledge registry):\n" + "\n".join(lines)


def _format_top_products(result: dict) -> str:
    lines = ["Top-selling products by gross profit (source: invoices + invoice_items):"]
    for row in result["top_by_gross_profit"][:5]:
        lines.append(f"- {row['product_name']}: {row['units_sold']} units, {row['gross_profit']} gross profit ({row['gross_margin_pct']}% margin)")
    return "\n".join(lines)


def _format_low_stock(result: dict) -> str:
    products = result["low_stock_products"]
    if not products:
        return "Inventory (source: inventory table): no products are currently at or below their reorder level."
    lines = ["Products at or below their reorder level (source: inventory table):"]
    for row in products[:10]:
        lines.append(f"- {row['product_name']}: {row['stock_quantity']} in stock (reorder level {row['reorder_level']})")
    return "\n".join(lines)


def _format_competitors(directory: dict, activity: dict) -> str:
    # get_competitor_directory() returns {"strategic": [...], "relevant": [...]},
    # not a flat "competitors" key - see dashboard/competitors.py's own
    # docstring for why (two distinct UI groups, ordered by tier).
    strategic = directory.get("strategic", []) if isinstance(directory, dict) else []
    relevant = directory.get("relevant", []) if isinstance(directory, dict) else []
    all_competitors = strategic + relevant
    if not all_competitors:
        return "Competitors (source: global_competitors, tenant_competitors): no competitors are currently tracked for this tenant."
    lines = [f"Tracked competitors (source: global_competitors, tenant_competitors), {len(all_competitors)} total:"]
    for row in strategic[:5]:
        lines.append(f"- {row['name']} (strategic - {row.get('overlap_pct')}% product overlap)")
    for row in relevant[:3]:
        lines.append(f"- {row['name']} (relevant)")
    price_changes = activity.get("recent_price_changes", [])
    if price_changes:
        lines.append(f"Recent competitor price changes (source: competitor pricing history): {len(price_changes)} in the tracked window.")
    return "\n".join(lines)


def _format_demand(result: dict) -> str:
    return f"Demand forecast summary (source: demand_forecasts table): {result}"


def _format_marketing(result: dict) -> str:
    campaigns = result.get("campaigns", []) if isinstance(result, dict) else []
    if not campaigns:
        return "Marketing campaigns (source: campaigns table): no campaigns have been generated yet."
    lines = [f"Recent marketing campaigns (source: campaigns table), {len(campaigns)} total:"]
    for row in campaigns[:5]:
        lines.append(f"- {row.get('campaign_brief', 'Untitled')}: {row.get('status', 'UNKNOWN')}")
    return "\n".join(lines)


def _format_root_cause(revenue_analysis: dict, margin_analysis: dict) -> str:
    lines = ["Root-cause signals for a revenue/profit change (source: invoices + invoice_items + products.cost_price):"]
    if revenue_analysis.get("has_data"):
        drivers = revenue_analysis["drivers"]
        lines.append(
            f"- Revenue changed by {revenue_analysis['revenue_change']} "
            f"(units-sold effect: {drivers['units_effect']}, average-selling-price effect: {drivers['price_effect']})."
        )
        if revenue_analysis["top_movers"]:
            top = revenue_analysis["top_movers"][0]
            lines.append(f"- Biggest single mover: \"{top['product_name']}\" changed by {top['revenue_change']}.")
        lines.append(f"- IMPORTANT: {revenue_analysis['movers_caveat']}")
    else:
        lines.append("- Not enough sales data in both the recent and prior period to decompose a revenue change.")
    if margin_analysis.get("has_data"):
        drivers = margin_analysis["drivers"]
        lines.append(
            f"- Gross-profit change driven by: revenue effect {drivers['revenue_effect']}, "
            f"cost-of-goods-sold effect {drivers['cogs_effect']}."
        )
    lines.append(
        "- This schema has NO data on marketing spend, discounts/promotions, or competitor actions - "
        "if the question asks about those specifically, say plainly that this cannot be established from KEEL's data."
    )
    return "\n".join(lines)


def build_tool_facts_blocks(conn, tenant_id: str, query_text: str) -> List[Tuple[str, str]]:
    """
    Returns a list of (source_label, block_text) pairs - never a single
    concatenated string - specifically so the caller (llm_client.py) and,
    eventually, the frontend can keep each block's source type visible
    rather than flattening everything into one undifferentiated wall of
    text. source_label is one of "TENANT_BUSINESS_DATA" (this tenant's
    own real data) or "CEOPRO_APPLICATION_KNOWLEDGE" (how KEEL itself
    works - the same for every tenant). Only ever calls a tool when this
    question's own text matched that tool's intent keywords.
    """
    lowered = (query_text or "").lower()
    blocks: List[Tuple[str, str]] = []

    if _matches(lowered, _APPLICATION_HELP_KEYWORDS):
        result = _tools.search_application_knowledge(conn, tenant_id, query_text)
        if result["matches"]:
            blocks.append(("CEOPRO_APPLICATION_KNOWLEDGE", _format_application_matches(result["matches"])))

    if _matches(lowered, _TOP_PRODUCTS_KEYWORDS):
        result = _tools.get_top_selling_products(conn, tenant_id)
        if result["top_by_gross_profit"]:
            blocks.append(("TENANT_BUSINESS_DATA", _format_top_products(result)))

    if _matches(lowered, _INVENTORY_KEYWORDS):
        result = _tools.get_low_stock_products(conn, tenant_id)
        blocks.append(("TENANT_BUSINESS_DATA", _format_low_stock(result)))

    if _matches(lowered, _COMPETITOR_KEYWORDS):
        directory = _tools.list_competitors(conn, tenant_id)
        activity = _tools.get_competitor_activity(conn, tenant_id)
        blocks.append(("TENANT_BUSINESS_DATA", _format_competitors(directory, activity)))

    if _matches(lowered, _DEMAND_FORECAST_KEYWORDS):
        result = _tools.get_demand_summary(conn, tenant_id)
        if result:
            blocks.append(("TENANT_BUSINESS_DATA", _format_demand(result)))

    if _matches(lowered, _MARKETING_KEYWORDS):
        result = _tools.get_marketing_performance(conn, tenant_id)
        blocks.append(("TENANT_BUSINESS_DATA", _format_marketing(result)))

    if _matches(lowered, _ROOT_CAUSE_KEYWORDS):
        revenue_analysis = _tools.analyze_revenue_change(conn, tenant_id)
        margin_analysis = _tools.analyze_margin(conn, tenant_id)
        if revenue_analysis.get("has_data") or margin_analysis.get("has_data"):
            blocks.append(("TENANT_BUSINESS_DATA", _format_root_cause(revenue_analysis, margin_analysis)))

    return blocks


def format_blocks_for_prompt(blocks: List[Tuple[str, str]]) -> str:
    """Joins (label, text) pairs into the single string llm_client.py's
    prompt assembly expects, with an explicit [LABEL] header per block so
    the model (and SYSTEM_PROMPT's own citation instructions) can tell a
    tenant-data block from an application-knowledge block."""
    return "\n\n".join(f"[{label}]\n{text}" for label, text in blocks)
