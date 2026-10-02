# Opportunities / Competitor Leaderboard Domain

## Purpose
Builds the competitor leaderboard/opportunity view from tenant-tracked competitors and the latest comparable product prices.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`

## Important decisions
- The source folder typo `opputunities` was corrected to `opportunities`; the HTTP mount remains `/leaderboard`, so the API contract is unchanged.
- Ranking continues to be based on the existing price competitiveness calculation and sort order.
- Only persisted mapped products and latest available competitor prices are used.
- No AI or mock ranking logic was introduced.

## Primary data
`tenant_competitors`, `global_competitors`, `competitor_product_mappings`, `competitor_prices`, and `products`.
