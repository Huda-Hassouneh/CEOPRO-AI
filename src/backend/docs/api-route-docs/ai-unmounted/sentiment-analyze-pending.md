# AI Sentiment Batch Analysis (Currently Unmounted)

## 1. Endpoint Details

`POST /sentiment/analyze-pending`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would trigger batch processing for pending sentiment records and count the successful operation against the tenant's `sentiment_analysis` entitlement.

## 3. Technical Decisions

The optional `batch_size` query is validated and forwarded to the AI service. The route applies `requireEntitlement("sentiment_analysis")`; usage increments only after a successful provider response.

## 4. Inputs

- Query: optional `batch_size: positive integer`.
- Body: none. Headers are not enforced locally because the parent router's auth middleware is commented out.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Batch sentiment analysis completed", "data": { "status": "ok", "analyzed_count": 25 } }`.

### Errors

`502 EXTERNAL_SERVICE_ERROR` with detail `AI Sentiment Service failed`; `500 INTERNAL_SERVER_ERROR` for unexpected errors; entitlement middleware may reject unauthorized usage.
