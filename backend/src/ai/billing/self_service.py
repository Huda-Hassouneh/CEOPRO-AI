"""Customer custom pricing over private, versioned billing inputs.

Only the billing-setup capability reads/writes frozen previews. No provider,
subscription, entitlement or Credit mutation belongs to this module.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from psycopg2.extras import Json

from src.ai.billing import custom_offers
from src.ai.billing.custom_plan_pricing import calculate_custom_plan_price, apply_billing_discount, CustomPlanPricingError

DEFAULTS = {
    "currency": "JOD", "targetGrossMargin": "0.35", "fixedPlatformFee": "25",
    "roundingIncrement": "1", "maxAutomaticMonthlyPrice": "2500",
    "maxAutomaticQuotaPerFeature": 500000, "featureLimits": {},
    "fxRate": "0.709", "fxSourceCurrency": "USD", "fxTargetCurrency": "JOD",
    "fxSource": "Legacy fallback approved by owner", "fxVersion": "legacy-fallback-v1",
}
TERMS = {"monthly": (1, 0), "three-months": (3, 10), "six-months": (6, 20)}
CADENCES = {"daily": (1440, 30), "every_12_hours": (720, 60), "every_6_hours": (360, 120), "hourly": (60, 720), "weekly": (10080, 4)}


def policy_values(row):
    """Stored commercial overrides win; old USD policy amounts keep their units."""
    values = dict(DEFAULTS)
    if row:
        overrides = row.get("self_service_policy") or {}
        if not isinstance(overrides, dict):
            raise CustomPlanPricingError("Self-service policy must be an object")
        if "fxRate" in overrides and Decimal(str(overrides["fxRate"])) != Decimal(DEFAULTS["fxRate"]):
            if not overrides.get("fxSource") or not overrides.get("fxVersion"):
                raise CustomPlanPricingError("An overridden FX rate requires explicit provenance and version")
        values.update({key: value for key, value in overrides.items() if value is not None})
        fx = Decimal(str(values["fxRate"]))
        for target, source in (("fixedPlatformFee", "fixed_platform_fee_usd"),
                               ("roundingIncrement", "upward_rounding_increment_usd")):
            if target not in overrides and row.get(source) is not None:
                values[target] = str(Decimal(str(row[source])) * fx)
        if "targetGrossMargin" not in overrides and row.get("target_gross_margin") is not None:
            values["targetGrossMargin"] = str(row["target_gross_margin"])
    if values["currency"] != "JOD" or values["fxSourceCurrency"] != "USD" or values["fxTargetCurrency"] != "JOD":
        raise CustomPlanPricingError("Self-service commercial currency must be JOD with USD/JOD FX")
    for key in ("targetGrossMargin", "fixedPlatformFee", "roundingIncrement", "maxAutomaticMonthlyPrice", "fxRate"):
        value = Decimal(str(values[key]))
        if not value.is_finite() or value < 0:
            raise CustomPlanPricingError("Invalid self-service pricing policy: " + key)
    if Decimal(str(values["targetGrossMargin"])) >= 1 or Decimal(str(values["fxRate"])) <= 0:
        raise CustomPlanPricingError("Invalid margin or FX rate")
    if not values["fxSource"] or not values["fxVersion"]:
        raise CustomPlanPricingError("FX provenance and version are required")
    if not isinstance(values["featureLimits"], dict):
        raise CustomPlanPricingError("Feature limits must be an object")
    for code in values["featureLimits"]:
        resolved_limit(code, values)
    return values


def resolved_limit(code, policy):
    configured = policy.get("featureLimits", {}).get(code, {})
    try:
        minimum = max(0, int(configured.get("min", 0)))
        return {"min": minimum, "max": max(minimum, int(configured.get("max", policy["maxAutomaticQuotaPerFeature"]))),
                "step": max(1, int(configured.get("step", 1)))}
    except (ValueError, TypeError, AttributeError) as exc:
        raise CustomPlanPricingError("Invalid automatic feature limit") from exc


def payment_amount(commercial, fx):
    rate = Decimal(str(fx["rate"]))
    if rate <= 0 or (fx["sourceCurrency"], fx["targetCurrency"]) != ("USD", "JOD"):
        raise CustomPlanPricingError("Unsupported payment FX pair")
    return (Decimal(str(commercial)) / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate(configuration, inputs):
    """Legacy decision order; prices and thresholds are JOD, never USD."""
    row = inputs.get("policy")
    policy = policy_values(row)
    limits = configuration["limits"]
    enabled = configuration["enabledFeatures"]
    period = configuration.get("billingPeriod", "monthly")
    if period not in TERMS:
        raise custom_offers.CustomOfferError(422, "invalid_billing_period", "Unsupported Custom billing period.")
    reasons = []
    for code, value in limits.items():
        bound = resolved_limit(code, policy)
        if value < bound["min"] or (value - bound["min"]) % bound["step"]:
            raise custom_offers.CustomOfferError(422, "invalid_quantity", "Quantity violates the configured minimum or increment.")
        if value > bound["max"]:
            reasons.append("QUOTA_ABOVE_AUTOMATIC_LIMIT:" + code)
    features = [{"feature_id": c, "feature_code": c, "limit_value": q, "estimated_usage": q}
                for c, q in limits.items()]
    for code in enabled:
        features.append({"feature_id": code, "feature_code": code, "estimated_usage": 1,
                         "configuration": ({"monitoring_frequency_minutes": CADENCES[configuration["refreshFrequency"]][0],
                                            "monitoring_checks_per_month": CADENCES[configuration["refreshFrequency"]][1]}
                                           if code == "competitor_management" else {})})
    selected = {f["feature_id"] for f in features if f["estimated_usage"] > 0}
    bindings = [b for b in inputs.get("bindings", []) if b["feature_code"] in selected]
    # Preserve KEEL's fail-closed cost mapping, including explicit zero-cost inputs.
    missing = selected - {b["feature_code"] for b in bindings}
    if missing:
        return {"pricingAvailable": False, "reviewRequired": True, "checkoutAllowed": False,
                "reasons": sorted(reasons + ["COST_MAPPING_MISSING:" + c for c in missing]), "currency": "JOD", "price": None}
    vendor, infrastructure, evidence = [], [], []
    for b in bindings:
        if b["unit_cost_usd"] is None:
            return {"pricingAvailable": False, "reviewRequired": True, "checkoutAllowed": False,
                    "reasons": sorted(set(reasons + ["UNVERIFIED_VENDOR_RATE"])), "currency": "JOD", "price": None}
        verified = bool(b["rate_id"] and str(b.get("rate_source") or "").strip()
                        and b["verified_at"] and b["cost_is_final"]
                        and b["verified_at"] <= datetime.now(timezone.utc).date().isoformat())
        rate = {"id": b["binding_id"], "feature_id": b["feature_code"], "feature": {"code": b["feature_code"]},
                "vendor": b["provider"], "service": b["operation"], "billing_unit": b["unit"],
                "unit_cost": b["unit_cost_usd"], "currency": "USD",
                "operational_multiplier": b["operational_multiplier"], "variability_reserve": b["variability_reserve"],
                "verification_status": "confirmed" if verified else "unconfirmed", "source": b["rate_source"],
                "metadata": {"usageAssumption": b["usage_assumption"] or {}}}
        if b["operational_multiplier"] is None or b["variability_reserve"] is None:
            raise CustomPlanPricingError("Cost multipliers are unconfigured")
        if b["cost_category"] == "vendor":
            if b["usage_basis"] == "limit_value":
                rate["unit_cost"] = Decimal(str(rate["unit_cost"])) * Decimal(str(b["units_per_feature_unit"]))
            vendor.append(rate)
        else:
            rate.update(cost_driver=b["operation"], usage_basis=b["usage_basis"], billing_units_per_feature_unit=b["units_per_feature_unit"])
            infrastructure.append(rate)
        evidence.append({**b, "providerScheduleId": b["rate_id"], "unitCostUsd": str(b["unit_cost_usd"]),
                         "source": b["rate_source"], "providerVerifiedAt": b["verified_at"],
                         "providerUpdatedAt": b["updated_at"]})
    result = calculate_custom_plan_price({
        "quote_currency": "JOD", "features": features, "vendor_rates": vendor, "infrastructure_rates": infrastructure,
        "vendor_cost_required_feature_ids": [r["feature_id"] for r in vendor],
        "monthly_infrastructure_cost": Decimal(str((row or {}).get("monthly_shared_infrastructure_cost_usd") or 0)) * Decimal(str(policy["fxRate"])),
        "active_paying_tenants": (row or {}).get("active_paying_tenant_count") or 1,
        "estimated_other_cost": policy.get("estimatedOtherCost", "0"), "target_gross_margin": policy["targetGrossMargin"],
        "max_vendor_cost_revenue_ratio": (row or {}).get("max_vendor_cost_revenue_ratio") or "0.2",
        "enforce_vendor_cost_ratio_floor": (row or {}).get("enforce_vendor_cost_ratio_floor") is True,
        "fixed_platform_fee": policy["fixedPlatformFee"], "rounding_increment": policy["roundingIncrement"],
        "fx_rate": policy["fxRate"], "fx_source_currency": policy["fxSourceCurrency"], "fx_target_currency": policy["fxTargetCurrency"],
    })
    if result["recommendedPrice"] > Decimal(str(policy["maxAutomaticMonthlyPrice"])):
        reasons.append("PRICE_ABOVE_AUTOMATIC_LIMIT")
    if result["warnings"]:
        reasons.append("UNVERIFIED_VENDOR_RATE")
    months, discount = TERMS[period]
    commercial = apply_billing_discount(result["recommendedPrice"], months, discount)
    fx = {"rate": str(policy["fxRate"]), "sourceCurrency": "USD", "targetCurrency": "JOD",
          "source": policy["fxSource"], "version": policy["fxVersion"]}
    payment = payment_amount(commercial, fx)
    snapshot = json.loads(json.dumps({"version": 2, "pricingStatus": "calculated", "currency": "JOD",
        "pricingPolicyVersionId": str(row["policy_version_id"]) if row else "legacy-fallback-v1",
        "policy": policy, "configuration": configuration, "rates": evidence, "calculation": result,
        "reviewDecision": {"required": bool(reasons), "reasons": list(dict.fromkeys(reasons))},
        "commercial": {"amount": commercial, "currency": "JOD", "monthlyAmount": result["recommendedPrice"],
                       "months": months, "period": period, "discountPercent": discount},
        "payment": {"amount": payment, "currency": "USD"}, "fx": fx}, default=str))
    snapshot["calculationHash"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"pricingAvailable": True, "valid": True, "currency": "JOD", "monthlyPrice": str(result["recommendedPrice"]),
            "price": str(commercial), "months": months, "discountPercent": discount,
            "paymentAmount": str(payment), "paymentCurrency": "USD",
            "reviewRequired": bool(reasons), "reasons": list(dict.fromkeys(reasons)), "checkoutAllowed": not reasons,
            "pricingSnapshot": snapshot}


def command(conn, action, payload=None):
    import psycopg2
    try:
        with conn.cursor() as cur:
            # Decode NUMERIC through Decimal, never psycopg's default JSON float.
            cur.execute("SELECT public.billing_custom_self_service(%s,%s::jsonb)::text", (action, Json(payload or {})))
            return json.loads(cur.fetchone()[0], parse_float=Decimal)
    except psycopg2.Error as exc:
        status, code = {"42501": (403, "billing_role_required"), "P0002": (404, "preview_not_found"),
                        "55000": (409, "preview_not_checkoutable"), "23505": (409, "preview_conflict"),
                        "22023": (422, "invalid_configuration")}.get(exc.pgcode, (None, None))
        if status is None:
            raise
        raise custom_offers.CustomOfferError(status, code, "The Custom pricing request is no longer eligible. Refresh or request review.") from None


def preview(conn, configuration, key):
    result = calculate(configuration, command(conn, "inputs"))
    snapshot = result.pop("pricingSnapshot", None)
    if snapshot:
        frozen = command(conn, "freeze", {"snapshot": snapshot, "idempotency_key": key})
        result["previewId"] = frozen["quote_id"]
    return result


def checkout_terms(terms):
    """Validate the frozen provider amount without repricing an existing quote."""
    if terms.get("currency") == "USD":
        return Decimal(str(terms["monthlyPriceUsd"])), 1, "monthly"
    if terms.get("currency") != "JOD" or terms.get("paymentCurrency") != "USD":
        raise CustomPlanPricingError("Unsupported Custom terms")
    amount = Decimal(str(terms["paymentAmountUsd"]))
    if amount != payment_amount(terms["amount"], terms["fx"]):
        raise CustomPlanPricingError("Frozen payment amount does not match FX evidence")
    period = terms["periodCode"]
    months = int(terms["billingPeriodMonths"])
    if period not in TERMS or months != TERMS[period][0]:
        raise CustomPlanPricingError("Unsupported Custom interval")
    return amount, months, period
