"""
KEEL - Dashboard Expansion Opportunities (presentation layer, not a
new model).

The Market Intelligence page's "Expansion Opportunities" cards - reuses
insights/category_gap.py::detect_category_gap_details() (the same real
category-gap detection, competitor-count threshold, and vertical playbook
note already used for the chatbot's own ADD-type insight), reshaped into
one card per gap. No new detection rule, no new table: an empty list here
means this platform genuinely has no competitor-catalog category the
tenant doesn't already carry (or not enough tracked-competitor market
observation data yet to tell) - never a fabricated opportunity.
"""
from src.ai.insights.category_gap import detect_category_gap_details

DEFAULT_MAX_RESULTS = 3


def get_expansion_opportunities(conn, tenant_id: str, max_results: int = DEFAULT_MAX_RESULTS) -> list:
    gaps = detect_category_gap_details(conn, tenant_id, max_results=max_results)
    return [
        {
            "category": gap["category"],
            "opportunity_score": round(gap["confidence"] * 100),
            "competitor_count": gap["competitor_count"],
            "note": gap["note"],
        }
        for gap in gaps
    ]
