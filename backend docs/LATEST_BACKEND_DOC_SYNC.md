# Latest Backend Documentation Sync - 2026-09-24

## Code inspected

- `src/app.ts`
- subscription/custom-plan/platform-admin route files
- `validateUser.ts` and `validatePlatformUser.ts`
- `plan-transition.service.ts` and `plans.service.ts`
- Custom Plan configurator/pricing service and DTOs
- subscription repository/controller output semantics

## Major corrections

1. Platform administration now documents the actual database-backed owner model (`TenantUser.roleKey=owner` + permission JSON), not the obsolete standalone `platform_role` JWT model.
2. Tenant subscription checkout/change/cancel routes are documented with `manage_billing`.
3. Global plan/feature/plan-feature/promo administration is documented as owner-only platform commercial access using `billing.read`/`billing.manage`.
4. Added all currently mounted Custom Plan configurator, preview, manual-review, checkout, offer/accept, quote, pricing-policy, and vendor-rate routes.
5. Added `/platform-admin/me` and the full `/platform-admin/billing/*` route matrix.
6. Updated plan-change behavior for entitlement-aware `upgrade`/`downgrade`/`mixed`/`equivalent` classification and period-end safety when any entitlement is lost.
7. Clarified current vs scheduled subscription state (`planId` vs `scheduledPlanId`) and plan-definition Enabled/Disabled state.

## Known current permission inconsistency

`POST /subscription/custom-plans/quotes/:id/accept` still requires tenant `manage_catalog`, while self-service Custom Plan billing actions use `manage_billing`.
