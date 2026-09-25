# Vendor Rates

## Legacy/internal endpoints
- `GET /subscription/custom-plans/vendor-rates` - owner + `billing.read`.
- `POST /subscription/custom-plans/vendor-rates` - owner + `billing.pricing.manage`.
- `PATCH /subscription/custom-plans/vendor-rates/:id` - owner + `billing.pricing.manage`.

The platform-admin aliases use `/platform-admin/billing/vendor-rates`.

A rate records vendor/service/billing unit/unit cost/currency, operational multiplier, variability reserve, effective dates, verification status, source/metadata, and optional linked `featureId`. Deprecated rates stay auditable rather than being destructively deleted.
