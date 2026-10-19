"""
KEEL - Business Copilot Tool Registry (Phase 2).

A controlled, read-only set of tools the RAG orchestrator (orchestrator.py)
can call, each a thin, tenant-scoped wrapper around an EXISTING service
function - see the module-level comment above each wrapper for exactly
which file:function it reuses. Per this feature's own requirement, NOTHING
here duplicates database logic that already exists elsewhere; a wrapper
that would need real new SQL (get_low_stock_products) was added to the
existing dashboard/inventory.py module it belongs with, not written here.

Every tool function has the same shape: `tool_fn(conn, tenant_id, **kwargs)
-> dict`. `conn` is always an already tenant-scoped connection (RLS is
enforced by the connection itself via db.py::app_role_connection() /
PooledTenantConnection's SET LOCAL app.current_tenant_id - see B10 in
RAG_BUSINESS_COPILOT_ARCHITECTURE.md and test_business_copilot_tools_
tenant_isolation.py) - no tool here does its own tenant filtering, and
none accepts a tenant_id that could differ from the authenticated caller's
own (the orchestrator always passes the request's own ctx.tenant_id).

Every tool is READ-ONLY. No tool here can create, update, or delete
anything - see B11 in RAG_BUSINESS_COPILOT_ARCHITECTURE.md for why write
actions were deliberately not added this pass.

TOOL_REGISTRY at the bottom maps a stable tool name -> (function,
description) for orchestrator.py to use. The description is what a human
reads when deciding what a tool does, not a prompt fed to the LLM asking
it to invent when to call it - tool SELECTION here is the same kind of
deterministic keyword-gate business_tools.py already established
(orchestrator.py), not an LLM planning loop.
"""
from typing import Optional

from src.ai.dashboard import (
    competitor_activity as _competitor_activity,
    competitor_pricing as _competitor_pricing,
    competitors as _competitors,
    financial_summary as _financial_summary,
    forecast as _forecast,
    forecast_detail as _forecast_detail,
    inventory as _inventory,
)
from src.ai.knowledge.application_registry import get_feature, search_features
from src.ai.marketing import data_access as _marketing_data_access
from src.ai.pricing import pipeline as _pricing_pipeline
from src.ai.rag.pipeline import run_retrieval as _run_retrieval
from src.ai.routers import products as _products_router


# ---------------------------------------------------------------------------
# Application knowledge (wraps src/ai/knowledge/application_registry.py)
# ---------------------------------------------------------------------------

def search_application_knowledge(conn, tenant_id: str, query_text: str) -> dict:
    """Tenant-independent (application knowledge is the same for every
    tenant - it describes KEEL itself, not a tenant's data). `conn`/
    `tenant_id` are accepted anyway to keep every tool's call signature
    uniform for the orchestrator."""
    matches = search_features(query_text)
    return {"matches": [_feature_to_dict(f) for f in matches]}


def get_feature_details(conn, tenant_id: str, feature_id: str) -> dict:
    feature = get_feature(feature_id)
    if feature is None:
        return {"found": False, "feature_id": feature_id}
    return {"found": True, "feature": _feature_to_dict(feature)}


def get_page_workflow(conn, tenant_id: str, feature_id: str) -> dict:
    """Same underlying entry as get_feature_details - a distinct tool name
    because a "how do I do X" question wants action_steps specifically,
    not the full record (route/component/api metadata a UI-help answer
    doesn't need to mention)."""
    feature = get_feature(feature_id)
    if feature is None:
        return {"found": False, "feature_id": feature_id}
    return {"found": True, "name": feature.name, "action_steps": feature.action_steps}


def _feature_to_dict(feature) -> dict:
    return {
        "feature_id": feature.feature_id,
        "name": feature.name,
        "route": feature.route,
        "action": feature.action,
        "action_steps": feature.action_steps,
        "fields": feature.fields,
    }


# ---------------------------------------------------------------------------
# Products (wraps src/ai/routers/products.py's own list_products/get_product
# - the same functions the real GET /products, GET /products/{id} endpoints
# call, not a reimplementation)
# ---------------------------------------------------------------------------

def list_products(conn, tenant_id: str, limit: int = 20, search: Optional[str] = None) -> dict:
    return _products_router.list_products(conn, tenant_id, limit=limit, search=search)


def get_product(conn, tenant_id: str, product_id: str) -> dict:
    product = _products_router.get_product(conn, tenant_id, product_id)
    return {"found": product is not None, "product": product}


