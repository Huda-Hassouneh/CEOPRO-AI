# Forecasting Domain

## Purpose
Serves persisted demand-prediction overview/detail data and generates a product forecast through the analytics Gradio API.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with calculation helpers under `service/`.

## Request flow
`HTTP -> forecasting.route -> forecasting.controller -> forecasting.service/calculations -> forecasting.repo -> Prisma`

## Important decisions
- Access remains gated by the `demand_prediction` feature entitlement.
- Forecast metrics are derived from persisted forecast coverage; missing or incomplete coverage is not treated as zero.
- Forecast generation is exposed at `POST /forecasting/demand/:productId/generate` with `horizon_days` from 1 to 60.
- Tenant product, inventory, and transaction data come from CEOPRO; generated forecasts and evidence are persisted locally.
- Existing read routes remain database-backed; incomplete coverage stays unavailable rather than becoming zero.

## Primary data
Demand forecast records, product/inventory inputs, and transaction history accessed by the repository.

## AI integration
The generation client uses `src/integrations/ai/`. See [`../../../INTEGRATIONS.md`](../../../INTEGRATIONS.md#ceopro-ai-service) for transport details.
