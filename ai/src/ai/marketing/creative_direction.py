"""
KEEL - Marketing Campaign Creative Direction (visual theme selection).

THEMES is a fixed, named set of visual styles a tenant can pick for a
campaign's future image/video creative - CUSTOM lets them skip the fixed
set entirely and describe exactly what they want instead
(custom_creative_prompt). recommend_theme() is a deterministic rule over
real signals this platform already has (a product's own category, its
real market-positioning label from positioning.py, and this tenant's real
per-category market activity level from dashboard/market_overview.py) -
not a new ML model, and never a guess dressed up as one: every branch is
traceable to one of those three real inputs, and the fallback is always
the same neutral default, never invented.

No image or video is actually generated from any of this in Phase 1 - see
content_generator.py's own note on why. This module only decides which
named style (or the tenant's own custom instructions) gets folded into
the one LLM-synthesized creative_direction brief.
"""
from typing import Optional

from src.ai.dashboard import market_overview

THEMES = {
    "LUXURY_PREMIUM": "Luxury / Premium: polished, high-end, understated elegance. Emphasize quality and exclusivity, not price.",
    "MINIMAL_CLEAN": "Minimal / Clean: simple, uncluttered, lots of negative space, calm and confident tone.",
    "MODERN_TECH": "Modern / Tech: sleek, precise, innovation-forward, cool color palette, feature-led framing.",
    "SOCIAL_TRENDY": "Social Media / Trendy: energetic, of-the-moment, casual, built to stop a scroll.",
    "BOLD_PROMOTIONAL": "Bold / Promotional: high contrast, high energy, value/deal-forward, strong call to action.",
    "LIFESTYLE": "Lifestyle: the product shown in a real, relatable everyday moment rather than isolated on its own.",
    "SEASONAL": "Seasonal: tied to a specific season/holiday/moment in the calendar year.",
    "CUSTOM": "Custom: follow the tenant's own custom_creative_prompt instructions exactly, ignoring the named themes above.",
}

# Crude keyword match against a product's own category text - Phase 1's
# honest floor, not a real category classifier. Kept small and easy to
# see through, rather than pretending this is smarter than it is.
_TECH_KEYWORDS = ("electronic", "tech", "gadget", "computer", "phone", "laptop", "software", "device")
_LIFESTYLE_KEYWORDS = ("fashion", "apparel", "clothing", "home", "decor", "furniture", "beauty", "wellness")

_DEFAULT_THEME = "MINIMAL_CLEAN"


def recommend_theme(conn, tenant_id: str, category: Optional[str], positioning_label: Optional[str]) -> str:
    """
    Priority order, each branch grounded in one real signal:
    1. PREMIUM positioning (real competitor-pricing-derived data) -> Luxury/Premium.
    2. BUDGET positioning -> Bold/Promotional (value-forward framing fits
       a genuinely budget-positioned product better than a luxury one).
    3. Category text matches a tech keyword -> Modern/Tech.
    4. Category text matches a lifestyle keyword -> Lifestyle.
    5. This tenant's own real market_overview.category_activity for that
       category reads "High" (genuine recent competitor/sentiment/price
       activity, not invented) -> Social/Trendy.
    6. Otherwise -> MINIMAL_CLEAN, the neutral default that fits any
       product rather than guessing.
    """
    if positioning_label == "PREMIUM":
        return "LUXURY_PREMIUM"
    if positioning_label == "BUDGET":
        return "BOLD_PROMOTIONAL"

    category_lower = (category or "").lower()
    if any(keyword in category_lower for keyword in _TECH_KEYWORDS):
        return "MODERN_TECH"
    if any(keyword in category_lower for keyword in _LIFESTYLE_KEYWORDS):
        return "LIFESTYLE"

    if category:
        overview = market_overview.get_market_overview(conn, tenant_id)
        if overview["category_activity"].get(category) == "High":
            return "SOCIAL_TRENDY"

    return _DEFAULT_THEME
