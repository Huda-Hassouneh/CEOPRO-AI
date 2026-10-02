# Architecture

This document explains how I structure the CEOPRO AI backend, what each layer owns, and the architectural decisions I want to preserve while the product grows.

---

## 1. Core design

I organize application code around **feature domains**, not around one global folder for every controller/service/repository.

The preferred shape is:

```text
src/modules/<domain>/
├── index.ts
├── route/
├── controller/
├── service/
├── repo/        # when the domain owns persistence
├── client/      # when the domain calls an external service/provider
└── types/
```

A normal request should read like:

```text
HTTP request
   ↓
route
   ↓
controller
   ↓
service
   ↓
repo / client
   ↓
PostgreSQL / external provider
```

I do not force a domain to own a repository or client if it does not need one.

---

## 2. Layer responsibilities

### `index.ts`

The public entry point for the domain.

I use it to mount/compose the domain router and, where necessary, export a narrow public API to another domain.

I do not want unrelated modules importing arbitrary internal files when an intentional domain entry point is enough.

### `route/`

Owns HTTP concerns:

- method + path;
- authentication middleware;
- tenant middleware;
- permission/entitlement middleware;
- request body/query/parameter validators;
- upload middleware;
- controller binding.

Routes should not contain business calculations.

### `controller/`

Owns request/response translation:

- read validated request data;
- call the service;
- select/shape the HTTP response;
- translate known domain errors where necessary.

Controllers should stay thin.

### `service/`

Owns the business rules and orchestration:

- workflow decisions;
- billing rules;
- quota calculations;
- feature behavior;
- validation that depends on business state;
- transactions that span multiple repositories;
- orchestration of repositories and external clients.

If I need to understand *why* the system behaves a certain way, the answer should normally be in this layer.

### `repo/`

Owns persistence:

- Prisma queries;
- transaction-scoped queries;
- database reads/writes;
- tenant-scoped data retrieval;
- persistence-specific mapping.

Repositories should not know about Express response objects or HTTP status codes.

### `client/`

Owns external transport:

- Stripe API calls;
- CEOPRO AI HTTP calls;
- provider timeout/retry behavior;
- upstream JSON parsing;
- upstream contract validation.

The client does **not** decide tenant authorization or CEOPRO billing policy.

### `types/`

Owns domain contracts:

- DTO/Zod schemas;
- request/response domain types;
- provider response types;
- domain configuration types.

---

## 3. Active domains

| Domain | What it owns | Persistence | External integration |
|---|---|---:|---|
| `subscription` | Plans, subscriptions, checkout, invoices, promo codes, custom plans, quotes, rates, billing policy | Yes | Stripe |
| `features` | Feature catalog, plan features, entitlements, usage, RAG/extraction frontend endpoints | Yes | CEOPRO AI |
| `platform-admin` | Platform HTTP facade for owner/billing management | Delegates | None directly |
| `owner-portal` | Companies, users, admin team, audit logs, settings, profile/session operations | Yes | None |
| `dashboard` | Tenant dashboard aggregation | Yes | None |
| `competitors` | Tracked competitors and competitor profiles | Yes | None |
| `opportunities` | Competitor opportunity/leaderboard view | Yes | None |
| `dataconnection` | Data sources and business-data ingestion | Yes | CEOPRO AI extraction |
| `forecasting` | Demand forecast overview/detail from persisted forecasts | Yes | No direct Node AI client |
| `market-intelligence` | Market-intelligence metrics from persisted data | Yes | No direct client |
| `pricing` | Server-prepared AI pricing recommendation | Yes | CEOPRO AI pricing |
| `sentiment` | Sentiment summary and pending analysis | Usage only / delegated | CEOPRO AI sentiment |
| `mpi` | Market Perception Index summary | No direct repo | CEOPRO AI MPI |
| `auth` | Login/session/logout/invitation handlers in source | Direct Prisma + owner portal service | None |

The `auth` source module is currently **not mounted by `src/app.ts`**, so it is not an active public API surface yet.

---

## 4. HTTP composition

`src/app.ts` is the source of truth for what is actually live.

Current top-level mounts:

```text
/stripe/webhooks
/platform-admin
/subscription
/features/pricing
/features/sentiment
/features/mpi
/features
/plans/:plan_id/features
/subscriptions/current/usage
/companies/:companyId/dashboard
/forecasting
/data-connection
/market-intelligence
/competitors
/leaderboard
/
```

