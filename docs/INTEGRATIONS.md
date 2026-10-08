# Integrations and Operational Flows

This document is the single place where I describe how this backend communicates with systems outside the normal Express/Prisma request path.

The main integrations are:

1. PostgreSQL/pgvector.
2. Stripe.
3. The CEOPRO AI service.
4. Background processing triggers/workers around ingestion and sentiment.

---

## 1. Integration ownership rule

My boundary is simple:

```text
CEOPRO backend
    owns security + tenant + business rules + persistence
          ↓
domain client
    owns HTTP/provider transport + upstream validation
          ↓
external service
    owns the external computation/provider state
```

An external service should not become the place where CEOPRO decides who may access a tenant, what plan they have, how much quota they have, or what data may be written to the CEOPRO database.

---

# PostgreSQL and pgvector

## Local database

The included Compose service uses:

```text
pgvector/pgvector:0.8.6-pg17
```

with:

```text
Host: 127.0.0.1
Port: 5433
DB:   CEOPROTEST3
User: postgres
```

Start it with:

```bash
docker compose up -d postgres
```

Prisma uses:

```env
DATABASE_URL=...
```

The schema/config paths are:

```text
prisma/schema.prisma
prisma/migrations/
prisma7.config.ts
```

Generate/validate:

```bash
npm run prisma:generate
npm run prisma:validate
```

Apply migrations in a deployment-style environment:

```bash
npx prisma migrate deploy --config prisma7.config.ts
```

---

# Stripe

## What Stripe is used for

The active billing integration is Stripe.

The backend uses it for flows such as:

- shared CEOPRO Stripe product initialization;
- customer management;
- checkout;
- subscription lifecycle;
- coupons/promotions;
- billing portal/schedules where supported by the existing service;
- test-clock support;
- webhook synchronization.

PayPal source placeholders exist, but I do not treat PayPal as a production-complete provider in this repository.

---

## Stripe configuration

Relevant values:

```env
STRIPE_SECRET_KEY=...
STRIPE_SECRET_WEBHOOK=...

SUCCESS_SUBSCRIPTION_URL=...
FAILED_SUBSCRIPTION_URL=...

PROMO_FIXED_AMOUNT_CURRENCY=USD

STRIPE_USE_TEST_CLOCK=false
STRIPE_TEST_CLOCK_ID=...
```

`STRIPE_SECRET_KEY` is required by the active Stripe client.

`STRIPE_SECRET_WEBHOOK` is required to verify incoming Stripe webhook signatures.

---

## Stripe bootstrap

The shared Stripe product can be initialized with:

```bash
npm run bootstrap:stripe
```

The script reuses the normal onboarding service rather than implementing separate bootstrap-only provider logic.

The resulting Stripe product ID is stored in application configuration.

---

## Critical webhook rule

The webhook route is:

```http
POST /stripe/webhooks
```

It is mounted before the global JSON parser.

The order in `src/app.ts` must remain:

```text
Stripe raw-body route
        ↓
security headers
        ↓
express.json()
        ↓
normal JSON routes
```

The webhook route uses `express.raw({ type: "application/json" })`.

This is required for Stripe signature verification.

---

## Webhook reliability

The webhook processing path uses persisted webhook-event state so provider retries can be handled safely.

The important behavior is:

- verify the Stripe signature;
- process the provider event;
- persist local changes transactionally where required;
- mark the event processed only after successful handling;
- allow Stripe to retry when processing fails.

I do not want a failed business handler to be recorded as a successfully processed webhook.

---

## Tenant ownership

Stripe customer reuse must remain tenant-aware.

A matching email address alone is not enough to establish that a Stripe customer belongs to the current tenant.

---

# CEOPRO AI service

## Configuration

```env
HUGGINGFACE_ACCESS_TOKEN=hf_...
AI_MODELS_SPACE=hhuuddaa/ceopro-ai-models
AI_MODELS_SPACE_URL=https://hhuuddaa-ceopro-ai-models.hf.space
AI_ANALYTICS_SPACE=hhuuddaa/ceopro-ai-analytics
AI_ANALYTICS_SPACE_URL=https://hhuuddaa-ceopro-ai-analytics.hf.space
AI_SERVICE_TIMEOUT_MS=180000
```

The AI client uses two Hugging Face Spaces: the models Space for `sentiment`, `market_intelligence`, and `rag_answer`; and the analytics Space for `extract_file`, `recommend`, and `forecast`. Space IDs and URLs default to the values above and can be overridden per environment. Production requires HTTPS.

`HUGGINGFACE_ACCESS_TOKEN` is a server secret. The shared client uses it to request an encrypted ZeroGPU token from Hugging Face, caches that token in process memory, and sends it as `X-ZeroGPU-Token` on both Gradio calls. CEOPRO does not forward the end user's Authorization header to Hugging Face. Errors and logs must not expose either token.

The runtime has no automatic mock fallback. Unit tests inject a fake Gradio transport. `AI_SERVICE_USE_MOCKS=true` is rejected in production as a configuration error.

