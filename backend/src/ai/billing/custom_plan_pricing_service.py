"""Database-backed, fail-closed Custom Plan price preview.

Financial policy is loaded only from an explicitly active, versioned owner policy.
Provider prices come from Python's provider_cost_schedules; this service never
accepts client-supplied cost, FX, margin or final-price values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from src.ai.billing.custom_plan_pricing import (
    CustomPlanPricingError, calculate_custom_plan_price,
)


class CustomPricingUnavailable(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = sorted(set(reasons))
        super().__init__("Custom pricing requires owner-configured verified inputs.")


def active_policy(conn, as_of: datetime | None = None) -> dict | None:
    as_of = as_of or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT policy_version_id, version_number, quote_currency, target_gross_margin,
                   enforce_vendor_cost_ratio_floor, max_vendor_cost_revenue_ratio,
                   fixed_platform_fee_usd, upward_rounding_increment_usd,
                   monthly_shared_infrastructure_cost_usd, active_paying_tenant_count,
                   custom_term_discount_percent, effective_from, effective_to
              FROM public.billing_custom_pricing_policies
             WHERE status='active' AND effective_from <= %s
               AND (effective_to IS NULL OR effective_to > %s)
             ORDER BY version_number DESC LIMIT 1
        """, (as_of, as_of))
        row = cur.fetchone()
    if not row:
        return None
    names = ("policy_version_id", "version_number", "quote_currency", "target_gross_margin",
             "enforce_vendor_cost_ratio_floor", "max_vendor_cost_revenue_ratio",
             "fixed_platform_fee_usd", "upward_rounding_increment_usd",
             "monthly_shared_infrastructure_cost_usd", "active_paying_tenant_count",
             "custom_term_discount_percent", "effective_from", "effective_to")
    return dict(zip(names, row))


def _unconfigured_policy_fields(policy: dict) -> list[str]:
    required = ("target_gross_margin", "enforce_vendor_cost_ratio_floor", "fixed_platform_fee_usd",
                "upward_rounding_increment_usd", "monthly_shared_infrastructure_cost_usd",
                )
    missing = [name for name in required if policy.get(name) is None]
    if policy.get("enforce_vendor_cost_ratio_floor") is True and policy.get("max_vendor_cost_revenue_ratio") is None:
        missing.append("max_vendor_cost_revenue_ratio")
    if policy.get("monthly_shared_infrastructure_cost_usd") not in (None, Decimal("0")) and policy.get("active_paying_tenant_count") is None:
        missing.append("active_paying_tenant_count")
    return ["pricing_policy." + key for key in missing]