Some paths above are mounted through a domain index router rather than directly in `app.ts`.

The complete live method/path table is in [`API_REFERENCE.md`](API_REFERENCE.md).

---

## 5. Authentication, tenant isolation, and permissions

I treat the backend as the security boundary.

### Authentication

Protected routes use the shared JWT authentication middleware.

The token is expected to identify the user and tenant context used by the request.

### Tenant validation

`requireTenant` verifies that the request is operating inside an active tenant context and that the user has a valid active membership.

A request must not gain tenant access just because it has a syntactically valid token.

### Tenant permissions

Tenant-scoped operations can additionally require permissions such as:

```text
manage_billing
manage_catalog
all
```

### Platform access

Platform-administration routes use:

```text
requirePlatformRole
requirePlatformPermission(...)
```

Common platform permissions include:

```text
platform.overview.read
companies.read
companies.update
companies.status.manage
users.read
users.manage
adminTeam.read
adminTeam.invite
adminTeam.roles.manage
adminTeam.remove
auditLogs.read
platformSettings.read
platformSettings.manage

billing.read
billing.manage
billing.pricing.manage
subscriptions.read
```

The single-owner protections in the owner-portal services are business rules, not frontend rules.

---

## 6. Feature entitlements and usage

Features are catalog records linked to plans through plan-feature records.

I keep two concepts separate:

- **Feature access** — is this capability enabled for the tenant?
- **Metered entitlement** — is the capability enabled and does it still have usable quota?

This distinction matters for operations such as:

- `rag_assistant`;
- `document_extraction`;
- `sentiment_analysis`;
- `demand_prediction`;
- other limit/boolean features.

Boolean features should not be converted into fake numeric limits.

Limit features may be reset by billing period or treated as lifetime usage depending on their catalog definition.

The server remains authoritative for usage increments.

---

## 7. Subscription and billing decisions

### Stripe is a provider, not the business authority

CEOPRO owns:

- plan definitions;
- custom-plan configuration;
- feature entitlements;
- server-authoritative pricing;
- tenant ownership;
- promo-code rules;
- plan transition rules;
- local subscription state;
- invoice/payment persistence.

Stripe owns provider-side payment/subscription objects.

I do not want provider identifiers to replace CEOPRO authorization or business state.

### Plan transitions

The current plan-transition logic compares actual feature entitlements first.

Conceptually:

```text
gains only        -> upgrade
losses only       -> downgrade
gains + losses    -> mixed
no differences    -> equivalent
```

When an entitlement is lost, the safe behavior is normally period-end transition rather than immediate removal.

### Custom plans

The custom-plan flow supports both:

1. an automatic/self-service quote path; and
2. a manual-review quote path.

Important decisions I want to preserve:

- accepted custom-plan data is protected from silent mutation;
- customer-private custom plans stay tenant-private;
- pricing inputs stay server-authoritative;
- quote snapshots/fingerprints preserve the pricing decision that was made;
- vendor rates and infrastructure rates are configurable rather than hardcoded;
- monitoring frequency is configuration of competitor management, not a fake standalone feature;
- tracked competitor count remains the capacity input;
- promo and ownership checks must not bypass tenant privacy.

---

## 8. Data and Prisma

The database is PostgreSQL with Prisma 7 and pgvector support.

Major model groups include:

### Platform and identity

```text
Company
User
SystemRole
TenantUser
PlatformInvitation
AuthSession
audit_logs
```

### Billing

```text
Plan
PlanPriceVersion
Subscription
PaymentTransaction
PromoCode
PromoCodePlan
PromoCodeRedemption
invoices
invoice_items
payment_providerWebhookEvent
AppConfig
```

### Features and custom plans

```text
Feature
PlanFeature
SubscriptionUsage
VendorRate
InfrastructureRate
CustomPlanQuote
CustomPlanQuoteFeature
```

### Product/competitor/market data

```text
products
transactions
inventory
global_competitors
tenant_competitors
competitor_product_mappings
competitor_prices
product_price_history
reviews
sentiment_results
competitor_score_snapshots
```

### Ingestion and AI evidence

