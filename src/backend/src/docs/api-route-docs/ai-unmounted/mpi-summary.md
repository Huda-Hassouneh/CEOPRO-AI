# AI Market Perception Index Summary (Currently Unmounted)

## 1. Endpoint Details

`GET /mpi/summary`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would provide a market perception index for a product, competitor, or business subject, combining sentiment, volume, recency, and reliability signals.

## 3. Technical Decisions

The route reuses the sentiment subject query schema and gates access with `market_perception`. It proxies only selected MPI metrics and evidence metadata from `AI_SERVICE_URL`, keeping provider response shape behind the backend contract.

## 4. Inputs

- Query: required `subject_type: PRODUCT | COMPETITOR | BUSINESS`; required `subject_id: string<uuid>`.
- Body/headers: none enforced locally.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Market Perception Index fetched successfully", "data": { "status": "ok", "mpi": 72, "weighted_sentiment_score": 0.7, "volume_confidence": 0.8, "review_count": 120, "avg_recency_weight": 0.9, "avg_reliability_weight": 0.85, "label_counts": {}, "confidence_score": 0.8, "sample_size": 120, "evidence_id": "..." } }`.

### Errors

`400 INVALID_REQUEST`, `502 EXTERNAL_SERVICE_ERROR`, or `500 INTERNAL_SERVER_ERROR` using the source controller's common envelope.
