"""
CEOPRO AI - Dashboard Top Recommendations (presentation layer, not a new model).

Unifies pricing + sentiment + sales/demand into one "top actionable
alerts" feed for the dashboard, per the explicit ask: the Marketing-only
recommendations card in the mockup should really be a single engine
across every signal the platform already tracks. Rather than building a
second detection engine, this wraps the one that already exists and
already merges all of those signals - insights/pipeline.py::
generate_insights_for_tenant() (snapshot cross-signal correlations from
cross_signal.py, plus event-timing competitor-price-drop-vs-sales
correlations from causal_chain.py) - and reshapes its output for the
dashboard feed. No new rule, no changed signature: this module only
calls that function and relabels its result.
"""
from src.ai.insights.pipeline import generate_insights_for_tenant

DEFAULT_LIMIT = 3

# Insight.category -> a short, plain label for a dashboard chip. "causal_timing"
# (causal_chain.py's own category) is relabeled here since "Competitor Activity"
# means something to a business owner in a way "causal_timing" does not.
_CATEGORY_LABELS = {
    "pricing": "Pricing",
    "sentiment": "Customer Feedback",
    "demand": "Demand",
    "causal_timing": "Competitor Activity",
}


def _priority_label(confidence: float) -> str:
    """Confidence is explicitly "internal ranking only - never shown to the
    user" per Insight's own docstring in cross_signal.py - this translates
    it into a plain priority word instead of exposing the raw number,
    same discipline structured_summaries.py's _plain_confidence_label()
    already applies to forecast confidence."""
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def get_top_recommendations(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> list:
    insights = generate_insights_for_tenant(conn, tenant_id, max_insights=limit)
    return [
        {
            "product_id": insight.product_id,
            "category": _CATEGORY_LABELS.get(insight.category, insight.category),
            "priority": _priority_label(insight.confidence),
            "message": insight.message,
        }
        for insight in insights
    ]
