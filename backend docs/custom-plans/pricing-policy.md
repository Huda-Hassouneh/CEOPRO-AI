# Custom Plan Pricing Policy

## Endpoints
- `GET /subscription/custom-plans/pricing-policy` - owner + `billing.read`.
- `PATCH /subscription/custom-plans/pricing-policy` - owner + `billing.pricing.manage`.

The platform-admin aliases are `/platform-admin/billing/pricing-policy` with the same effective permissions.

## Configurable policy fields
Currency, target gross margin, fixed platform fee, shared infrastructure cost, active-paying-tenant divisor, other cost, rounding increment, automatic-price/quota limits, optional vendor-cost/revenue floor, FX metadata, trial period, billing options, and per-feature automatic min/max/step.

These are internal commercial inputs and are not exposed by the customer configurator/preview response.
