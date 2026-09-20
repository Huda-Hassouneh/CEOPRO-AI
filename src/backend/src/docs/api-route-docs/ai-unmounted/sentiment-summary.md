# AI Sentiment Summary (Currently Unmounted)

## 1. Endpoint Details

`GET /sentiment/summary`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would retrieve an aggregate sentiment view for a product, competitor, or business subject from the AI service.

## 3. Technical Decisions

The shared summary schema restricts subject type and UUID shape before the controller makes a provider GET. The response is curated to status, score, label counts, sample size, and evidence ID. This route requires the boolean/entitlement gate `sentiment_analysis`.

## 4. Inputs

- Query: required `subject_type: PRODUCT | COMPETITOR | BUSINESS`; required `subject_id: string<uuid>`.
- Body: none; no route-local required headers.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Sentiment summary retrieved successfully", "data": { "status": "ok", "sentiment_score": 0.75, "label_counts": {}, "sample_size": 100, "evidence_id": "..." } }`.

### Errors

`400 INVALID_REQUEST` for missing subject fields; `502 EXTERNAL_SERVICE_ERROR` for provider failure; `500 INTERNAL_SERVER_ERROR` for unexpected errors.
