# API Reference

This is the canonical route index for the CEOPRO AI backend.

I build this list from the **currently mounted routers**, not from every route file that happens to exist in the repository. That distinction matters because the codebase still contains some legacy/duplicate source files and an `auth` module that is not mounted by `src/app.ts`.

Current server behavior has **127 mounted method/path declarations**.

---

## How to read access labels

All protected routes use the shared backend authentication/authorization middleware.

Common labels in the tables:

| Label                        | Meaning                                                             |
| ---------------------------- | ------------------------------------------------------------------- |
| `Public`                     | No authentication middleware on the active route                    |
| `Tenant`                     | Authenticated user + active tenant context                          |
| `Platform` / `Platform role` | Authenticated platform membership accepted by `requirePlatformRole` |
| `` `permission.name` ``      | Additional platform permission required                             |
| `` `manage_billing` ``       | Tenant billing permission required                                  |
| `Feature access`             | Feature must be enabled/available                                   |
| `Entitlement`                | Feature must be enabled and satisfy the current metered access rule |
| `Stripe signature`           | Provider webhook signature validation, not JWT auth                 |

Base URL is the backend origin itself; there is currently no global `/api` prefix.

Example local origin:

```text
http://localhost:5000
```

---

## Important route notes

### The auth source module is not live

`src/modules/auth` contains handlers for:

```text
POST /login
GET  /session
POST /logout
GET  /invitations/:token
POST /invitations/:token/accept
```

but `src/app.ts` does **not** currently mount the auth router. I therefore do not include those handlers in the live route table below.

### Platform-admin owner routes are live through nesting

`platform-admin` mounts the `owner-portal` router after platform authentication/role middleware. Therefore routes such as:

```text
/platform-admin/overview
/platform-admin/companies
/platform-admin/users
```

are live even though `owner-portal` is not mounted directly in `app.ts`.

### Stripe webhook is mounted before JSON parsing

`POST /stripe/webhooks` is intentionally mounted before `express.json()` so the raw body is available for signature verification.

---

## Health

| Method | Path | Access | Purpose                    |
| ------ | ---- | ------ | -------------------------- |
| `GET`  | `/`  | Public | Basic API-running response |

## Platform admin: billing facade

