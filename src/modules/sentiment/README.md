# Sentiment Domain

## Purpose
Exposes sentiment summary retrieval and pending-sentiment analysis through the external AI sentiment contract.

## Structure
`index.ts -> route/ -> controller/ -> service/ -> client/`, with validation/contracts in `types/`.

## Important decisions
- Tenant and entitlement checks remain server-side.
- Product/competitor summaries require a subject ID; business summaries may omit it according to the existing schema.
- AI responses are runtime-validated.
- `UNKNOWN`/low-sample states remain explicit instead of being converted into fake sentiment values.
- Pending analysis remains a distinct operation from summary retrieval.
- Existing mock mode and timeout/error behavior are preserved.

## AI integration
See `SENTIMENT_AI_INTEGRATION.md`.
