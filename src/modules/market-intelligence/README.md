# Market Intelligence Domain

## Purpose
Builds tenant market-intelligence metrics from persisted product, competitor, pricing, review, sentiment, and market data.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`

## Request flow
`HTTP -> market-int.route -> market-int.controller -> market-int.service -> market-int.repo -> Prisma`

## Important decisions
- Market intelligence remains database-driven.
- Metrics that lack required source coverage remain unavailable rather than being fabricated.
- Existing score scaling/calculation behavior is preserved.
- Pricing recommendation AI calls are owned by the separate `pricing` domain; this domain does not duplicate that external client.
- The public route remains under `/market-intelligence`.

## Integration notes
No direct external AI transport is owned by this domain.
