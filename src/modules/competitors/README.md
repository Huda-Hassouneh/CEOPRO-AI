# Competitors Domain

## Purpose
Manages tenant-tracked competitors, competitor profiles, mapped products, and competitor activity derived from persisted price history.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`

## Request flow
`HTTP -> competitors.route -> competitors.controller -> competitors.service -> competitors.repo -> Prisma`

## Important decisions
- Tenant isolation is preserved by using `req.tenant_id` and repository filters.
- The global competitor pool is reused idempotently; creating a tenant competitor links to an existing global competitor when possible.
- Profile activity is derived from stored competitor price history. Missing schema-backed metrics remain empty instead of being fabricated.
- The public API mount remains `/competitors`; only source-file locations changed.

## Primary data
`tenant_competitors`, `global_competitors`, `competitor_product_mappings`, `competitor_prices`, and `products`.

## Integration notes
No direct third-party or AI client is owned by this domain.