```text
data_sources
ingestion_jobs
import_staging_rows
rag_documents_metadata
rag_document_chunks
evidence_records
recommendation_outcomes
demand_forecasts
model_versions
```

The full schema is always authoritative:

```text
prisma/schema.prisma
```

I do not document every column here because that becomes stale faster than the schema itself.

---

## 9. Analytics behavior

For analytics/AI-facing outputs, I preserve unknown/unavailable states.

I do **not** treat missing data as zero unless the business rule explicitly defines it that way.

This is especially important for:

- forecast coverage;
- confidence values;
- market presence/perception;
- sentiment summaries;
- MPI;
- competitor market statistics.

A believable but fabricated value is worse than an explicit unavailable value.

---

## 10. External boundaries

### Stripe

Stripe transport belongs under:

```text
src/modules/subscription/client/payment-providers/stripe/
```

The webhook route is intentionally mounted before JSON parsing.

### CEOPRO AI

AI transport belongs in the client of the domain that owns the feature:

```text
features/client/
dataconnection/client/
pricing/client/
sentiment/client/
mpi/client/
```

The backend owns:

- auth;
- tenant isolation;
- feature checks;
- usage accounting;
- authoritative source data;
- persistence;
- frontend-facing API contracts.

The AI service owns:

- extraction;
- RAG model work;
- pricing recommendation model output;
- sentiment inference;
- MPI computation.

See [`INTEGRATIONS.md`](INTEGRATIONS.md).

---

## 11. Background/triggered AI work

Operations such as:

```text
POST /features/extraction/process-pending
POST /features/sentiment/analyze-pending
```

should not depend on a frontend user guessing when new scraped/ingested data is ready.

The production trigger should come from one of these controlled backend patterns:

- a completion signal/event after a successful scraping/ingestion cycle; or
- a backend worker/scheduler that periodically processes pending rows.

The frontend is not the workflow coordinator for background processing.

---

## 12. Error handling and HTTP safety

The app uses centralized not-found/error middleware and shared error definitions.

Important rules:

- external provider details should not leak unnecessarily to clients;
- validation errors should be structured;
- known domain errors should map predictably;
- unexpected errors should reach the global handler;
- body/upload limits remain configurable;
- CORS is environment-driven;
- `x-powered-by` is disabled;
- basic response security headers are applied.

---

## 13. Stripe webhook ordering

This is a hard rule:

```text
app.use("/stripe/webhooks", stripeRouter);
app.use(express.json(...));
```

The webhook route itself uses:

```text
express.raw({ type: "application/json" })
```

Do not reverse this ordering.

If the body is parsed before signature verification, Stripe webhook verification can fail.

---

## 14. Testing and verification

The repository provides:

```text
tests/
scripts/verify-route-contract.mjs
scripts/verify-security-regressions.mjs
scripts/verify-custom-plan-contract.mjs
scripts/verify-feature-entitlements.mjs
```

The complete validation command is:

```bash
npm run validate
```

That runs Prisma validation, a TypeScript build, and the full test/verification suite.

For changes that touch Stripe or the AI service, static/unit checks are not enough. I also test the real integration in the provider's test environment.

---

## 15. Legacy and duplicate source files

This snapshot contains some older duplicate files/folders from previous refactors, for example old route/controller paths and previous provider locations.

I determine the active implementation from the import graph and `src/app.ts`, not from filename similarity.

Until legacy files are removed after a dedicated import audit:

- do not document an endpoint just because a route file exists;
- do not edit both old and new copies automatically;
- prefer the files imported by the active domain `index.ts` and `app.ts`.

This documentation follows the active import graph.

---

## 16. Decisions I want future changes to respect

When extending this backend, I want these rules preserved:

- Keep business logic out of routes.
- Keep Prisma access out of external-service clients.
- Keep provider transport out of repositories.
- Keep tenant/security/entitlement enforcement in CEOPRO.
- Keep pricing inputs server-authoritative.
- Do not hardcode vendor/infrastructure costs that are designed to be configurable.
- Do not invent fake metrics when data is incomplete.
- Do not create standalone features for values that are configuration of another feature.
- Keep RAG/knowledge-base document flows conceptually separate from business-data ingestion even when they reuse extraction infrastructure.
- Keep Stripe webhook raw-body handling intact.
- Keep API changes deliberate; moving source files must not silently change routes/contracts.
