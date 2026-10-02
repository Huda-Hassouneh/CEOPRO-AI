# Dashboard Domain

## Purpose
Builds the tenant dashboard overview from persisted company, subscription, feature-usage, market, and operational data.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`

## Request flow
`HTTP -> dashboard.route -> dashboard.controller -> dashboard.service -> dashboard.repo -> Prisma`

## Important decisions
- The existing dashboard route remains mounted at `/companies/:companyId/dashboard`.
- Dashboard values stay database-backed; the structural refactor does not replace missing values with mock production data.
- Aggregation/orchestration remains in service/repo code rather than being moved into the router.
- Existing response contracts are unchanged.

## Integration notes
No direct AI client is owned by this domain.
