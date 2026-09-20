# AI RAG Query (Currently Unmounted)

## 1. Endpoint Details

`POST /rag/query`

**Runtime status:** Defined but not mounted by `app.ts`.

## 2. Mental Model

Would send a tenant's knowledge question to the retrieval-augmented generation service and return an answer with source references.

## 3. Technical Decisions

The query is URL-encoded before forwarding, `top_k` is capped at 20 by validation and defaults to 5 in the controller, and usage increments only after provider success. Access is gated by `rag_assistant`.

## 4. Inputs

- Query: required `query_text: string`; optional `top_k: positive integer <= 20`.
- Body: none; no local header requirement.

## 5. Outputs

### Success

`200 OK`: `{ "success": true, "message": "Assistant query successful", "data": { "answer": "...", "sources": [] } }`.

### Errors

`400 INVALID_REQUEST` for missing query text; `502 EXTERNAL_SERVICE_ERROR` for AI failure; `500 INTERNAL_SERVER_ERROR` for unexpected failure.
