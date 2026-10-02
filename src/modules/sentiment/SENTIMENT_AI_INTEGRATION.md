# Sentiment AI Integration

## Endpoints
- `GET /sentiment/summary`
- `POST /sentiment/analyze-pending`

Both are resolved relative to `AI_SERVICE_URL` and receive the caller Authorization header.

## Summary contract
The backend sends `subject_type`, optional `subject_id`, and optional `country_context`. The response must match either the existing `OK` summary contract or the explicit `UNKNOWN` contract. Low sample size remains explicit in `sample_size`.

## Pending-analysis contract
The backend sends `batch_size`; the AI service returns an `OK` result with `analyzed_count`.

## Operational trigger
`analyze-pending` is intended to run after new review/sentiment source data becomes available. In production this should be triggered by the ingestion/scraping completion workflow or a backend worker schedule; the frontend should not be responsible for detecting spider completion.

## Configuration and failures
`AI_SERVICE_USE_MOCKS=true` preserves local mock behavior. The client validates all upstream JSON and maps timeout/network/non-2xx/schema failures to the existing sentiment client error.

## Boundary rule
CEOPRO owns authentication, tenant isolation, feature access, orchestration, and stored application data. The AI service owns sentiment inference only.
