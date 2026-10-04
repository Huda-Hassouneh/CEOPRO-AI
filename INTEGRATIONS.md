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
AI_SERVICE_URL=http://localhost:8000
AI_SERVICE_USE_MOCKS=true
```

`AI_SERVICE_URL` selects the upstream service.

Where a module supports it, `AI_SERVICE_USE_MOCKS=true` enables deterministic development behavior.

Production should use the real service and disable mocks.

---

## Authorization forwarding

The Node backend forwards the incoming Bearer token for the AI endpoints that expect CEOPRO user/tenant context.

The Node backend still performs its own route-level authentication/tenant checks before delegating.

---

## AI endpoint map

| CEOPRO backend feature | Upstream AI endpoint | Backend client |
|---|---|---|
| RAG query | `POST /rag/query` | `rag/client/rag.client.ts` |
| RAG document upload | `POST /rag/documents` | `rag/client/rag.client.ts` |
| Document extraction upload | `POST /extraction/upload` | `features/client/features-ai.client.ts` |
| Business-data ingestion upload | `POST /extraction/upload` | `dataconnection/client/ingestion.client.ts` |
| Pending extraction processing | `POST /extraction/process-pending` | feature/data-ingestion client flow |
| Pricing recommendation | `POST /pricing/recommend` | `pricing/client/pricing.client.ts` |
| Sentiment summary | `GET /sentiment/summary` | `sentiment/client/sentiment.client.ts` |
| Pending sentiment analysis | `POST /sentiment/analyze-pending` | `sentiment/client/sentiment.client.ts` |
| MPI summary | `GET /mpi/summary` | `mpi/client/mpi.client.ts` |

Forecasting and market-intelligence endpoints in this Node service are currently database-backed; they do not own a direct forecasting/market-intelligence AI HTTP client in the active code.

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
→ call AI /rag/query
→ validate response
→ return answer/sources
→ charge actual usage when supplied
```

The AI service performs the RAG/model work.

CEOPRO owns the entitlement and usage decision.

---

## RAG documents/chunks

The dedicated RAG module exposes tenant-scoped document/chunk reads and the Knowledge Base upload route:

```text
GET  /features/rag/documents
POST /features/rag/documents
GET  /features/rag/chunks/:chunk_id
```

`POST /features/rag/documents` forwards multipart field `file` to the AI service at `POST /rag/documents`. Supported upload extensions are `.txt`, `.md`, `.pdf`, `.docx`, and `.xlsx`. The AI response contract is `document_id`, `file_name`, and `processed_status`. These routes remain subject to the relevant feature access rules.

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

The AI upload response must include the fields the backend needs to persist metadata, including the object key used by the current document metadata flow.

The backend then persists the application-side document/usage state.

---

## RAG vs business-data ingestion

I keep these as separate product flows:

### Knowledge/RAG

Used to make documents searchable/answerable by the assistant. Knowledge Base uploads use `POST /features/rag/documents`, which delegates to AI `POST /rag/documents`.

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

The upload path calls the extraction service through:

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

I do not store passwords, API keys, access tokens, or connection strings in generic `data_sources.metadata`.

Secrets need a proper secret/configuration mechanism.

---

# Pending extraction processing

The integration client supports:

```text
POST /extraction/process-pending
```

The important question is **when to trigger it**.

I do not want the frontend to poll the scraper and guess that a spider finished.

Production options:

### Option A — completion signal

After a successful scraping/ingestion cycle, the component that knows the cycle is complete sends a trusted completion event/callback. A backend worker then processes pending extraction rows.

### Option B — scheduled worker

A backend worker runs on a controlled schedule, finds pending rows, and calls the processing endpoint in bounded batches.

Both are valid patterns.

The key rule is that background workflow coordination belongs to backend/worker infrastructure, not the frontend.

---

# Pricing recommendation

Frontend/API route:

```text
POST /features/pricing/recommend?product_id=<uuid>
```

Upstream AI route:

```text
POST /pricing/recommend
```

The backend prepares authoritative pricing inputs from CEOPRO data.

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

Upstream routes:

```text
POST /sentiment/analyze-pending
GET  /sentiment/summary
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

`analyze-pending` is a metered operation and is capped by the tenant's remaining `sentiment_analysis` usage.

The AI service returns how many rows were actually analyzed; usage should reflect actual processed work.

---

# When to run sentiment analyze-pending

The same background-trigger principle applies here.

I should run sentiment processing when new review data becomes available.

The clean production choices are:

- trigger it after a scraper/monitoring cycle reports successful completion; or
- run a backend worker periodically against pending review rows.

The frontend should not be responsible for knowing when a spider has closed.

---

# MPI / Market Perception

Backend route:

```text
GET /features/mpi/summary
```

Upstream route:

```text
GET /mpi/summary
```

The upstream contract supports:

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

- [ ] `AI_SERVICE_USE_MOCKS=false` in production.
- [ ] `AI_SERVICE_URL` points to the real deployed service.
- [ ] AI authentication/tenant forwarding works end to end.
- [ ] Every AI response is validated against the expected contract.
- [ ] No provider secrets are logged.
- [ ] `STRIPE_SECRET_KEY` and webhook secret are production-safe values.
- [ ] Stripe webhook signature verification works through the real ingress/proxy.
- [ ] Webhook retries are idempotent.
- [ ] Worker/trigger ownership for pending extraction is defined.
- [ ] Worker/trigger ownership for pending sentiment is defined.
- [ ] AI mock fallbacks cannot silently mask a production outage.
- [ ] Timeouts/retries are appropriate for the deployed environment.
- [ ] Feature/usage gates match the commercial product configuration.
- [ ] End-to-end tests cover both success and explicit `UNKNOWN`/no-data cases.