| Method   | Path                                                             | Access                   | Purpose                                 |
| -------- | ---------------------------------------------------------------- | ------------------------ | --------------------------------------- |
| `GET`    | `/platform-admin/me`                                             | Platform role            | Return the current platform principal   |
| `GET`    | `/platform-admin/billing/tenants`                                | `billing.read`           | List tenant/company billing records     |
| `GET`    | `/platform-admin/billing/subscriptions`                          | `subscriptions.read`     | List platform subscriptions             |
| `GET`    | `/platform-admin/billing/plans`                                  | `billing.read`           | List plans from the platform facade     |
| `POST`   | `/platform-admin/billing/plans`                                  | `billing.manage`         | Create a plan                           |
| `PATCH`  | `/platform-admin/billing/plans/:id`                              | `billing.manage`         | Update a plan                           |
| `GET`    | `/platform-admin/billing/infrastructure-rates`                   | `billing.read`           | List infrastructure cost rates          |
| `POST`   | `/platform-admin/billing/infrastructure-rates`                   | `billing.pricing.manage` | Create an infrastructure rate           |
| `PATCH`  | `/platform-admin/billing/infrastructure-rates/:id`               | `billing.pricing.manage` | Update an infrastructure rate           |
| `GET`    | `/platform-admin/billing/custom-plans`                           | `billing.read`           | List custom plans                       |
| `PATCH`  | `/platform-admin/billing/custom-plans/:id/status`                | `billing.manage`         | Enable/disable a custom plan            |
| `GET`    | `/platform-admin/billing/custom-quotes`                          | `billing.read`           | List custom-plan quotes                 |
| `POST`   | `/platform-admin/billing/custom-quotes`                          | `billing.manage`         | Create a custom-plan quote for a tenant |
| `GET`    | `/platform-admin/billing/custom-quotes/:id`                      | `billing.read`           | Read a custom-plan quote                |
| `PATCH`  | `/platform-admin/billing/custom-quotes/:id`                      | `billing.manage`         | Update a custom-plan quote              |
| `POST`   | `/platform-admin/billing/custom-quotes/:id/calculate`            | `billing.manage`         | Calculate/recalculate a quote           |
| `POST`   | `/platform-admin/billing/custom-quotes/:id/approve`              | `billing.manage`         | Approve a quote                         |
| `POST`   | `/platform-admin/billing/custom-quotes/:id/send`                 | `billing.manage`         | Send a quote to the customer            |
| `POST`   | `/platform-admin/billing/custom-quotes/:id/reject`               | `billing.manage`         | Reject a quote                          |
| `GET`    | `/platform-admin/billing/pricing-policy`                         | `billing.read`           | Read custom-plan pricing policy         |
| `PATCH`  | `/platform-admin/billing/pricing-policy`                         | `billing.pricing.manage` | Update custom-plan pricing policy       |
| `GET`    | `/platform-admin/billing/vendor-rates`                           | `billing.read`           | List vendor rate cards                  |
| `POST`   | `/platform-admin/billing/vendor-rates`                           | `billing.pricing.manage` | Create a vendor rate                    |
| `PATCH`  | `/platform-admin/billing/vendor-rates/:id`                       | `billing.pricing.manage` | Update a vendor rate                    |
| `GET`    | `/platform-admin/billing/promo-codes`                            | `billing.read`           | List promo codes                        |
| `POST`   | `/platform-admin/billing/promo-codes`                            | `billing.manage`         | Create a promo code                     |
| `PATCH`  | `/platform-admin/billing/promo-codes/:id`                        | `billing.manage`         | Update a promo code                     |
| `POST`   | `/platform-admin/billing/promo-codes/:promoCodeId/plans/:planId` | `billing.manage`         | Link a promo code to a plan             |
| `GET`    | `/platform-admin/billing/features`                               | `billing.read`           | List feature catalog                    |
| `GET`    | `/platform-admin/billing/features/:id`                           | `billing.read`           | Read one feature                        |
| `POST`   | `/platform-admin/billing/features`                               | `billing.manage`         | Create a feature                        |
| `DELETE` | `/platform-admin/billing/features/:id`                           | `billing.manage`         | Delete a feature                        |
| `PATCH`  | `/platform-admin/billing/features/:id`                           | `billing.manage`         | Update a feature                        |
| `GET`    | `/platform-admin/billing/plans/:plan_id/features`                | `billing.read`           | List features attached to a plan        |
| `POST`   | `/platform-admin/billing/plans/:plan_id/features`                | `billing.manage`         | Attach a feature to a plan              |
| `DELETE` | `/platform-admin/billing/plans/:plan_id/features/:feature_id`    | `billing.manage`         | Remove a feature from a plan            |
| `PATCH`  | `/platform-admin/billing/plans/:plan_id/features/:feature_id`    | `billing.manage`         | Update the plan-feature limit           |

## Platform admin: owner portal

| Method | Path                                     | Access                    | Purpose                            |
| ------ | ---------------------------------------- | ------------------------- | ---------------------------------- |
| `GET`  | `/platform-admin/overview`               | `platform.overview.read`  | Read platform overview metrics     |
| `GET`  | `/platform-admin/companies`              | `companies.read`          | List companies/tenants             |
| `GET`  | `/platform-admin/companies/:id`          | `companies.read`          | Read one company                   |
| `POST` | `/platform-admin/companies/:id/metadata` | `companies.update`        | Update company metadata            |
| `POST` | `/platform-admin/companies/:id/status`   | `companies.status.manage` | Change company platform status     |
| `GET`  | `/platform-admin/users`                  | `users.read`              | List users                         |
| `GET`  | `/platform-admin/users/:id`              | `users.read`              | Read one user                      |
| `POST` | `/platform-admin/users/:id/status`       | `users.manage`            | Change user platform status        |
| `GET`  | `/platform-admin/admin-team`             | `adminTeam.read`          | List platform admin team           |
| `POST` | `/platform-admin/admin-team/new/invite`  | `adminTeam.invite`        | Invite a platform admin            |
| `POST` | `/platform-admin/admin-team/:id/role`    | `adminTeam.roles.manage`  | Change an admin-team role          |
| `POST` | `/platform-admin/admin-team/:id/status`  | `adminTeam.roles.manage`  | Change an admin-team member status |
| `POST` | `/platform-admin/admin-team/:id/remove`  | `adminTeam.remove`        | Remove an admin-team member        |
| `POST` | `/platform-admin/admin-team/:id/resend`  | `adminTeam.invite`        | Resend a platform invitation       |
| `POST` | `/platform-admin/admin-team/:id/cancel`  | `adminTeam.remove`        | Cancel a platform invitation       |
| `GET`  | `/platform-admin/audit-logs`             | `auditLogs.read`          | Read platform audit logs           |
| `GET`  | `/platform-admin/settings`               | `platformSettings.read`   | Read platform settings             |
| `POST` | `/platform-admin/settings/new/update`    | `platformSettings.manage` | Update platform settings           |
| `GET`  | `/platform-admin/me/sessions`            | Platform role             | List my active sessions            |
| `POST` | `/platform-admin/me/profile`             | Platform role             | Update my profile                  |
| `POST` | `/platform-admin/me/password`            | Platform role             | Change my password                 |
| `POST` | `/platform-admin/me/revoke`              | Platform role             | Revoke one of my sessions          |
| `POST` | `/platform-admin/me/revokeOthers`        | Platform role             | Revoke my other sessions           |

