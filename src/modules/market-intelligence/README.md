# Market Intelligence Domain

## Purpose
Builds tenant market-intelligence metrics from persisted product, competitor, pricing, review, sentiment, and market data.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with optional MPI enrichment through `src/modules/mpi`.

## Request flow
`HTTP -> market-int.route -> market-int.controller -> market-int.service -> market-int.repo -> Prisma`

## Important decisions
- Market intelligence remains database-driven.
- Metrics that lack required source coverage remain unavailable rather than being fabricated.
- Existing score scaling/calculation behavior is preserved.
- Overview metrics remain database-driven; competitor MPI enrichment uses tenant reviews and the shared Gradio `market_intelligence` client.
- Pricing recommendation AI calls are owned by the separate `pricing` domain.
- The public route remains under `/market-intelligence`.

## Integration notes
The main overview does not replace its persisted metrics with AI output. Optional MPI enrichment is supplied by the MPI domain.
