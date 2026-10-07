# Pricing Recommendation Domain

## Purpose
Collects the server-authoritative pricing recommendation inputs for a tenant/product and calls the external AI pricing service.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> repo/ -> client/`, with schemas/contracts in `types/`.

## Important decisions
- Backend data preparation remains authoritative; the client is not trusted to supply pricing evidence directly.
- The Gradio analytics response is runtime-validated before use.
- Product/competitor inputs and persisted evidence/outcomes remain tenant-owned CEOPRO data.
- The shared transport handles ZeroGPU authentication, timeout, SSE parsing, and sanitized errors; there is no runtime mock fallback.
- The unrelated duplicate ingestion client previously inside this domain was removed because it had no references and belonged to data connection.

## AI integration
See `PRICING_AI_INTEGRATION.md`.
