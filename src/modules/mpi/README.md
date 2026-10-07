# MPI Domain

## Purpose
Provides Market Perception Index summaries for business/product/competitor subjects through the Gradio `market_intelligence` API.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> client/`, with request/response schemas in `types/`.

## Important decisions
- Tenant authentication remains mandatory.
- AI responses are runtime-validated before being accepted.
- `UNKNOWN` remains a valid upstream state and is not converted into an invented score.
- Eligible review samples and evidence records remain tenant-scoped in CEOPRO.
- Shared transport failures map to external-service errors without exposing provider credentials.
- No runtime mock fallback is enabled.

## AI integration
See `MPI_AI_INTEGRATION.md`.
