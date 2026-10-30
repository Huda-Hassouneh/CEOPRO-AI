"""Decimal port of Node's feature-based Custom Plan cost calculation.

This module is deliberately pure: callers must supply versioned, approved
policy and cost inputs. It does not fetch rates, choose defaults for missing
business policy, persist a quote, contact Stripe, or grant rights.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
MINUTES_PER_PRICING_MONTH = Decimal(30 * 24 * 60)


class CustomPlanPricingError(ValueError):
    """A source-backed input/rate/policy error from the Node pricing contract."""


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CustomPlanPricingError(f"{name} must be a finite decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CustomPlanPricingError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise CustomPlanPricingError(f"{name} must be a finite decimal")
    return result


def _field(row: dict, snake: str, camel: str | None = None, default=None):
    if snake in row:
        return row[snake]
    if camel and camel in row:
        return row[camel]
    return default


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _convert_rate(rate: dict, args: dict) -> Decimal:
    unit_cost = _decimal(_field(rate, "unit_cost", "unitCost"), "unit cost")
    source = str(_field(rate, "currency", default="")).upper()
    target = str(_field(args, "quote_currency", "quoteCurrency", "")).upper()
    if source == target:
        return unit_cost
    fx_rate = _field(args, "fx_rate", "fxRate")
    fx_source = _field(args, "fx_source_currency", "fxSourceCurrency")
    fx_target = _field(args, "fx_target_currency", "fxTargetCurrency")
    if fx_rate is None or str(fx_source or "").upper() != source or str(fx_target or "").upper() != target:
        vendor = _field(rate, "vendor", default="internal")
        service = _field(rate, "service", default=_field(rate, "cost_driver", "costDriver", "unknown"))
        raise CustomPlanPricingError(f"Missing FX rate for {source} -> {target} ({vendor}/{service})")
    return unit_cost * _decimal(fx_rate, "fx rate")


def _resolve_vendor_usage(rate: dict, args: dict, fallback: Decimal, features: list[dict]) -> tuple[Decimal, dict | None]:
    feature = _field(rate, "feature", default={}) or {}
    code = _field(feature, "code")
    feature_id = _field(rate, "feature_id", "featureId")
    if code != "competitor_management":
        return fallback, None
    monitoring = next((f for f in features if _field(f, "feature_id", "featureId") == feature_id), None)
    cfg = (_field(monitoring or {}, "configuration") or {})
    frequency = _field(cfg, "monitoring_frequency_minutes", "monitoringFrequencyMinutes")
    if frequency is None:
        return fallback, None
    if isinstance(frequency, bool) or not isinstance(frequency, int) or frequency <= 0:
        raise CustomPlanPricingError("Invalid competitor monitoring frequency")
    capacity = next((f for f in features if _field(f, "feature_code", "featureCode") == "tracked_competitors"), None)
    competitor_count = _decimal(_field(capacity or {}, "limit_value", "limitValue", _field(capacity or {}, "estimated_usage", "estimatedUsage", 0)), "competitor count")
    if competitor_count <= 0:
        raise CustomPlanPricingError("tracked_competitors must be selected with a positive limit when competitor monitoring is configured")
    metadata = _field(rate, "metadata") or {}
    assumption = metadata.get("usageAssumption", metadata.get("usage_assumption", {})) or {}
    if assumption.get("model") != "competitor_monitoring" or assumption.get("unitsPerCompetitorCheck", assumption.get("units_per_competitor_check")) is None:
        raise CustomPlanPricingError(f"Missing competitor-monitoring usage assumption on vendor rate {_field(rate, 'id', default='unknown')}")
    units_per_check = _decimal(assumption.get("unitsPerCompetitorCheck", assumption.get("units_per_competitor_check")), "units per competitor check")
    if units_per_check <= 0:
        raise CustomPlanPricingError("Invalid competitor-monitoring usage assumption")
    configured_runs = _field(cfg, "monitoring_checks_per_month", "monitoringChecksPerMonth")
    runs = MINUTES_PER_PRICING_MONTH / Decimal(frequency) if configured_runs is None else _decimal(configured_runs, "monitoring checks per month")
    if runs <= 0:
        raise CustomPlanPricingError("Invalid competitor monitoring checks per month")
    return competitor_count * runs * units_per_check, {
        "model": "competitor_monitoring",
        "competitorCount": str(competitor_count),
        "monitoringFrequencyMinutes": frequency,
        "monitoringRunsPerMonth": str(runs),
        "unitsPerCompetitorCheck": str(units_per_check),
    }


def _round_up(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return _money(value)
    return _money((value / increment).to_integral_value(rounding=ROUND_CEILING) * increment)


def calculate_custom_plan_price(args: dict) -> dict:
    """Mirror ``calculateCustomPlanPrice`` using only explicit caller inputs.

    Input dictionaries accept the Node camelCase contract and Python snake_case
    equivalents. Monetary results are returned as ``Decimal`` values so callers
    cannot accidentally introduce binary floating-point rounding.
    """
    paying_tenants = _field(args, "active_paying_tenants", "activePayingTenants")
    if isinstance(paying_tenants, bool) or not isinstance(paying_tenants, int) or paying_tenants <= 0:
        raise CustomPlanPricingError("activePayingTenants must be a positive integer")
    margin = _decimal(_field(args, "target_gross_margin", "targetGrossMargin"), "target gross margin")
    if margin < 0 or margin >= 1:
        raise CustomPlanPricingError("Invalid targetGrossMargin")
    enforce_ratio = _field(args, "enforce_vendor_cost_ratio_floor", "enforceVendorCostRatioFloor", False) is True
    max_ratio_raw = _field(args, "max_vendor_cost_revenue_ratio", "maxVendorCostRevenueRatio")
    max_ratio = None if max_ratio_raw is None else _decimal(max_ratio_raw, "max vendor cost revenue ratio")
    if max_ratio is not None and (max_ratio <= 0 or max_ratio > 1):
        raise CustomPlanPricingError("Invalid maxVendorCostRevenueRatio")
    if enforce_ratio and max_ratio is None:
        raise CustomPlanPricingError("maxVendorCostRevenueRatio is required when vendor-cost floor enforcement is enabled")
    fee = _decimal(_field(args, "fixed_platform_fee", "fixedPlatformFee", 0), "fixed platform fee")
    increment = _decimal(_field(args, "rounding_increment", "roundingIncrement", 0), "rounding increment")
    if fee < 0 or increment < 0:
        raise CustomPlanPricingError("Pricing policy amounts cannot be negative")

    features = list(_field(args, "features", default=[]))
    usage_by_id = {}
    feature_by_id = {}
    for feature in features:
        fid = _field(feature, "feature_id", "featureId")
        amount = _decimal(_field(feature, "estimated_usage", "estimatedUsage"), "estimated usage")
        if amount < 0:
            raise CustomPlanPricingError(f"Estimated usage cannot be negative ({fid})")
        usage_by_id[fid] = amount
        feature_by_id[fid] = feature

    vendor_rates = list(_field(args, "vendor_rates", "vendorRates", []))
    priced = { _field(rate, "feature_id", "featureId") for rate in vendor_rates
              if _field(rate, "feature_id", "featureId") and _field(rate, "verification_status", "verificationStatus") != "deprecated" }
    required_raw = _field(args, "vendor_cost_required_feature_ids", "vendorCostRequiredFeatureIds")
    required = None if required_raw is None else set(required_raw)
    missing = [fid for fid, amount in usage_by_id.items() if amount > 0 and (required is None or fid in required) and fid not in priced]
    if missing:
        raise CustomPlanPricingError(f"Missing vendor rate for feature(s): {', '.join(missing)}")

    quote_currency = str(_field(args, "quote_currency", "quoteCurrency", "")).upper()
    vendor_cost = ZERO
    vendor_breakdown = []
    for rate in vendor_rates:
        fid = _field(rate, "feature_id", "featureId")
        if not fid or _field(rate, "verification_status", "verificationStatus") == "deprecated":
            continue
        fallback = usage_by_id.get(fid, ZERO)
        if fallback <= 0:
            continue
        units, calculation = _resolve_vendor_usage(rate, args, fallback, features)
        unit_cost = _convert_rate(rate, args)
        operational = _decimal(_field(rate, "operational_multiplier", "operationalMultiplier"), "operational multiplier")
        reserve = _decimal(_field(rate, "variability_reserve", "variabilityReserve"), "variability reserve")
        if operational <= 0 or reserve < 1:
            raise CustomPlanPricingError(f"Invalid multiplier on vendor rate {_field(rate, 'id', default='unknown')}")
        cost = units * unit_cost * operational * reserve
        vendor_cost += cost
        vendor_breakdown.append({
            "rateId": _field(rate, "id"), "featureId": fid,
            "vendor": _field(rate, "vendor"), "service": _field(rate, "service"),
            "billingUnit": _field(rate, "billing_unit", "billingUnit"),
            "verificationStatus": _field(rate, "verification_status", "verificationStatus"),
            "source": _field(rate, "source"), "estimatedUsage": str(units),
            "sourceUnitCost": str(_decimal(_field(rate, "unit_cost", "unitCost"), "unit cost")),
            "sourceCurrency": _field(rate, "currency"), "quoteCurrency": quote_currency,
            "normalizedUnitCost": str(unit_cost),
            "operationalMultiplier": str(operational), "variabilityReserve": str(reserve),
            "cost": _money(cost), "usageCalculation": calculation,
            "effectiveFrom": _field(rate, "effective_from", "effectiveFrom"),
            "effectiveTo": _field(rate, "effective_to", "effectiveTo"),
        })

    monthly_infra = _decimal(_field(args, "monthly_infrastructure_cost", "monthlyInfrastructureCost"), "monthly infrastructure cost")
    other_cost = _decimal(_field(args, "estimated_other_cost", "estimatedOtherCost"), "estimated other cost")
    if monthly_infra < 0 or other_cost < 0:
        raise CustomPlanPricingError("Cost inputs cannot be negative")

    infra_cost = ZERO
    infra_breakdown = []
    selected = set()
    for rate in _field(args, "infrastructure_rates", "infrastructureRates", []) or []:
        fid = _field(rate, "feature_id", "featureId")
        if not fid or _field(rate, "verification_status", "verificationStatus") == "deprecated" or fid not in feature_by_id:
            continue
        driver = _field(rate, "cost_driver", "costDriver")
        selection = (fid, driver)
        if selection in selected:
            continue
        selected.add(selection)
        feature = feature_by_id[fid]
        basis = _field(rate, "usage_basis", "usageBasis")
        if basis == "enabled_feature":
            quantity = ONE
        elif basis == "limit_value":
            raw = _field(feature, "limit_value", "limitValue")
            if raw is None:
                raise CustomPlanPricingError(f"Infrastructure rate {_field(rate, 'id')} requires a configured feature limit")
            quantity = _decimal(raw, "feature limit")
        else:
            quantity = _decimal(_field(feature, "estimated_usage", "estimatedUsage"), "estimated usage")
        if quantity < 0:
            raise CustomPlanPricingError(f"Invalid infrastructure quantity for {_field(rate, 'id')}")
        conversion = _decimal(_field(rate, "billing_units_per_feature_unit", "billingUnitsPerFeatureUnit"), "billing units per feature unit")
        operational = _decimal(_field(rate, "operational_multiplier", "operationalMultiplier"), "operational multiplier")
        reserve = _decimal(_field(rate, "variability_reserve", "variabilityReserve"), "variability reserve")
        if conversion <= 0 or operational <= 0 or reserve < 1:
            raise CustomPlanPricingError(f"Invalid multiplier or conversion factor on infrastructure rate {_field(rate, 'id')}")
        billable = quantity * conversion
        unit_cost = _convert_rate(rate, args)
        cost = billable * unit_cost * operational * reserve
        infra_cost += cost
        infra_breakdown.append({
            "rateId": _field(rate, "id"), "featureId": fid,
            "featureCode": _field(rate, "feature_code", "featureCode", _field(feature, "feature_code", "featureCode")),
            "costDriver": driver, "usageBasis": basis,
            "originalFeatureQuantity": str(quantity), "normalizedBillableQuantity": str(billable),
            "billingUnit": _field(rate, "billing_unit", "billingUnit"),
            "billingUnitsPerFeatureUnit": str(conversion),
            "sourceUnitCost": str(_decimal(_field(rate, "unit_cost", "unitCost"), "unit cost")),
            "sourceCurrency": _field(rate, "currency"), "quoteCurrency": quote_currency,
            "normalizedUnitCost": str(unit_cost), "operationalMultiplier": str(operational),
            "variabilityReserve": str(reserve),
            "verificationStatus": _field(rate, "verification_status", "verificationStatus"),
            "source": _field(rate, "source"), "cost": _money(cost),
            "effectiveFrom": _field(rate, "effective_from", "effectiveFrom"),
            "effectiveTo": _field(rate, "effective_to", "effectiveTo"),
        })

    base_infra = monthly_infra / Decimal(paying_tenants)
    estimated_infra = base_infra + infra_cost
    total_cost = vendor_cost + estimated_infra + other_cost
    margin_floor = total_cost / (ONE - margin)
    ratio_floor = vendor_cost / max_ratio if max_ratio is not None else ZERO
    safe_price = max(ratio_floor, margin_floor) if enforce_ratio else margin_floor
    pre_round = safe_price + fee
    recommended = _round_up(pre_round, increment)
    warnings = [f"{item['vendor']}/{item['service']} rate is {item['verificationStatus']}"
                for item in vendor_breakdown + infra_breakdown
                if item["verificationStatus"] != "confirmed"]
    return {
        "estimatedVendorCost": _money(vendor_cost),
        "estimatedInfrastructureCost": _money(estimated_infra),
        "estimatedOtherCost": _money(other_cost), "estimatedTotalCost": _money(total_cost),
        "grossMarginFloor": _money(margin_floor), "vendorCostRatioFloor": _money(ratio_floor),
        "minimumSafePrice": _money(safe_price), "fixedPlatformFee": _money(fee),
        "recommendedPriceBeforeRounding": _money(pre_round), "recommendedPrice": recommended,
        "targetGrossMargin": margin, "maxVendorCostRevenueRatio": max_ratio,
        "enforceVendorCostRatioFloor": enforce_ratio, "vendorBreakdown": vendor_breakdown,
        "infrastructureBreakdown": infra_breakdown, "baseInfrastructureCost": _money(base_infra),
        "usageDrivenInfrastructureCost": _money(infra_cost), "warnings": warnings,
    }


def calculate_expected_profitability(final_price: Any, total_cost: Any, vendor_cost: Any) -> dict:
    price = _decimal(final_price, "final price")
    if price <= 0:
        raise CustomPlanPricingError("finalPrice must be greater than zero")
    total = _decimal(total_cost, "estimated total cost")
    vendor = _decimal(vendor_cost, "estimated vendor cost")
    return {"expectedGrossMargin": ONE - total / price, "expectedVendorCostRatio": vendor / price}


def apply_billing_discount(monthly_price: Any, months: int, discount_percent: Any) -> Decimal:
    """Node configurator's billing-total formula, rounded to 2 decimals."""
    if isinstance(months, bool) or not isinstance(months, int) or months < 1:
        raise CustomPlanPricingError("months must be a positive integer")
    discount = _decimal(discount_percent, "discount percent")
    if discount < 0 or discount > 100:
        raise CustomPlanPricingError("discount percent must be between 0 and 100")
    return ( _decimal(monthly_price, "monthly price") * Decimal(months) * (ONE - discount / Decimal(100)) ).quantize(CENT, rounding=ROUND_HALF_UP)
