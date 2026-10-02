# MPI Domain

## Purpose
Provides Market Perception Index summaries for business/product/competitor subjects through the external AI MPI contract.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> client/`, with request/response schemas in `types/`.

## Important decisions
- Tenant authentication remains mandatory.
- AI responses are runtime-validated before being accepted.
- `UNKNOWN` remains a valid upstream state and is not converted into an invented score.
- Timeouts, malformed JSON, and non-2xx responses remain external-service failures.
- Optional AI mocks continue to be controlled by `AI_SERVICE_USE_MOCKS`.

## AI integration
See `MPI_AI_INTEGRATION.md`.