## Subscription and billing

| Method  | Path                                                   | Access                              | Purpose                                                   |
| ------- | ------------------------------------------------------ | ----------------------------------- | --------------------------------------------------------- |
| `POST`  | `/subscription`                                        | Tenant + `all`                      | Initialize the shared subscription/Stripe onboarding flow |
| `GET`   | `/subscription/plans`                                  | Public                              | List plans                                                |
| `POST`  | `/subscription/plans`                                  | Platform + `billing.manage`         | Create a plan                                             |
| `PATCH` | `/subscription/plans/:id`                              | Platform + `billing.manage`         | Update a plan                                             |
| `GET`   | `/subscription/promo-codes`                            | Platform + `billing.read`           | List promo codes                                          |
| `POST`  | `/subscription/promo-codes`                            | Platform + `billing.manage`         | Create a promo code                                       |
| `POST`  | `/subscription/promo-codes/validate`                   | Tenant + `manage_billing`           | Validate a promo code against the requested plan/context  |
| `PATCH` | `/subscription/promo-codes/:id`                        | Platform + `billing.manage`         | Update a promo code                                       |
| `POST`  | `/subscription/promo-codes/:promoCodeId/plans/:planId` | Platform + `billing.manage`         | Link promo code to plan                                   |
| `GET`   | `/subscription/current`                                | Tenant                              | Read current subscription                                 |
| `PATCH` | `/subscription/current/cancel`                         | Tenant + `manage_billing`           | Schedule/cancel the current subscription                  |
| `PATCH` | `/subscription/current/cancel/undo`                    | Tenant + `manage_billing`           | Undo scheduled cancellation                               |
| `PATCH` | `/subscription/current/plan`                           | Tenant + `manage_billing`           | Change/schedule plan                                      |
| `POST`  | `/subscription/checkout`                               | Tenant + `manage_billing`           | Create subscription checkout                              |
| `GET`   | `/subscription/invoices`                               | Tenant                              | List tenant invoices                                      |
| `GET`   | `/subscription/custom-plans/configurator`              | Tenant                              | Read available custom-plan configuration inputs           |
| `POST`  | `/subscription/custom-plans/preview`                   | Tenant                              | Calculate a server-authoritative custom-plan preview      |
| `POST`  | `/subscription/custom-plans/manual-review`             | Tenant + `manage_billing`           | Submit a custom-plan request for manual review            |
| `POST`  | `/subscription/custom-plans/checkout`                  | Tenant + `manage_billing`           | Checkout/apply an eligible instant custom plan            |
| `GET`   | `/subscription/custom-plans/pricing-policy`            | Platform + `billing.read`           | Read internal custom-plan pricing policy                  |
| `PATCH` | `/subscription/custom-plans/pricing-policy`            | Platform + `billing.pricing.manage` | Update internal pricing policy                            |
| `GET`   | `/subscription/custom-plans`                           | Tenant                              | List tenant-visible custom plans                          |
| `GET`   | `/subscription/custom-plans/quotes/:id/offer`          | Tenant                              | Read a customer-safe quote offer                          |
| `POST`  | `/subscription/custom-plans/quotes/:id/accept`         | Tenant + `manage_catalog`           | Accept a manual quote (current permission in code)        |
| `GET`   | `/subscription/custom-plans/quotes`                    | Platform + `billing.read`           | List internal custom-plan quotes                          |
| `POST`  | `/subscription/custom-plans/quotes`                    | Platform + `billing.manage`         | Create an internal custom-plan quote                      |
| `GET`   | `/subscription/custom-plans/quotes/:id`                | Platform + `billing.manage`         | Read an internal quote                                    |
| `PATCH` | `/subscription/custom-plans/quotes/:id`                | Platform + `billing.manage`         | Update an internal quote                                  |
| `POST`  | `/subscription/custom-plans/quotes/:id/calculate`      | Platform + `billing.manage`         | Calculate/recalculate an internal quote                   |
| `POST`  | `/subscription/custom-plans/quotes/:id/approve`        | Platform + `billing.manage`         | Approve an internal quote                                 |
| `POST`  | `/subscription/custom-plans/quotes/:id/send`           | Platform + `billing.manage`         | Send an internal quote                                    |
| `POST`  | `/subscription/custom-plans/quotes/:id/reject`         | Platform + `billing.manage`         | Reject an internal quote                                  |
| `GET`   | `/subscription/custom-plans/vendor-rates`              | Platform + `billing.read`           | List vendor rate cards                                    |
| `POST`  | `/subscription/custom-plans/vendor-rates`              | Platform + `billing.pricing.manage` | Create vendor rate                                        |
| `PATCH` | `/subscription/custom-plans/vendor-rates/:id`          | Platform + `billing.pricing.manage` | Update vendor rate                                        |
| `POST`  | `/stripe/webhooks`                                     | Stripe signature                    | Receive Stripe webhook events using the raw request body  |

