"""
KEEL - RAG Chatbot Financial/Profitability Tool (query-driven, not
always-on).

structured_context.py's build_structured_facts_block() runs a fixed set
of cheap queries on EVERY chat turn - the right call for signals cheap
enough to always have ready (sentiment, competitor tiers, price gaps).
Profitability is a different shape of question: it needs two real
queries (dashboard/financial_summary.py's business-wide summary AND its
per-product ranking) that are more expensive and only relevant to a
minority of questions - so this module gates them behind a real intent
check on the question text first, the first real instance of this
service's RAG pipeline choosing which tool to run per-question rather
than running every tool on every question (see this feature's own "don't
blindly run every tool for every question" requirement).

This is intentionally simple - a keyword match, not a classifier or an
LLM-based intent call (which would add real latency/cost to every single
message just to decide whether to run two more queries). Both the
dashboard/financial_summary.py functions it calls and this module's own
formatting are 100% deterministic - no LLM arithmetic anywhere in this
path, matching this feature's own "never rely on LLM arithmetic when
database calculations can be performed" requirement.
"""
from typing import Optional

from src.ai.dashboard.financial_summary import get_product_profitability, get_profitability_summary

# English + Arabic (MSA + common Levantine/Gulf colloquial forms already
# used elsewhere in this service's own dialect-aware prompts) keywords for
# the question shapes this tool actually answers: profit/margin/cost
# questions, and "which product is doing well/badly" questions (the most
# common real phrasing of a profitability question that never says the
# word "profit" at all).
_FINANCIAL_KEYWORDS = (
    "profit", "margin", "gross margin", "cost of goods", "cogs", "profitable",
    "losing money", "lose money", "earn", "earning", "revenue", "markup",
    "most profitable", "least profitable", "best selling", "worst selling",
    "بالربح", "ربح", "أرباح", "الأرباح", "هامش", "هامش الربح", "خسارة", "خسران",
    "أكثر ربحية", "الأكثر ربحية", "الإيرادات", "إيرادات", "تكلفة البضاعة",
)


def is_financial_question(query_text: str) -> bool:
    lowered = (query_text or "").lower()
    return any(keyword in lowered for keyword in _FINANCIAL_KEYWORDS)


def build_financial_facts_block(conn, tenant_id: str, query_text: str) -> str:
    """
    Returns "" (never a placeholder) when the question doesn't look
    financial, OR when it does but there is genuinely no sales data to
    summarize - the same "empty means empty" convention
    structured_context.py's own build_structured_facts_block() already
    follows. Every line names its own source table/columns, the same
    provenance discipline as that module, so the LLM (and SYSTEM_PROMPT's
    own citation instructions) has something concrete to point at.
    """
    if not is_financial_question(query_text):
        return ""

    summary = get_profitability_summary(conn, tenant_id)
    ranking = get_product_profitability(conn, tenant_id)

    if summary["revenue"]["amount"] <= 0:
        return ""

    lines = [
        f"Gross margin analysis for the trailing {summary['window_days']} days "
        f"(source: invoices + invoice_items + products.cost_price):",
        f"- Revenue: {summary['revenue']['amount']} {summary['currency'] or ''}"
        + (f" ({summary['revenue']['change_pct']:+.1f}% vs. the prior {summary['window_days']}-day period)" if summary["revenue"]["change_pct"] is not None else " (no prior-period data to compare)"),
    ]

    if summary["gross_profit"]["amount"] is not None:
        coverage = summary["cost_data_coverage_pct"]
        lines.append(
            f"- Gross profit (revenue minus cost of goods sold): {summary['gross_profit']['amount']} {summary['currency'] or ''}, "
            f"gross margin {summary['gross_margin_pct']['recent']}%"
            + (f" ({summary['gross_margin_pct']['change_pts']:+.1f} percentage points vs. the prior period)" if summary["gross_margin_pct"]["change_pts"] is not None else "")
            + f". This covers {coverage}% of revenue - the rest is from products with no cost_price on file, so it is excluded from this figure, not counted as zero cost."
        )
    else:
        lines.append(
            "- Gross profit/margin: cannot be calculated - none of the products sold in this period have a cost_price on file "
            "(products.cost_price is not set)."
        )
    lines.append(
        f"- IMPORTANT: this is GROSS margin only (revenue minus product cost). It does NOT include "
        f"{', '.join(f.replace('_', ' ') for f in summary['excludes'])} - none of those are tracked in this platform's data today, "
        f"so this is not the tenant's full net profit."
    )

    if ranking["most_profitable"]:
        top = ranking["most_profitable"][0]
        lines.append(
            f"- Most profitable product (source: products, invoice_items): \"{top['product_name']}\" - "
            f"{top['gross_profit']} {summary['currency'] or ''} gross profit ({top['gross_margin_pct']}% margin) "
            f"from {top['units_sold']} units sold."
        )
    if ranking["least_profitable"]:
        bottom = ranking["least_profitable"][0]
        if bottom["gross_profit"] < 0:
            lines.append(
                f"- Losing money (source: products, invoice_items): \"{bottom['product_name']}\" - "
                f"{bottom['gross_profit']} {summary['currency'] or ''} gross loss from {bottom['units_sold']} units sold."
            )
    if ranking["no_cost_data"]:
        names = ", ".join(f'"{row["product_name"]}"' for row in ranking["no_cost_data"][:5])
        lines.append(f"- Sold this period but excluded above (no cost_price on file): {names}.")

    return "\n".join(lines)
