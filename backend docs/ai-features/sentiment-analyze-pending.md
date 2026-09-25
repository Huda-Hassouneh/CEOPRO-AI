# AI Sentiment Batch Analysis

> **Latest codebase sync (2026-09-24):** Verified against `CEOPRO_Entitlements_CustomPlan_UX_Fixed.zip` with the later `CEOPRO_CustomPlan_Card_Alignment_Icons_Fix.zip` frontend overlay. Where older historical notes conflict with a “current behavior” section, the latest-codebase section is authoritative.

## 1. Endpoint Details

`POST /features/sentiment/analyze-pending`

**Runtime status:** Mounted by `modules/features/index.ts` under `/features`; authenticated tenant context is required.

## 2. Mental Model

Triggers batch processing for pending sentiment records and count the successful operation against the tenant's `sentiment_analysis` entitlement.

## 3. Technical Decisions

The optional `batch_size` query is validated and forwarded to the AI service. The route applies `requireEntitlement("sentiment_analysis")`; usage increments only after a successful provider response.

## 4. Inputs

- Query: optional `batch_size: positive integer`.
- Header: `Authorization: Bearer <JWT>` with tenant context.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Batch sentiment analysis completed", "data": { "status": "ok", "analyzed_count": 25 } }`.

### Errors

`502 EXTERNAL_SERVICE_ERROR` with detail `AI Sentiment Service failed`; `500 INTERNAL_SERVER_ERROR` for unexpected errors; entitlement middleware may reject unauthorized usage.