def search_products(conn, tenant_id: str, query_text: str, limit: int = 10) -> dict:
    return _products_router.list_products(conn, tenant_id, limit=limit, search=query_text)


# ---------------------------------------------------------------------------
# Sales / financial (wraps dashboard/financial_summary.py - already the
# real backing for the always-financial-facts-block in business_tools.py;
# reused here as callable tools for orchestrator.py's broader intent set,
# not duplicated)
# ---------------------------------------------------------------------------

def get_sales_summary(conn, tenant_id: str, window_days: int = 30) -> dict:
    return _financial_summary.get_profitability_summary(conn, tenant_id, window_days=window_days)


def get_top_selling_products(conn, tenant_id: str, window_days: int = 30, limit: int = 10) -> dict:
    ranking = _financial_summary.get_product_profitability(conn, tenant_id, window_days=window_days, limit=limit)
    return {"window_days": window_days, "top_by_gross_profit": ranking["most_profitable"]}


def get_revenue_summary(conn, tenant_id: str, window_days: int = 30) -> dict:
    return _financial_summary.get_profitability_summary(conn, tenant_id, window_days=window_days)


def get_profitability_summary(conn, tenant_id: str, window_days: int = 30) -> dict:
    return _financial_summary.get_profitability_summary(conn, tenant_id, window_days=window_days)


def analyze_margin(conn, tenant_id: str, window_days: int = 30) -> dict:
    """New deterministic root-cause tool - see financial_summary.py::
    analyze_margin_change() for the decomposition itself; never LLM math."""
    return _financial_summary.analyze_margin_change(conn, tenant_id, window_days=window_days)


def analyze_revenue_change(conn, tenant_id: str, window_days: int = 30) -> dict:
    return _financial_summary.analyze_revenue_change(conn, tenant_id, window_days=window_days)


# ---------------------------------------------------------------------------
# Inventory (wraps dashboard/inventory.py - get_low_stock_products is new
# in that file this pass, filling a real, confirmed gap; get_inventory_status
# already existed)
# ---------------------------------------------------------------------------

def get_inventory_summary(conn, tenant_id: str) -> dict:
    return _inventory.get_inventory_status(conn, tenant_id)


def get_low_stock_products(conn, tenant_id: str, limit: int = 20) -> dict:
    products = _inventory.get_low_stock_products(conn, tenant_id, limit=limit)
    return {"low_stock_products": products}


# ---------------------------------------------------------------------------
# Competitors (wraps dashboard/competitors.py, competitor_pricing.py,
# competitor_activity.py - all already real, already used by the dashboard
# UI)
# ---------------------------------------------------------------------------

def list_competitors(conn, tenant_id: str) -> dict:
    return _competitors.get_competitor_directory(conn, tenant_id)


def get_competitor_activity(conn, tenant_id: str, window_days: int = 30, limit: int = 10) -> dict:
    return {
        "recent_price_changes": _competitor_activity.get_recent_competitor_price_changes(conn, tenant_id, limit),
        "market_activity": _competitor_activity.get_market_activity_levels(conn, tenant_id, window_days),
    }


def compare_competitor_prices(conn, tenant_id: str, limit: int = 10) -> dict:
    return {"positioning": _competitor_pricing.get_competitor_price_positioning(conn, tenant_id, limit=limit)}


# ---------------------------------------------------------------------------
# Pricing (wraps pricing/pipeline.py - the real POST /pricing/recommend
# backing function)
# ---------------------------------------------------------------------------

def get_pricing_recommendation(conn, tenant_id: str, product_id: str) -> dict:
    try:
        return _pricing_pipeline.run_price_recommendation(conn, tenant_id, product_id)
    except ValueError as exc:
        return {"error": str(exc)}


def compare_current_price_to_market(conn, tenant_id: str, product_id: str) -> dict:
    """Same underlying pipeline as get_pricing_recommendation - a distinct
    tool name because "how does my price compare" and "what should I
    price this at" are different question shapes the orchestrator routes
    on, even though the current implementation answers both from the same
    real competitor-price comparison."""
    return get_pricing_recommendation(conn, tenant_id, product_id)


