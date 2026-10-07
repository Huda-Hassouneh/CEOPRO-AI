# Features & Entitlements Domain

## Purpose
Owns the feature catalog, plan-feature assignments, subscription usage/entitlement checks, and document extraction/storage capacity enforcement. Dedicated RAG HTTP endpoints now live in `src/modules/rag`.

## Structure
- `index.ts` composes feature routes.
- `route/` owns HTTP routing and middleware.
- `controller/` owns HTTP request/response handling.
- `service/` owns entitlement/feature business rules.
- `repo/` owns Prisma access and usage persistence.
- Legacy `/features/extraction/*` routes delegate extraction uploads to the Data Connection domain; pending processing remains mounted and returns HTTP 501.
- `types/` owns schemas, DTOs, catalog definitions, and domain types.

## Important decisions
- `rag_assistant` remains a token-limited feature.
- `document_extraction` remains a separate KB-based usage feature from `document_storage_mb`, which represents stored capacity in MB.
- Boolean features and limit features remain distinct; usage code does not invent numeric limits for boolean features.
- Entitlement checks remain server-authoritative.
- AI requests use domain clients over `src/integrations/ai/`; this module does not own an AI transport client.
- Actual RAG token usage is charged after the AI response because exact token consumption is not known before the request completes.
- Missing/unsupported values are not silently converted into fake production data.

## Cross-domain usage
Subscription plans and platform-admin management call into this domain for feature catalog and plan-feature operations.

## AI integration
See `RAG_AND_EXTRACTION_AI_INTEGRATION.md` and `../rag/RAG_AI_INTEGRATION.md`.
