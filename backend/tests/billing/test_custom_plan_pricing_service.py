"""Unit checks for fail-closed Custom Plan pricing-policy validation."""
import unittest
from decimal import Decimal

from src.ai.billing.custom_plan_pricing_service import _unconfigured_policy_fields


class CustomPlanPricingServiceTests(unittest.TestCase):
    def test_missing_values_are_not_treated_as_zero_or_one(self):
        row = {
            "target_gross_margin": None,
            "enforce_vendor_cost_ratio_floor": None,
            "fixed_platform_fee_usd": None,
            "upward_rounding_increment_usd": None,
            "monthly_shared_infrastructure_cost_usd": None,
            "active_paying_tenant_count": None,
        }
        reasons = _unconfigured_policy_fields(row)
        self.assertIn("pricing_policy.target_gross_margin", reasons)
        self.assertIn("pricing_policy.fixed_platform_fee_usd", reasons)
        self.assertNotIn("pricing_policy.active_paying_tenant_count", reasons)

    def test_shared_cost_requires_verified_allocation_count(self):
        row = {"target_gross_margin": Decimal("0.2"), "enforce_vendor_cost_ratio_floor": False,
               "fixed_platform_fee_usd": Decimal("0"), "upward_rounding_increment_usd": Decimal("0"),
               "monthly_shared_infrastructure_cost_usd": Decimal("12"), "active_paying_tenant_count": None}
        self.assertIn("pricing_policy.active_paying_tenant_count", _unconfigured_policy_fields(row))

    def test_zero_shared_cost_does_not_require_allocation_count(self):
        row = {"target_gross_margin": Decimal("0.2"), "enforce_vendor_cost_ratio_floor": False,
               "fixed_platform_fee_usd": Decimal("0"), "upward_rounding_increment_usd": Decimal("0"),
               "monthly_shared_infrastructure_cost_usd": Decimal("0"), "active_paying_tenant_count": None}
        self.assertNotIn("pricing_policy.active_paying_tenant_count", _unconfigured_policy_fields(row))


if __name__ == "__main__":
    unittest.main()
