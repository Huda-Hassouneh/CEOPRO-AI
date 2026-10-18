"""
KEEL - Application Knowledge Registry.

A structured, source-derived description of how the real KEEL
application actually works today - NOT screenshots, NOT free-text prose
guessed from memory. Every entry below was written by reading the actual
route table (frontend/src/app/router/routePaths.js), the actual page/
component files, and the actual backend router that serves each feature,
at the commit named in SOURCE_COMMIT below.

This is a deliberately CURATED subset (the highest-traffic, most-asked-
about flows), not exhaustive coverage of every route in routePaths.js -
see knowledge/registry_validator.py's own module docstring for what
"coverage" this registry claims and does not claim.

## How this stays in sync (read before trusting an old copy of this file)

This registry is NOT automatically regenerated when the frontend changes -
that would need a real route/component static-analysis generator, which is
real future work (see RAG_BUSINESS_COPILOT_ARCHITECTURE.md's Phase 2/3
section). What exists today is the next-safest thing:
`scripts/validate_application_knowledge.py` parses the actual
frontend/src/app/router/routePaths.js file and checks every `route` value
below against it, and checks every `frontend_source_file`/`backend_service`
path below actually exists on disk. It fails loudly (non-zero exit) if a
route was renamed/removed or a file was moved, so a stale entry is
DETECTED (not silently trusted) rather than auto-fixed. Run it:

    python backend/scripts/validate_application_knowledge.py

This is a manual/CI-triggered check, not a live/automatic sync - if nobody
runs it (locally or in CI) after a route changes, this file can still go
stale between runs. That is an honest limitation, not a hidden one.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# The commit this registry's content was verified against. Update this
# (and re-run validate_application_knowledge.py) whenever entries are
# added, changed, or re-verified - it is what "last_synchronized" below
# actually means: not "the app hasn't changed since", but "a human/CI run
# last checked these entries were still true as of this commit".
SOURCE_COMMIT = "3087cf6"
LAST_SYNCHRONIZED = "2026-09-25"


@dataclass(frozen=True)
class ApplicationFeature:
    feature_id: str
    name: str
    route: Optional[str]  # None when the action has no dedicated route (e.g. a modal on another page)
    page: str  # Page-level React component
    component: Optional[str]  # More specific sub-component, if the action lives inside one
    action: str
    action_steps: List[str]
    fields: List[str] = field(default_factory=list)
    field_meanings: Dict[str, str] = field(default_factory=dict)
    api_endpoint: Optional[str] = None
    http_method: Optional[str] = None
    permissions: str = "any authenticated tenant member"
    workflow_dependencies: List[str] = field(default_factory=list)
    backend_service: Optional[str] = None
    frontend_source_file: str = ""
    locale: List[str] = field(default_factory=lambda: ["en", "ar"])
    source_commit: str = SOURCE_COMMIT
    last_synchronized: str = LAST_SYNCHRONIZED


APPLICATION_FEATURES: List[ApplicationFeature] = [
    ApplicationFeature(
        feature_id="add_product",
        name="Add a product",
        route="/products/new",
        page="ProductFormPage",
        component="ProductForm",
        action="Create a new product",
        action_steps=[
            "Click 'Products' in the top navigation bar (/products).",
            "Click 'Add product' - this opens /products/new.",
            "Fill in the product name (English is required; Arabic is optional).",
            "Optionally set brand, category, current price, cost price, and initial stock quantity.",
            "Save - the product is created and you're returned to the product list.",
        ],
        fields=["product_name", "brand", "category", "current_price", "cost_price", "initial_stock_quantity", "currency"],
        field_meanings={
            "product_name": "Localized name - a JSON object with an 'en' key required and an optional 'ar' key.",
            "cost_price": "What the product costs you (used for gross-margin calculations elsewhere in the app). Optional - leaving it blank means margin can't be calculated for this product, not that its cost is zero.",
            "current_price": "The price you currently sell this product at.",
            "initial_stock_quantity": "Starting stock count; defaults to 0 if left blank.",
        },
        api_endpoint="/products",
        http_method="POST",
        workflow_dependencies=["Must be logged in and have completed onboarding (a company must exist)."],
        backend_service="src.ai.routers.products.create_product",
        frontend_source_file="frontend/src/features/products/pages/ProductFormPage.jsx",
    ),
    ApplicationFeature(
        feature_id="edit_product",
        name="Edit a product",
        route="/products/:productId/edit",
        page="ProductFormPage",
        component="ProductForm",
        action="Update an existing product's fields",
        action_steps=[
            "Go to Products (/products).",
            "Click a product row to open its edit page.",
            "Change any field (name, price, cost, stock) and save.",
        ],
        fields=["product_name", "brand", "category", "current_price", "cost_price", "currency"],
        api_endpoint="/products/{product_id}",
        http_method="PATCH",
        backend_service="src.ai.routers.products.update_product",
        frontend_source_file="frontend/src/features/products/pages/ProductFormPage.jsx",
    ),
    ApplicationFeature(
        feature_id="view_products",
        name="View products",
        route="/products",
        page="ProductsListPage",
        component="ProductTable",
        action="See the full product list with current price/stock",
        action_steps=["Click 'Products' in the top navigation bar."],
        api_endpoint="/products",
        http_method="GET",
        backend_service="src.ai.routers.products.list_products",
        frontend_source_file="frontend/src/features/products/pages/ProductsListPage.jsx",
    ),
    ApplicationFeature(
        feature_id="record_a_sale",
        name="Make a sale (quick sale)",
        route=None,  # Not a dedicated route - a modal opened from the products page.
        page="ProductsListPage",
        component="QuickSaleModal",
        action="Record a sale of one or more products (creates an invoice)",
        action_steps=[
            "Go to Products (/products).",
            "Click 'Quick sale' (opens QuickSaleModal, no page navigation).",
            "Pick a product and quantity.",
            "Submit - this creates a real invoice + invoice_item row, which is what Dashboard/",
            "financial reporting and this Assistant's own profitability answers are computed from.",
        ],
        fields=["product_id", "quantity", "unit_price"],
        api_endpoint="/sales/quick-sale",
        http_method="POST",
        backend_service="src.ai.sales.quick_sale.record_quick_sale",
        frontend_source_file="frontend/src/features/products/components/QuickSaleModal.jsx",
    ),
    ApplicationFeature(
        feature_id="view_competitors",
        name="View competitors",
        route="/market",
        page="CompetitorLandscapePage",
        component=None,
        action="See the competitor directory this tenant is tracking",
        action_steps=["Click 'Competitors' in the top navigation bar; the Overview tab lists every tracked competitor."],
        api_endpoint="/dashboard/competitors",
        http_method="GET",
        backend_service="src.ai.dashboard.competitors.get_competitor_directory",
        frontend_source_file="frontend/src/features/market-intelligence/pages/CompetitorLandscapePage.jsx",
    ),
    ApplicationFeature(
        feature_id="add_competitor",
        name="Add a competitor",
        route="/market/competitors/new",
        page="AddCompetitorPage",
        component=None,
        action="Manually register a competitor to track",
        action_steps=[
            "Click 'Competitors' in the top navigation bar (/market).",
            "Click 'Add competitor' - opens /market/competitors/new.",
            "Enter the competitor's details and save.",
        ],
        api_endpoint="/competitors",
        http_method="POST",
        backend_service="src.ai.routers.competitors",
        frontend_source_file="frontend/src/features/market-intelligence/pages/AddCompetitorPage.jsx",
    ),
    ApplicationFeature(
        feature_id="view_competitor_profile",
        name="View a competitor's profile",
        route="/market/competitors/:competitorId",
        page="CompetitorProfileDetailPage",
        component=None,
        action="See one competitor's detail: pricing, activity, products",
        action_steps=["From the competitor list, click a competitor's row."],
        backend_service="src.ai.dashboard.competitors.get_competitor_profile",
        frontend_source_file="frontend/src/features/market-intelligence/pages/CompetitorProfileDetailPage.jsx",
    ),
    ApplicationFeature(
        feature_id="pricing_recommendation",
        name="Get a pricing recommendation",
        route="/pricing",
        page="PricingPage",
        component=None,
        action="See a recommended price for a product based on competitor pricing",
        action_steps=["Click 'Pricing' in the top navigation bar, then select a product."],
        api_endpoint="/pricing/recommend",
        http_method="POST",
        workflow_dependencies=["Needs at least one tracked competitor with pricing data for a useful recommendation."],
        backend_service="src.ai.pricing.pipeline.run_price_recommendation",
        frontend_source_file="frontend/src/features/pricing/pages/PricingPage.jsx",
    ),
    ApplicationFeature(
        feature_id="demand_forecast",
        name="View demand forecasts",
        route="/demand",
        page="DemandPredictionOverviewPage",
        component=None,
        action="See predicted future demand per product",
        action_steps=["Click 'Demand' in the top navigation bar."],
        api_endpoint="/dashboard/forecast",
        http_method="GET",
        workflow_dependencies=["Needs enough historical sales data for this tenant's products to produce a forecast; otherwise shown as an honest empty state (see DemandPredictionEmptyPage)."],
        backend_service="src.ai.dashboard.forecast.get_forecast_summary",
        frontend_source_file="frontend/src/features/forecasting/pages/DemandPredictionOverviewPage.jsx",
    ),
    ApplicationFeature(
        feature_id="marketing_studio",
        name="Generate marketing content",
        route="/marketing",
        page="MarketingStudioPage",
        component="CampaignForm",
        action="Generate ad copy (and optionally an AI image) for a product or free-text brief",
        action_steps=[
            "Click 'Marketing' in the top navigation bar.",
            "Choose a product, or enter free text / a URL as the campaign brief.",
            "Pick a creative theme and tone, then generate.",
        ],
        api_endpoint="/marketing/campaigns",
        http_method="POST",
        backend_service="src.ai.routers.marketing",
        frontend_source_file="frontend/src/features/marketing/pages/MarketingStudioPage.jsx",
    ),
    ApplicationFeature(
        feature_id="rag_assistant",
        name="Ask the AI Business Copilot",
        route="/ai-advisor/chat",
        page="RagAssistantPage",
        component="RagChatWindow",
        action="Ask a question about your business, KEEL itself, or the market",
        action_steps=["Click 'Assistant' in the top navigation bar."],
        api_endpoint="/rag/query",
        http_method="POST",
        workflow_dependencies=["Requires GROQ_API_KEY (or a local LLM) to be configured server-side - see RAG_BUSINESS_COPILOT_ARCHITECTURE.md."],
        backend_service="src.ai.rag.llm_client.answer_query",
        frontend_source_file="frontend/src/features/knowledge-base/pages/RagAssistantPage.jsx",
    ),
    ApplicationFeature(
        feature_id="dashboard",
        name="View the dashboard",
        route="/dashboard",
        page="CommandCenterPage",
        component=None,
        action="See the business-at-a-glance summary (revenue, recommendations, forecasts)",
        action_steps=["Dashboard is the default page after login."],
        api_endpoint="/dashboard/metrics",
        http_method="GET",
        backend_service="src.ai.dashboard.metrics.get_dashboard_metrics",
        frontend_source_file="frontend/src/features/dashboard/pages/CommandCenterPage.jsx",
    ),
]


def get_feature(feature_id: str) -> Optional[ApplicationFeature]:
    for feature in APPLICATION_FEATURES:
        if feature.feature_id == feature_id:
            return feature
    return None


def search_features(query_text: str) -> List[ApplicationFeature]:
    """Simple substring match over name/action/feature_id - no embeddings/LLM
    involved, deliberately: this registry is small enough that a keyword
    match is both sufficient and fully deterministic (no risk of a vector
    search surfacing the wrong feature for a "how do I..." question)."""
    lowered = (query_text or "").lower()
    if not lowered:
        return []
    matches = []
    for feature in APPLICATION_FEATURES:
        haystack = " ".join([feature.feature_id, feature.name, feature.action, " ".join(feature.action_steps)]).lower()
        if any(word in haystack for word in lowered.split() if len(word) > 2):
            matches.append(feature)
    return matches