## Features and entitlements

| Method   | Path                                   | Access                                     | Purpose                                               |
| -------- | -------------------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| `GET`    | `/features`                            | Platform + `billing.read`                  | List feature catalog                                  |
| `GET`    | `/features/:id`                        | Platform + `billing.read`                  | Read one feature                                      |
| `POST`   | `/features`                            | Platform + `billing.manage`                | Create feature                                        |
| `DELETE` | `/features/:id`                        | Platform + `billing.manage`                | Delete feature                                        |
| `PATCH`  | `/features/:id`                        | Platform + `billing.manage`                | Update feature                                        |
| `GET`    | `/plans/:plan_id/features`             | Platform + `billing.read`                  | List features attached to a plan                      |
| `POST`   | `/plans/:plan_id/features`             | Platform + `billing.manage`                | Attach feature to plan                                |
| `DELETE` | `/plans/:plan_id/features/:feature_id` | Platform + `billing.manage`                | Detach feature from plan                              |
| `PATCH`  | `/plans/:plan_id/features/:feature_id` | Platform + `billing.manage`                | Update plan-feature limit                             |
| `GET`    | `/subscriptions/current/usage`         | Tenant                                     | Read current subscription usage/entitlement dashboard |
| `GET`    | `/features/rag/documents`              | Tenant + `document_extraction` entitlement | List tenant RAG documents                             |
| `GET`    | `/features/rag/chunks/:chunk_id`       | Tenant + `rag_assistant` access            | Read one tenant-scoped RAG chunk                      |
| `POST`   | `/features/rag/query`                  | Tenant + `rag_assistant` entitlement       | Query the RAG assistant                               |
| `POST`   | `/features/extraction/upload`          | Tenant + `document_extraction` entitlement | Upload a document for extraction                      |
| `POST`   | `/features/extraction/process-pending` | Tenant + `document_extraction` access      | Ask the AI service to process pending extraction work |

## Data, analytics, competitors and forecasting

| Method | Path                              | Access                                     | Purpose                                                    |
| ------ | --------------------------------- | ------------------------------------------ | ---------------------------------------------------------- |
| `GET`  | `/companies/:companyId/dashboard` | Tenant                                     | Read aggregated dashboard metrics (`periodDays` supported) |
| `GET`  | `/forecasting/demand`             | Tenant + `demand_prediction` access        | Read demand-forecast overview                              |
| `GET`  | `/forecasting/demand/:productId`  | Tenant + `demand_prediction` access        | Read one product forecast detail                           |
| `POST` | `/data-connection/sources`        | Tenant + `data_integration` entitlement    | Create a persistent data-source record                     |
| `GET`  | `/data-connection`                | Tenant                                     | Read data-connection overview/recent imports               |
| `POST` | `/data-connection`                | Tenant + `document_extraction` entitlement | Upload a business-data file for ingestion                  |
| `GET`  | `/market-intelligence`            | Tenant                                     | Read market-intelligence overview/metrics                  |
| `GET`  | `/competitors`                    | Tenant                                     | List tracked competitors                                   |
| `POST` | `/competitors`                    | Tenant                                     | Create/link a tracked competitor                           |
| `GET`  | `/competitors/:competitorId`      | Tenant                                     | Read competitor profile/activity                           |
| `GET`  | `/leaderboard`                    | Tenant                                     | Read competitor opportunity/leaderboard view               |

