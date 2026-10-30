from decimal import Decimal
import unittest

from src.ai.billing.custom_plan_pricing import (
    CustomPlanPricingError,
    apply_billing_discount,
    calculate_custom_plan_price,
)


class CustomPlanPricingParityTests(unittest.TestCase):
    def test_cost_margin_fee_and_round_up_order_matches_node_formula(self):
        result = calculate_custom_plan_price({
            "quoteCurrency": "USD",
            "features": [{"featureId": "f1", "featureCode": "feature_a", "limitValue": 10, "estimatedUsage": 10}],
            "vendorRates": [{"id": "r1", "featureId": "f1", "vendor": "v", "service": "s", "billingUnit": "unit",
                             "unitCost": "0.10", "currency": "USD", "operationalMultiplier": "1.2",
                             "variabilityReserve": "1.1", "verificationStatus": "confirmed"}],
            "monthlyInfrastructureCost": "30", "activePayingTenants": 3, "estimatedOtherCost": "2",
            "targetGrossMargin": "0.2", "fixedPlatformFee": "1", "roundingIncrement": "5",
        })
        self.assertEqual(result["estimatedVendorCost"], Decimal("1.32"))
        self.assertEqual(result["baseInfrastructureCost"], Decimal("10.00"))
        self.assertEqual(result["estimatedTotalCost"], Decimal("13.32"))
        self.assertEqual(result["grossMarginFloor"], Decimal("16.65"))
        self.assertEqual(result["recommendedPriceBeforeRounding"], Decimal("17.65"))
        self.assertEqual(result["recommendedPrice"], Decimal("20.00"))

    def test_competitor_cadence_multiplies_competitors_runs_and_units(self):
        result = calculate_custom_plan_price({
            "quoteCurrency": "USD",
            "features": [
                {"featureId": "monitor", "featureCode": "competitor_management", "estimatedUsage": 1,
                 "configuration": {"monitoringFrequencyMinutes": 1440, "monitoringChecksPerMonth": 30}},
                {"featureId": "capacity", "featureCode": "tracked_competitors", "limitValue": 2, "estimatedUsage": 2},
            ],
            "vendorRates": [{"id": "r1", "featureId": "monitor", "vendor": "v", "service": "scrape", "billingUnit": "request",
                             "unitCost": "0.02", "currency": "USD", "operationalMultiplier": "1",
                             "variabilityReserve": "1", "verificationStatus": "confirmed",
                             "metadata": {"usageAssumption": {"model": "competitor_monitoring", "unitsPerCompetitorCheck": "0.5"}},
                             "feature": {"code": "competitor_management"}}],
            "monthlyInfrastructureCost": 0, "activePayingTenants": 1, "estimatedOtherCost": 0,
            "targetGrossMargin": "0.2", "vendorCostRequiredFeatureIds": ["monitor"],
        })
        self.assertEqual(result["vendorBreakdown"][0]["estimatedUsage"], "30.0")
        self.assertEqual(result["estimatedVendorCost"], Decimal("0.60"))

    def test_infrastructure_allocation_and_vendor_ratio_floor(self):
        result = calculate_custom_plan_price({
            "quoteCurrency": "USD",
            "features": [{"featureId": "f", "featureCode": "feature_a", "limitValue": 100, "estimatedUsage": 100}],
            "vendorRates": [{"id": "v1", "featureId": "f", "vendor": "v", "service": "s", "billingUnit": "unit",
                             "unitCost": "0.5", "currency": "USD", "operationalMultiplier": 1,
                             "variabilityReserve": 1, "verificationStatus": "confirmed"}],
            "infrastructureRates": [
                {"id": "i1", "featureId": "f", "costDriver": "storage", "usageBasis": "limit_value",
                 "billingUnit": "GB", "billingUnitsPerFeatureUnit": "0.1", "unitCost": "2",
                 "currency": "USD", "operationalMultiplier": 1, "variabilityReserve": 1,
                 "verificationStatus": "confirmed"},
                # Node selects only the first rate for a feature/cost-driver pair.
                {"id": "i2", "featureId": "f", "costDriver": "storage", "usageBasis": "limit_value",
                 "billingUnit": "GB", "billingUnitsPerFeatureUnit": "1", "unitCost": "99",
                 "currency": "USD", "operationalMultiplier": 1, "variabilityReserve": 1,
                 "verificationStatus": "confirmed"},
            ],
            "monthlyInfrastructureCost": "30", "activePayingTenants": 3, "estimatedOtherCost": 0,
            "targetGrossMargin": "0.2", "maxVendorCostRevenueRatio": "0.1",
            "enforceVendorCostRatioFloor": True, "fixedPlatformFee": "3", "roundingIncrement": "10",
        })
        # Vendor cost 50; feature-driven infrastructure 20; shared base 10.
        # Total 80 -> margin floor 100; vendor ratio floor 500; fee then up-round -> 510.
        self.assertEqual(result["estimatedInfrastructureCost"], Decimal("30.00"))
        self.assertEqual(result["estimatedTotalCost"], Decimal("80.00"))
        self.assertEqual(result["grossMarginFloor"], Decimal("100.00"))
        self.assertEqual(result["vendorCostRatioFloor"], Decimal("500.00"))
        self.assertEqual(result["recommendedPrice"], Decimal("510.00"))
        self.assertEqual(len(result["infrastructureBreakdown"]), 1)

    def test_fx_conversion_and_unconfirmed_rate_warning(self):
        result = calculate_custom_plan_price({
            "quoteCurrency": "JOD", "features": [{"featureId": "f", "estimatedUsage": 1}],
            "vendorRates": [{"id": "r", "featureId": "f", "vendor": "v", "service": "s", "billingUnit": "unit",
                             "unitCost": "1", "currency": "USD", "operationalMultiplier": 1,
                             "variabilityReserve": 1, "verificationStatus": "estimated"}],
            "monthlyInfrastructureCost": 0, "activePayingTenants": 1, "estimatedOtherCost": 0,
            "targetGrossMargin": "0.2", "fxRate": "0.709", "fxSourceCurrency": "USD", "fxTargetCurrency": "JOD",
        })
        self.assertEqual(result["estimatedVendorCost"], Decimal("0.71"))
        self.assertEqual(result["recommendedPrice"], Decimal("0.89"))
        self.assertEqual(result["warnings"], ["v/s rate is estimated"])

    def test_missing_rate_and_fx_fail_closed(self):
        base = {"quoteCurrency": "JOD", "features": [{"featureId": "f", "estimatedUsage": 1}],
                "vendorRates": [], "monthlyInfrastructureCost": 0, "activePayingTenants": 1,
                "estimatedOtherCost": 0, "targetGrossMargin": "0.2"}
        with self.assertRaisesRegex(CustomPlanPricingError, "Missing vendor rate"):
            calculate_custom_plan_price(base)
        base["vendorRates"] = [{"id": "r", "featureId": "f", "vendor": "v", "service": "s",
                                "billingUnit": "unit", "unitCost": 1, "currency": "USD",
                                "operationalMultiplier": 1, "variabilityReserve": 1,
                                "verificationStatus": "confirmed"}]
        with self.assertRaisesRegex(CustomPlanPricingError, "Missing FX rate"):
            calculate_custom_plan_price(base)

    def test_billing_period_discount_uses_node_two_decimal_total(self):
        self.assertEqual(apply_billing_discount("100", 3, "10"), Decimal("270.00"))

    def test_invalid_margin_and_negative_usage_fail_closed(self):
        base = {"quoteCurrency": "USD", "features": [], "vendorRates": [],
                "monthlyInfrastructureCost": 0, "activePayingTenants": 1, "estimatedOtherCost": 0,
                "targetGrossMargin": 1}
        with self.assertRaisesRegex(CustomPlanPricingError, "targetGrossMargin"):
            calculate_custom_plan_price(base)
        base["targetGrossMargin"] = "0.2"
        base["features"] = [{"featureId": "f", "estimatedUsage": -1}]
        with self.assertRaisesRegex(CustomPlanPricingError, "cannot be negative"):
            calculate_custom_plan_price(base)


if __name__ == "__main__":
    unittest.main()
