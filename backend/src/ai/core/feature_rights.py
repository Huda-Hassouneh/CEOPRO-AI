"""Informational projection of existing Python feature-rights configuration.

This module is deliberately pure: it consumes the plan structure returned by
``usage.get_plan`` and never queries storage, applies access controls, or changes
usage, billing, subscriptions, or Credits. Crosswalk aliases remain candidates
until separately approved; an unresolved mapping can never grant a Python right.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureMapping:
    """A crosswalk entry; candidate aliases are descriptive, not enforceable."""

    feature_code: str
    python_feature_code: str | None
    status: str


# Exact-code rows are grounded in current Python usage feature/module codes.
# Aliases are intentionally non-authoritative, even when the Python target exists.
FEATURE_MAPPINGS = (
    FeatureMapping("dashboard_analytics", None, "unmapped"),
    FeatureMapping("market_intelligence", "market_intelligence", "established_python_code"),
    FeatureMapping("market_perception", "market_intelligence", "candidate_alias"),
    FeatureMapping("demand_prediction", "demand_prediction", "established_python_code"),
    FeatureMapping("inventory_intelligence", None, "unmapped"),
    FeatureMapping("product_management", None, "unmapped"),
    FeatureMapping("competitor_management", "competitor_management", "established_python_code"),
    FeatureMapping("data_integration", None, "unmapped"),
    FeatureMapping("business_recommendations", None, "unmapped"),
    FeatureMapping("system_alerts", None, "unmapped"),
    FeatureMapping("ai_pricing", None, "unmapped"),
    FeatureMapping("sentiment_analysis", "sentiment_analysis", "established_python_code"),
    FeatureMapping("rag_assistant", "rag_assistant", "established_python_code"),
    FeatureMapping("document_extraction", "document_extraction", "established_python_code"),
    FeatureMapping("report_generation", "monthly_reports", "candidate_alias"),
    FeatureMapping("marketing_image_generation", "marketing_image_generation", "established_python_code"),
    FeatureMapping("tracked_competitors", "tracked_competitors", "established_python_code"),
    FeatureMapping("tracked_products", "tracked_products", "established_python_code"),
    FeatureMapping("connected_data_sources", "connected_data_sources", "established_python_code"),
    FeatureMapping("team_members", "team_seats", "candidate_alias"),
    FeatureMapping("document_storage_mb", "document_storage_mb", "established_python_code"),
    FeatureMapping("ai_credits", "ai_credits", "python_only"),
    FeatureMapping("data_credits", "data_credits", "python_only"),
    FeatureMapping("web_searches", "web_searches", "python_only"),
)

_BOOLEAN_RIGHTS = frozenset({
    "market_intelligence",
    "demand_prediction",
    "competitor_management",
})


def _effective_python_configuration(
    plan: Mapping[str, Any], python_code: str
) -> dict[str, Any]:
    """Describe only rights/configuration represented by an existing plan."""
    entitlements = plan.get("entitlements")
    if entitlements is None:
        return {
            "configured_state": "absent",
            "is_configured": False,
            "unit": None,
            "aggregation_type": None,
            "reset_cycle": None,
            "limit": None,
        }
    if isinstance(entitlements, (str, bytes)) or not isinstance(entitlements, (set, frozenset, list, tuple)):
        raise TypeError("plan entitlements must be a collection of feature codes")

    if python_code in _BOOLEAN_RIGHTS:
        enabled = python_code in entitlements
        return {
            "configured_state": "enabled" if enabled else "disabled",
            "is_configured": enabled,
            "unit": None,
            "aggregation_type": None,
            "reset_cycle": None,
            "limit": None,
        }

    features = plan.get("features", {})
    if not isinstance(features, Mapping):
        raise TypeError("plan features must be a mapping")
    feature = features.get(python_code)
    if feature is None:
        return {
            "configured_state": "absent",
            "is_configured": False,
            "unit": None,
            "aggregation_type": None,
            "reset_cycle": None,
            "limit": None,
        }
    if not isinstance(feature, Mapping) or "limit" not in feature:
        raise ValueError(f"configured feature {python_code!r} must include a limit")

    limit = feature["limit"]
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError(f"configured feature {python_code!r} has an invalid limit")
    if limit is None:
        state = "unlimited"
    elif limit == 0:
        state = "explicit_zero"
    else:
        state = "limited"

    return {
        "configured_state": state,
        "is_configured": True,
        "unit": feature.get("unit"),
        "aggregation_type": feature.get("aggregation_type"),
        "reset_cycle": feature.get("reset_cycle"),
        "limit": limit,
    }


def project_effective_rights(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic, informational view of an existing Python plan.

    ``plan`` is the already tenant-scoped value from ``usage.get_plan``. This
    function does not accept a tenant identifier or a database connection, so
    it cannot look up another tenant or broaden the caller's authority.
    """
    if not isinstance(plan, Mapping):
        raise TypeError("plan must be a mapping")

    rights = []
    for mapping in FEATURE_MAPPINGS:
        entry: dict[str, Any] = {
            "feature_code": mapping.feature_code,
            "python_feature_code": mapping.python_feature_code,
            "mapping_status": mapping.status,
            "configured_state": "unmapped",
            "is_configured": False,
            "unit": None,
            "aggregation_type": None,
            "reset_cycle": None,
            "limit": None,
        }
        if mapping.status == "established_python_code" or mapping.status == "python_only":
            assert mapping.python_feature_code is not None
            entry.update(_effective_python_configuration(plan, mapping.python_feature_code))
        elif mapping.status == "candidate_alias":
            assert mapping.python_feature_code is not None
            # Show the target's existing state as evidence, never as an alias grant.
            entry["candidate_python_state"] = _effective_python_configuration(
                plan, mapping.python_feature_code
            )["configured_state"]
        rights.append(entry)

    return {
        "projection_type": "informational_only",
        "plan_key": plan.get("plan_key"),
        "status": plan.get("status"),
        "assigned": plan.get("assigned"),
        "source": plan.get("source"),
        "period_code": plan.get("period_code"),
        "period_start": plan.get("period_start"),
        "period_end": plan.get("period_end"),
        "trial_ends_at": plan.get("trial_ends_at"),
        "rights": rights,
    }
