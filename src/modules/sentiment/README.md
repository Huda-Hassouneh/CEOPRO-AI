# Sentiment Domain

## Purpose
Exposes sentiment summary retrieval and pending-sentiment analysis through the Gradio sentiment model.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> client/`, with validation/contracts in `types/`.

## Important decisions
- Tenant and entitlement checks remain server-side.
- Product/competitor summaries require a subject ID; business summaries may omit it according to the existing schema.
- AI responses are runtime-validated and saved to tenant-scoped CEOPRO records.
- `UNKNOWN`/low-sample states remain explicit instead of being converted into fake sentiment values.
- Pending analysis remains a distinct operation from summary retrieval.
- Shared transport owns ZeroGPU token handling, timeouts, SSE parsing, and sanitized external-service errors. No runtime mock fallback is enabled.

## AI integration
See `SENTIMENT_AI_INTEGRATION.md`.
