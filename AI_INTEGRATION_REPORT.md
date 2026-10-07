# CEOPRO AI integration audit and implementation report

Date: 2026-10-05

## Audit findings

| Area | Before this change | Current status |
|---|---|---|
| Shared transport | Domain clients used direct FastAPI-style HTTP calls and separate error/auth behavior. Runtime configuration defaulted to a localhost service. | Implemented shared Gradio submit/SSE client with encrypted ZeroGPU token acquisition, per-Space memory cache, 401 refresh, timeout, response validation, and sanitized errors. |
| Extraction | FastAPI response assumptions included provider-owned storage/job identifiers; a duplicate feature client overlapped Data Connection. | Implemented analytics `extract_file`. CEOPRO creates the job/source/staging records and owns returned IDs. Staging maps clean, partial, and failed rows to local statuses. |
| Pricing | Existing pricing client targeted the old endpoint; a second obsolete ingestion client contained `TESTING_MODE=true`. | Implemented analytics `recommend` using tenant product, competitor observations, and rate data. CEOPRO owns market statistics, evidence, and outcome IDs. Obsolete duplicate clients were removed. |
| Sentiment | Existing client depended on external pending-analysis and summary endpoints plus mock behavior. | Implemented models `sentiment`; pending tenant reviews are loaded locally, sent in batches of at most 64, validated, upserted, and metered. Summaries aggregate local results. |
| MPI | Existing client expected `GET /mpi/summary`. | Implemented models `market_intelligence` from tenant-scoped reviews and locally persisted evidence. Insufficient samples remain `UNKNOWN`. |
| Market Intelligence | Existing overview metrics were database-backed; no direct analytics endpoint was active. | Existing metrics remain database-backed. Competitor MPI is optional enrichment through the MPI domain and returns unavailable values if the AI call fails. |
| Forecasting | Existing routes read stored forecasts; generation was missing. | Added authenticated `POST /forecasting/demand/:productId/generate`, tenant-owned input loading, analytics `forecast`, validation, and local forecast/evidence persistence. |
| RAG | Existing upload/query flow expected a persistent external FastAPI document service. | Uploads are retained in CEOPRO; queries submit up to ten stored documents to models `rag_answer`. Added a `BYTEA` source-content migration and local citation mapping. |

## Current constraints and configuration

- Live Hugging Face calls were not exercised. The transport and domain adapters were tested with injected fake responses. Deployment requires `HUGGINGFACE_ACCESS_TOKEN` and the intended models/analytics Space IDs and URLs.
- Apply migration `20261005110000_add_rag_source_file_content` before enabling the updated RAG query path.
- RAG files are limited to 2 MB each, and each query sends at most ten documents. Uploads do not call or index documents in the AI service.
- The current extraction model has no pending-batch API. `POST /features/extraction/process-pending` remains mounted and now returns HTTP 501; each file is submitted synchronously.
- Sentiment country filtering is unsupported because the CEOPRO review schema has no country column.
- Forecast output supplies `source` (`baseline` or `xgboost`) rather than a registered model-version ID. The backend stores that source in the existing forecast version field and creates its own evidence record; it does not register model metadata from `persisted_records`.
- Pricing entitlement and MPI feature-access gates remain as currently configured in their routes; the existing product decision is still tracked in `PROJECT_STATUS.md`.

## Files changed

- Shared transport: `src/integrations/ai/`.
- Domain clients and persistence: `src/modules/dataconnection/`, `pricing/`, `sentiment/`, `mpi/`, `market-intelligence/`, `forecasting/`, and `rag/`.
- RAG schema/migration: `prisma/schema.prisma` and `prisma/migrations/20261005110000_add_rag_source_file_content/`.
- Route/error mapping: legacy extraction controllers, forecasting generation route/controller, and `src/errors/`.
- Tests: `tests/ai/`, updated RAG contract tests, forecasting fixture expectations, and corrected route/feature/security source-contract checks.
- Documentation: `INTEGRATIONS.md`, `ARCHITECTURE.md`, `API_REFERENCE.md`, `README.md`, `PROJECT_STATUS.md`, and active domain AI integration guides. Obsolete FastAPI implementation guides now point to the current contract.

## Verification

- `npm run prisma:validate` — passed; Prisma reported seven pre-existing `SetNull` relation warnings.
- `npm run prisma:generate` — passed.
- `npx tsc --noEmit` — passed.
- `npm test` — passed: 57 unit tests, 44 route-contract checks, 29 security checks, 11/11 custom-plan groups, and feature-entitlement checks.
- `npm run test:rag` — passed: 5 RAG contract tests.
