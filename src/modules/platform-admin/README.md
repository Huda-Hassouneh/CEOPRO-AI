# Platform Admin Domain

## Purpose
Provides the platform-admin HTTP facade for platform identity, owner-portal routes, plans, subscriptions, custom plans/quotes, pricing policy, rates, promo codes, and feature management.

## Structure
`index.ts -> route/ -> controller/`, delegating business operations to the owning domains (`owner-portal`, `subscription`, and `features`).

## Important decisions
- This domain is intentionally an orchestration/facade layer instead of duplicating subscription/features repositories and services.
- Platform membership and permission checks remain mandatory and server-side.
- Billing/custom-plan logic remains owned by `subscription`; feature catalog/plan-feature logic remains owned by `features`.
- Route URLs and permission names were not changed.
- Direct platform profile lookup behavior remains unchanged in the controller in this structural-only pass.

## Cross-domain dependencies
`owner-portal`, `subscription`, `features`, shared platform-user validation, and Prisma for the existing platform profile lookup.

## Integration notes
No AI client is owned here.