---

## AI endpoint map

All model calls use `POST /gradio_api/call/<api_name>` with positional JSON inputs, then `GET /gradio_api/call/<api_name>/<event_id>` and parse the Gradio SSE completion. The active API names are `extract_file`, `recommend`, `sentiment`, `market_intelligence`, `forecast`, and `rag_answer`.

| CEOPRO feature | Space | Gradio API | Source of authoritative data |
|---|---|---|---|
| Extraction upload | Analytics | `extract_file` | Uploaded file bytes and country/currency supplied by CEOPRO |
| Pricing recommendation | Analytics | `recommend` | Tenant product, cost, tracked competitor prices, and exchange rates from CEOPRO |
| Sentiment classification | Models | `sentiment` | Pending tenant reviews from CEOPRO |
| Market perception index | Models | `market_intelligence` | Tenant review samples from CEOPRO |
| Demand forecast generation | Analytics | `forecast` | Tenant product, inventory, and transaction history from CEOPRO |
| RAG answer | Models | `rag_answer` | Up to ten tenant documents loaded from CEOPRO storage |

The models Space currently receives requests without a CEOPRO country or tenant filter for the sentiment batch API; CEOPRO scopes and persists the results locally. Country-filtered sentiment summaries are unsupported because `reviews` has no country column.

---

# RAG and document extraction

## RAG query flow

Frontend/API caller:

```text
POST /features/rag/query
```

Backend flow:

```text
authenticate
→ resolve tenant
→ validate query
→ check rag_assistant entitlement
→ load up to ten tenant documents from CEOPRO storage
→ call Gradio `rag_answer`
→ validate response
→ map citations to CEOPRO document/chunk IDs
→ return answer/sources
→ charge actual usage when supplied
```

CEOPRO retains uploaded source bytes because the Gradio RAG API processes documents supplied on each query and does not keep an external document store. Each upload is limited to 2 MB. Plain text and Markdown are sent as text; PDF, DOCX, and XLSX are sent as Base64. RAG queries submit the latest ten documents, so older documents remain stored but are not included in each request.

CEOPRO owns the entitlement and usage decision.

---

## RAG documents/chunks

The dedicated RAG module exposes tenant-scoped document/chunk reads and the Knowledge Base upload route:

```text
GET  /features/rag/documents
POST /features/rag/documents
GET  /features/rag/chunks/:chunk_id
```

`POST /features/rag/documents` accepts multipart field `file` and stores the file and metadata in CEOPRO. Upload does not call the AI service. Supported extensions are `.txt`, `.md`, `.pdf`, `.docx`, and `.xlsx`; each file is limited to 2 MB. Query-time citations are mapped to CEOPRO document and chunk records.

---

## Extraction upload

The legacy/general extraction endpoint is:

```text
POST /features/extraction/upload
```

The backend checks:

- tenant/auth;
- file presence;
- upload size;
- supported extension;
- `document_extraction` quota;
- storage/capacity rules owned by CEOPRO;
- AI response shape.

The backend sends the upload as Base64 in positional input `[file_name, file_base64, country_code, currency]` to analytics `extract_file`. CEOPRO creates and owns the job and import staging rows; the AI response does not contain a MinIO object key or CEOPRO IDs.

The backend then persists the application-side document/usage state.

---

## RAG vs business-data ingestion

I keep these as separate product flows:

### Knowledge/RAG

Used to make documents searchable/answerable by the assistant. Knowledge Base uploads use `POST /features/rag/documents`; CEOPRO retains source bytes and supplies the documents to Gradio `rag_answer` during a query.

### Data Connection ingestion

Used to import business/sales/operational data into CEOPRO data workflows.

They may reuse extraction infrastructure, but they are not the same user-facing feature and should not be collapsed into one API just because the upstream AI endpoint is shared.

---

# Data Connection ingestion

Main backend routes:

```text
GET  /data-connection
POST /data-connection
POST /data-connection/sources
```

The upload path calls analytics `extract_file` through:

```text
src/modules/dataconnection/client/ingestion.client.ts
```

The backend owns:

- tenant context;
- feature checks;
- file limits;
- source/job persistence;
- frontend-facing status;
- safe metadata handling.

After extraction, accepted rows are persisted as pending staging rows. A separate process (`npm run worker:data-ingestion`) polls queued jobs every 10 seconds, validates each staged sales payload, creates or reuses a tenant product, inserts a `transactions` row, and updates the staging row with its committed transaction ID. Invalid staged rows are quarantined as `INVALID`. The worker uses `INGESTION_WORKER_DATABASE_URL` and the restricted `ceopro_ingestion_worker` database role; it is separate from the notification worker. Upload still waits for synchronous AI extraction, while the business-table import runs asynchronously.

I do not store passwords, API keys, access tokens, or connection strings in generic `data_sources.metadata`.

Secrets need a proper secret/configuration mechanism.

---

# Pending extraction processing

The legacy CEOPRO routes remain mounted:

```text
POST /features/extraction/process-pending
```