def _load_bindings(conn, policy_id, feature_codes: list[str], as_of: datetime) -> list[dict]:
    if not feature_codes:
        return []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT b.binding_id, b.feature_code, b.cost_category, b.budget_kind,
                   b.provider, b.operation, b.unit, b.usage_basis,
                   b.units_per_feature_unit, b.operational_multiplier, b.variability_reserve,
                   b.required_for_price, b.effective_from, b.effective_to, b.source,
                   b.usage_assumption,
                   COALESCE(cr.cost_rate_id,p.schedule_id) AS rate_id,
                   COALESCE(cr.unit_cost_usd,p.unit_cost_usd) AS unit_cost_usd,
                   p.safety_margin, COALESCE(cr.cost_rate_id IS NOT NULL,p.cost_is_final) AS cost_is_final,
                   COALESCE(cr.source,p.source) AS rate_source,
                   COALESCE(cr.verified_at,p.verified_at) AS verified_at,
                   COALESCE(cr.created_at,p.updated_at) AS updated_at
              FROM public.billing_custom_cost_bindings b
              LEFT JOIN public.billing_custom_cost_rates cr ON cr.cost_rate_id=b.cost_rate_id
               AND cr.effective_from <= %s AND (cr.effective_to IS NULL OR cr.effective_to > %s)
              LEFT JOIN public.provider_cost_schedules p
                ON b.cost_rate_id IS NULL AND p.budget_kind=b.budget_kind AND p.provider=b.provider
               AND p.operation=b.operation AND p.unit=b.unit
               AND p.updated_at <= %s
             WHERE b.policy_version_id=%s AND b.feature_code=ANY(%s)
               AND b.effective_from <= %s AND (b.effective_to IS NULL OR b.effective_to > %s)
             ORDER BY b.feature_code,b.cost_category,b.binding_id
        """, (as_of, as_of, as_of, policy_id, feature_codes, as_of, as_of))
        rows = cur.fetchall()
    names = ("binding_id", "feature_code", "cost_category", "budget_kind", "provider", "operation", "unit",
             "usage_basis", "units_per_feature_unit", "operational_multiplier", "variability_reserve",
             "required_for_price", "effective_from", "effective_to", "binding_source", "usage_assumption",
        "schedule_id", "unit_cost_usd", "safety_margin", "cost_is_final", "rate_source", "verified_at", "updated_at")
    return [dict(zip(names, row)) for row in rows]


def calculate_preview(conn, *, limits: dict, refresh_frequency: str | None,
                      enabled_features: list[str] | None = None,
                      as_of: datetime | None = None) -> dict:
    """Return public preview status; details expose no vendor costs or margins."""
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        raise CustomPlanPricingError("quote timestamp must be timezone-aware")
    from src.ai.billing import custom_offers
    validated = custom_offers.validate_configuration(
        conn, limits=limits, enabled_features=enabled_features or [], refresh_frequency=refresh_frequency)
    quantities = {code: value for code, value in validated["configuration"]["limits"].items() if value > 0}
    included = list(validated["configuration"]["enabledFeatures"])
    selected = {**quantities, **{code: 1 for code in included}}
    policy = active_policy(conn, as_of)
    if policy is None:
        return {"pricingAvailable": False, "pricingStatus": "configuration_required",
                "reviewRequired": True, "reasons": ["active_pricing_policy_missing"],
                "currency": "USD", "price": None}
    reasons = _unconfigured_policy_fields(policy)
    if policy["quote_currency"] != "USD":
        reasons.append("unsupported_quote_currency")
    if policy["custom_term_discount_percent"] != Decimal("0"):
        reasons.append("custom_term_discount_requires_separate_approval")
    bindings = _load_bindings(conn, policy["policy_version_id"], list(selected), as_of)
    by_feature: dict[str, list[dict]] = {code: [] for code in selected}
    for binding in bindings:
        by_feature[binding["feature_code"]].append(binding)
    for code, rows in by_feature.items():
        if not rows:
            reasons.append("cost_mapping_missing:" + code)
    vendor_rates, infra_rates, source_snapshot = [], [], []
    feature_rows = []
    frequency_minutes = {"hourly": 60, "daily": 1440, "weekly": 10080}.get(refresh_frequency)
    for code, quantity in quantities.items():
        feature_rows.append({"feature_id": code, "feature_code": code, "limit_value": quantity,
                             "estimated_usage": quantity})
    for code in included:
        feature_rows.append({"feature_id": code, "feature_code": code, "limit_value": 1,
                             "estimated_usage": 1,
                             "configuration": ({"monitoring_frequency_minutes": frequency_minutes}
                                               if code == "competitor_management" and frequency_minutes else {})})
    # Monitoring is driven by the configured number of tracked competitors.
    if "competitor_management" in included:
        if "tracked_competitors" not in quantities:
            reasons.append("tracked_competitor_allowance_required")
        else:
            tracked = next(row for row in feature_rows if row["feature_code"] == "tracked_competitors")
            tracked["limit_value"] = quantities["tracked_competitors"]
    for b in bindings:
        ident = str(b["binding_id"])
        verified = (b["schedule_id"] is not None and b["unit_cost_usd"] is not None
                    and b["cost_is_final"] is True and b["verified_at"] is not None
                    and b["verified_at"] <= as_of.date())
        if not verified:
            if b["required_for_price"]:
                reasons.append("provider_cost_unverified:" + str(b["provider"]) + "/" + str(b["operation"]) + "/" + str(b["unit"]))
            continue
        if b["operational_multiplier"] is None or b["variability_reserve"] is None:
            reasons.append("cost_policy_unconfigured:" + ident)
            continue
        if b["rate_source"] is None or not str(b["rate_source"]).strip():
            reasons.append("cost_provenance_missing:" + ident)
            continue
        base = {"id": ident, "feature_id": b["feature_code"], "feature": {"code": b["feature_code"]},
                "vendor": b["provider"], "service": b["operation"], "billing_unit": b["unit"],
                "unit_cost": b["unit_cost_usd"], "currency": "USD",
                "operational_multiplier": b["operational_multiplier"],
                "variability_reserve": b["variability_reserve"], "verification_status": "confirmed",
                "source": b["rate_source"], "effective_from": b["effective_from"], "effective_to": b["effective_to"],
                "metadata": {"usageAssumption": b["usage_assumption"] or {}}}
        source_snapshot.append({"bindingId": ident, "providerScheduleId": str(b["schedule_id"]),
                                "featureCode": b["feature_code"], "category": b["cost_category"],
                                "provider": b["provider"], "operation": b["operation"], "unit": b["unit"],
                                "unitCostUsd": str(b["unit_cost_usd"]), "providerVerifiedAt": b["verified_at"].isoformat(),
                                "providerUpdatedAt": b["updated_at"].isoformat(), "source": b["rate_source"], "bindingSource": b["binding_source"],
                                "unitsPerFeatureUnit": str(b["units_per_feature_unit"]),
                                "operationalMultiplier": str(b["operational_multiplier"]),
                                "variabilityReserve": str(b["variability_reserve"])})
        target = vendor_rates if b["cost_category"] == "vendor" else infra_rates
        if b["cost_category"] == "vendor":
            if b["usage_basis"] == "limit_value":
                base["unit_cost"] = Decimal(str(b["unit_cost_usd"])) * Decimal(str(b["units_per_feature_unit"]))
            if b["feature_code"] == "competitor_management":
                base["metadata"]["usageAssumption"] = b["usage_assumption"] or {}
            target.append(base)
        else:
            base.update({"cost_driver": b["operation"], "usage_basis": b["usage_basis"],
                         "billing_units_per_feature_unit": b["units_per_feature_unit"]})
            target.append(base)
    if reasons:
        return {"pricingAvailable": False, "pricingStatus": "manual_review_required",
                "reviewRequired": True, "reasons": sorted(set(reasons)), "currency": "USD", "price": None}
    try:
        result = calculate_custom_plan_price({
            "quote_currency": "USD", "features": feature_rows, "vendor_rates": vendor_rates,
            "infrastructure_rates": infra_rates,
            "monthly_infrastructure_cost": policy["monthly_shared_infrastructure_cost_usd"],
            "active_paying_tenants": policy["active_paying_tenant_count"] or 1,
            "estimated_other_cost": Decimal("0"),
            "target_gross_margin": policy["target_gross_margin"],
            "max_vendor_cost_revenue_ratio": policy["max_vendor_cost_revenue_ratio"],
            "enforce_vendor_cost_ratio_floor": policy["enforce_vendor_cost_ratio_floor"],
            "fixed_platform_fee": policy["fixed_platform_fee_usd"],
            "rounding_increment": policy["upward_rounding_increment_usd"],
        })
    except CustomPlanPricingError as exc:
        return {"pricingAvailable": False, "pricingStatus": "manual_review_required",
                "reviewRequired": True, "reasons": ["calculation_rejected"], "currency": "USD", "price": None}
    if result["recommendedPrice"] <= 0:
        return {"pricingAvailable": False, "pricingStatus": "manual_review_required",
                "reviewRequired": True, "reasons": ["non_positive_checkout_price"], "currency": "USD", "price": None}
    snapshot_data = {"pricingStatus": "calculated", "policyVersionId": str(policy["policy_version_id"]), "policyVersion": int(policy["version_number"]),
                     "quotedAt": as_of.astimezone(timezone.utc).isoformat(), "currency": "USD",
                     "configuration": validated["configuration"], "featureQuantities": quantities,
                     "enabledFeatures": included,
                     "rates": source_snapshot, "calculation": _snapshot_value(result)}
    canonical = json.dumps(snapshot_data, sort_keys=True, separators=(",", ":"), default=str)
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    snapshot_data["pricingPolicyVersionId"] = str(policy["policy_version_id"])
    snapshot_data["calculationHash"] = snapshot_hash
    # Manual approval is mandatory even when the indicative calculation is available.
    return {"pricingAvailable": True, "pricingStatus": "indicative", "reviewRequired": True,
            "policyVersion": int(policy["version_number"]), "currency": "USD",
            "monthlyPrice": str(result["recommendedPrice"]), "billingTermDiscountPercent": "0",
            "calculationHash": snapshot_hash, "pricingSnapshot": snapshot_data}


def _snapshot_value(value):
    """Canonical JSON-compatible representation of every calculator output."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
