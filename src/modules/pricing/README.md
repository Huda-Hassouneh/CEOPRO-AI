# Pricing Recommendation Domain

## Purpose
Collects the server-authoritative pricing recommendation inputs for a tenant/product and calls the external AI pricing service.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/ -> client/`, with schemas/contracts in `types/`.

## Important decisions
- Backend data preparation remains authoritative; the client is not trusted to supply pricing evidence directly.
- The external AI response is runtime-validated before it is returned/used.
- Existing timeout/error mapping and `AI_SERVICE_USE_MOCKS` behavior are preserved.
- The unrelated duplicate ingestion client previously inside this domain was removed because it had no references and belonged to data connection.
- No pricing formulas or business calculations were changed by the restructuring.

## AI integration
See `PRICING_AI_INTEGRATION.md`.