# ---------------------------------------------------------------------------
# Forecasting (wraps dashboard/forecast.py, forecast_detail.py - the
# presentation-layer reads of already-computed demand_forecasts rows, NOT
# forecasting/pipeline.py::run_forecast, which triggers a real model run -
# a chat tool should read existing forecasts, never train a model per
# question)
# ---------------------------------------------------------------------------

def get_product_forecast(conn, tenant_id: str, product_id: str) -> dict:
    return _forecast_detail.get_product_forecast_detail(conn, tenant_id, product_id)


def get_demand_summary(conn, tenant_id: str) -> dict:
    return _forecast.get_forecast_summary(conn, tenant_id)


# ---------------------------------------------------------------------------
# Marketing (wraps marketing/data_access.py - the real campaign CRUD
# backing GET /marketing/campaigns)
# ---------------------------------------------------------------------------

def get_campaign_summary(conn, tenant_id: str, campaign_id: str) -> dict:
    campaign = _marketing_data_access.get_campaign(conn, tenant_id, campaign_id)
    return {"found": campaign is not None, "campaign": campaign}


def get_marketing_performance(conn, tenant_id: str, limit: int = 10) -> dict:
    return _marketing_data_access.list_campaigns(conn, tenant_id, limit=limit)


# ---------------------------------------------------------------------------
# RAG / documents (wraps rag/pipeline.py::run_retrieval - the exact same
# hybrid BM25+FAISS+RRF+cross-encoder pipeline answer_query() already
# uses, not a second retrieval implementation)
# ---------------------------------------------------------------------------

def search_documents(conn, tenant_id: str, query_text: str, top_k: int = 5) -> dict:
    context = _run_retrieval(conn, tenant_id, query_text, top_k=top_k)
    return {"context_text": context.context_text, "sources": context.sources}


def retrieve_relevant_context(conn, tenant_id: str, query_text: str, top_k: int = 5) -> dict:
    return search_documents(conn, tenant_id, query_text, top_k=top_k)


# ---------------------------------------------------------------------------
# Registry: stable tool name -> (function, human-readable description).
# orchestrator.py uses the names/descriptions below; it never calls a tool
# function directly by import, so adding/removing a tool here is the one
# place that changes what's callable.
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "search_application_knowledge": (search_application_knowledge, "Search KEEL's own how-to/feature knowledge."),
    "get_feature_details": (get_feature_details, "Get full detail on one KEEL feature by feature_id."),
    "get_page_workflow": (get_page_workflow, "Get the step-by-step workflow for one KEEL feature."),
    "list_products": (list_products, "List this tenant's products."),
    "get_product": (get_product, "Get one product by id."),
    "search_products": (search_products, "Search this tenant's products by name."),
    "get_sales_summary": (get_sales_summary, "Revenue/gross-profit summary for a trailing window."),
    "get_top_selling_products": (get_top_selling_products, "Top products by gross profit for a trailing window."),
    "get_revenue_summary": (get_revenue_summary, "Revenue summary for a trailing window."),
    "get_profitability_summary": (get_profitability_summary, "Gross profitability summary for a trailing window."),
    "analyze_margin": (analyze_margin, "Decompose a gross-margin change into revenue/COGS/mix drivers."),
    "analyze_revenue_change": (analyze_revenue_change, "Decompose a revenue change into units x average-selling-price."),
    "get_inventory_summary": (get_inventory_summary, "Aggregate in-stock/low-stock inventory status."),
    "get_low_stock_products": (get_low_stock_products, "List products at or below their reorder level."),
    "list_competitors": (list_competitors, "List tracked competitors."),
    "get_competitor_activity": (get_competitor_activity, "Recent competitor price changes and market activity level."),
    "compare_competitor_prices": (compare_competitor_prices, "This tenant's price positioning vs. tracked competitors."),
    "get_pricing_recommendation": (get_pricing_recommendation, "Recommended price for one product from competitor data."),
    "compare_current_price_to_market": (compare_current_price_to_market, "How one product's price compares to the market."),
    "get_product_forecast": (get_product_forecast, "Demand forecast detail for one product."),
    "get_demand_summary": (get_demand_summary, "Demand-forecast summary across products."),
    "get_campaign_summary": (get_campaign_summary, "Detail on one marketing campaign."),
    "get_marketing_performance": (get_marketing_performance, "List of recent marketing campaigns."),
    "search_documents": (search_documents, "Hybrid retrieval over this tenant's ingested documents."),
    "retrieve_relevant_context": (retrieve_relevant_context, "Alias of search_documents."),
}
