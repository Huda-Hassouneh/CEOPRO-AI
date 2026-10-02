# Forecasting Domain

## Purpose
Serves demand-prediction overview and product forecast detail data from persisted forecast records.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/`, with calculation helpers under `service/`.

## Request flow
`HTTP -> forecasting.route -> forecasting.controller -> forecasting.service/calculations -> forecasting.repo -> Prisma`

## Important decisions
- Access remains gated by the `demand_prediction` feature entitlement.
- Forecast metrics are derived from persisted forecast coverage; missing or incomplete coverage is not treated as zero.
- Existing date/coverage calculation logic is unchanged by this structural pass.
- No mock forecasting values were introduced.

## Primary data
Demand forecast records and supporting product/inventory data accessed by the existing repository.

## AI integration
This backend domain currently contains no direct AI HTTP client. It serves persisted forecasting results, so no AI integration document is added here until the backend owns such a contract.