The current Gradio `extract_file` API processes an uploaded file synchronously and has no `process-pending` equivalent. The mounted legacy feature route returns HTTP 501 with `NOT_IMPLEMENTED`; clients should submit each file to the upload endpoint.

The separate `worker:data-ingestion` process does not call that legacy endpoint. It consumes CEOPRO's already-extracted `import_staging_rows` and commits valid sales rows into CEOPRO's own business tables.

---

# Pricing recommendation

Frontend/API route:

```text
POST /features/pricing/recommend?product_id=<uuid>
```

Gradio API:

```text
analytics Space: recommend
```

Inputs are `[product, competitor_prices, exchange_rates]`. The backend loads product, cost, competitor-price, and rate data from CEOPRO before calling the model, then creates CEOPRO evidence and outcome IDs locally.

The AI service recommends; it does not choose what tenant/product data is authoritative.

The client validates both successful and explicit unknown/unavailable response shapes.

The backend may derive supporting market statistics from its own canonical competitor-price data rather than trusting undocumented AI fields.

Important current-state note:

```text
requireEntitlement("ai_pricing")
```

is currently commented out in the active pricing route. The route still requires authentication and tenant context. I track the final gating decision in `PROJECT_STATUS.md`.

---

# Sentiment

Backend routes:

```text
POST /features/sentiment/analyze-pending
GET  /features/sentiment/summary
```

Gradio API:

```text
models Space: sentiment
```

### Summary

The summary supports subjects such as:

```text
PRODUCT
COMPETITOR
BUSINESS
```

Product/competitor summaries use a subject identifier. Business-level summaries can work without one according to the current validation contract.

Unknown/low-sample states stay explicit.

### Pending analysis

`analyze-pending` reads pending tenant reviews from CEOPRO, sends texts to the `sentiment` API in batches of at most 64, persists validated predictions locally, and meters actual processed reviews against the tenant's remaining `sentiment_analysis` usage.

The summary route aggregates CEOPRO's stored results; it is not a separate upstream request. Country filtering is unsupported because the review schema has no country field.

---

# When to run sentiment analyze-pending

The authenticated endpoint processes pending reviews synchronously. A future scraper or scheduled worker may call the CEOPRO endpoint after new reviews land; the model itself does not own or discover pending tenant records.

---

# MPI / Market Perception

Backend route:

```text
GET /features/mpi/summary
```

Gradio API:

```text
models Space: market_intelligence
```

The backend selects tenant reviews and sends `[reviews, subject_type, subject_id, country_code, as_of]`. It persists evidence locally and maps the model result to the existing CEOPRO summary response. The Gradio output supports:

- `OK` with a 0-100 MPI and supporting metrics; or
- `UNKNOWN` when there is not enough usable evidence.

I preserve `UNKNOWN` instead of converting it to zero.

Important current-state note:

```text
requireFeatureAccess("market_perception")
```

is currently commented out in the active MPI route. The final feature-gating decision is tracked in `PROJECT_STATUS.md`.

---

# Forecasting

Backend routes:

```text
GET /forecasting/demand
GET /forecasting/demand/:productId
```

The active Node forecasting domain reads persisted forecast/inventory/product data.

It is gated by:

```text
demand_prediction
```

There is no direct forecasting AI HTTP client in the active Node domain right now.

That means the process that generates/persists forecast records is operationally separate from these read endpoints.

---

# Market Intelligence

Backend route:

```text
GET /market-intelligence
```

The active implementation builds metrics from persisted data such as products, competitors, prices, reviews, sentiment, forecasts, and score snapshots.

The pricing AI integration stays in the separate `pricing` domain.

I do not duplicate the pricing client inside market intelligence.

---

# Failure handling for external AI calls

External clients should consistently handle:

- timeout;
- connection/network failure;
- non-2xx HTTP response;
- invalid JSON;
- schema/contract mismatch.

The external client converts those failures into the domain's existing external-service error behavior.

The rest of the backend should not continue as though an invalid provider response were valid production data.

---

# Production integration checklist

Before I consider external integrations production-ready, I verify:

- [ ] `HUGGINGFACE_ACCESS_TOKEN` is configured in the secret store.
- [ ] Model and analytics Space IDs/URLs point to the intended deployments.
- [ ] Hugging Face ZeroGPU token acquisition and refresh work end to end.
- [ ] Every AI response is validated against the expected contract.
- [ ] No provider secrets are logged.
- [ ] `STRIPE_SECRET_KEY` and webhook secret are production-safe values.
- [ ] Stripe webhook signature verification works through the real ingress/proxy.
- [ ] Webhook retries are idempotent.
- [ ] Clients understand that legacy extraction `process-pending` returns 501.
- [ ] AI mock fallbacks cannot silently mask a production outage.
- [ ] Timeouts/retries are appropriate for the deployed environment.
- [ ] Feature/usage gates match the commercial product configuration.
- [ ] End-to-end tests cover both success and explicit `UNKNOWN`/no-data cases.