## AI feature routes

| Method | Path                                  | Access                                                        | Purpose                              |
| ------ | ------------------------------------- | ------------------------------------------------------------- | ------------------------------------ |
| `POST` | `/features/pricing/recommend`         | Tenant; pricing entitlement currently not enforced in route   | Get AI pricing recommendation        |
| `POST` | `/features/sentiment/analyze-pending` | Tenant + `sentiment_analysis` entitlement                     | Analyze pending sentiment rows       |
| `GET`  | `/features/sentiment/summary`         | Tenant + `sentiment_analysis` access                          | Read sentiment summary               |
| `GET`  | `/features/mpi/summary`               | Tenant; market-perception access gate currently commented out | Read Market Perception Index summary |

---

# Route groups in context

## Platform administration

All `/platform-admin/*` routes first pass through:

```text
authenticateUser
→ requireTenant
→ requirePlatformRole
```

Specific routes then add their permission checks.

The billing facade intentionally delegates to the owning subscription/features domains instead of duplicating those business rules.

---

## Subscription

Main public/tenant surface:

```text
/subscription/plans
/subscription/current
/subscription/checkout
/subscription/invoices
/subscription/promo-codes
/subscription/custom-plans
```

Plan listing is currently public.

Mutating global billing/catalog state is platform-protected.

Tenant billing actions use tenant permission checks such as `manage_billing`.

One current inconsistency is worth keeping visible:

```text
POST /subscription/custom-plans/quotes/:id/accept
```

uses `manage_catalog` in the active code even though most self-service custom-plan billing actions use `manage_billing`.

I treat that as a current-code fact, not something the documentation should silently “correct.”

---

## Feature catalog and usage

There are two related API areas:

### Platform feature catalog

```text
/features
/plans/:plan_id/features
```

These manage global features and plan-feature relationships.

### Tenant feature operations

```text
/features/rag/*
/features/extraction/*
/features/sentiment/*
/features/mpi/*
/features/pricing/*
/subscriptions/current/usage
```

These operate in tenant context and may add feature/entitlement checks.

---

## Analytics/data endpoints

The analytics-facing routes are currently:

```text
/companies/:companyId/dashboard
/forecasting/demand
/forecasting/demand/:productId
/market-intelligence
/competitors
/competitors/:competitorId
/leaderboard
/data-connection
```

Even where a route includes a `:companyId`, tenant middleware remains the real server-side boundary. A path parameter must never be treated as authorization by itself.

---

# Current feature-gating exceptions

Two active routes currently have their intended feature middleware commented out:

## Pricing

```text
POST /features/pricing/recommend
```

The route enforces authentication + tenant context, but the `ai_pricing` entitlement middleware is commented in source.

## MPI

```text
GET /features/mpi/summary
```

The route enforces authentication + tenant context, but the `market_perception` feature-access middleware is commented in source.

I track both decisions explicitly in [`PROJECT_STATUS.md`](PROJECT_STATUS.md) so they do not disappear as undocumented behavior.

---

# Query/body validation

Routes use domain Zod schemas and shared validation middleware where implemented.

Common patterns include:

```text
validateBody(...)
validateParams(...)
validateQuery(...)
```

The full field-level request/response contract should be read from the active domain `types/` schemas when implementation detail is needed.

I keep this API document focused on navigation, access, and route purpose so it remains maintainable.

---

# Source of truth

When this document and source code disagree, use this order:

1. `src/app.ts` — what top-level routers are mounted.
2. Domain `index.ts` — how the domain composes its active routes.
3. Active `route/*.ts` — method/path/middleware.
4. Domain `types/` — validation contracts.
5. Controller/service/repo — behavior.
6. This document — human navigation/reference.

After changing public routes, I update this file in the same change.
