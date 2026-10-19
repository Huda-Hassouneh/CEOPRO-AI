"""
KEEL - Reduce/Discontinue Candidate Insight (real "what should I
remove" signal).

Deliberately reuses dashboard/inventory_recommendations.py::
get_inventory_recommendations() rather than recomputing the same
forecast-vs-stock comparison a second time - that module's own docstring
already documents the real rule (predicted 30-day demand vs. current
stock, ACTION_THRESHOLD_PCT/HIGH_PRIORITY_THRESHOLD_PCT bands) and this
would just be drift-prone duplication of the identical logic. This module
only adds the framing a "should I remove this" question needs (a
suggestion to reconsider carrying the item at all, not just this month's
reorder quantity) and turns the strongest REDUCE_ORDER row into a real
Insight so it flows through the same proactive-surfacing path
(structured_context.py's always-on block, structured_summaries.py's
strategic-insights RAG slot) every other insight already uses.
"""
from typing import List

from src.ai.dashboard.inventory_recommendations import ACTION_REDUCE_ORDER, get_inventory_recommendations
from src.ai.insights.cross_signal import Insight

# Internal ranking only (never shown to the user) - a notch below
# category_gap.py's own ADD signal, since "demand is currently well below
# stock" is a real but reorder-cycle-sensitive signal, not yet a
# confirmed long-term discontinue case.
REDUCE_CANDIDATE_CONFIDENCE = 0.5

_LIMIT_FOR_SCAN = 50


def detect_reduce_candidate_insights(conn, tenant_id: str, max_insights: int = 1) -> List[Insight]:
    """Returns at most `max_insights` reduce-candidate findings, taken
    from get_inventory_recommendations()'s own already-sorted output
    (highest-magnitude gap first). Returns [] when there's no forecast/
    stock data yet, or nothing currently qualifies as REDUCE_ORDER."""
    result = get_inventory_recommendations(conn, tenant_id, limit=_LIMIT_FOR_SCAN)
    reduce_candidates = [r for r in result["recommendations"] if r["action"] == ACTION_REDUCE_ORDER]
    if not reduce_candidates:
        return []

    insights = []
    for rec in reduce_candidates[:max_insights]:
        reason = rec["reason"]
        reason_lowered = reason[0].lower() + reason[1:] if reason else reason
        insights.append(Insight(
            message=(
                f"{reason_lowered} Worth reconsidering how much of {rec['product_name']} you keep "
                f"in stock, or whether to phase it out over time, rather than reordering the same "
                f"amount again."
            ),
            category="assortment", product_id=rec["product_id"], confidence=REDUCE_CANDIDATE_CONFIDENCE,
        ))
    return insights
