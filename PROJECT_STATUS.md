# Project Status and Roadmap

I use this file as the living record of **what I have completed, what I am working on now, what I plan to do next, and which decisions are still open**.

I want this document to stay structured enough that I can keep adding work without turning it into another pile of disconnected notes.

---

## How I maintain this file

I use these statuses:

```text
✅ Done
🟡 In progress
⬜ Next / planned
⚠️ Decision required
⏸ Deferred
```

When I complete a meaningful backend change, I update:

1. the relevant section below;
2. the decision log if behavior/architecture changed;
3. the production-readiness checklist if the change affects deployment;
4. the canonical architecture/API/integration doc if the public truth changed.

---

# Current objective

My current backend objective is:

> Prepare the CEOPRO AI backend for production without losing the feature-domain structure, tenant/security boundaries, server-authoritative billing rules, and explicit external AI contracts.

I am reducing documentation/source ambiguity, finishing integration boundaries, and validating each production-critical flow against the real database/provider behavior.

---

# Completed foundations

## Architecture

- ✅ Feature-domain organization is established around `index.ts`, `route/`, `controller/`, `service/`, `repo/`, `client/`, and `types/` where each layer is actually needed.
- ✅ Major domains have dedicated ownership instead of putting all behavior in one shared feature controller.
- ✅ Pricing, sentiment, and MPI have dedicated AI-client boundaries.
- ✅ RAG/extraction transport is separated from feature entitlement/usage rules.
- ✅ Stripe provider code is isolated under the subscription domain.
- ✅ The Stripe webhook raw-body ordering is preserved.

## Security and tenancy

- ✅ Tenant membership is checked server-side.
- ✅ Platform administration uses platform role + permission checks.
- ✅ CORS is environment-driven.
- ✅ JWT verification is centralized.
- ✅ Stripe customer reuse is tenant-aware.
- ✅ Webhook signature validation uses the raw request body.
- ✅ Global JSON error handling exists.
- ✅ Request body/upload sizes are configurable.

## Subscription and billing

- ✅ Plans and plan-feature assignments are server managed.
- ✅ Subscription checkout/change/cancel flows exist.
- ✅ Invoices are exposed through the tenant API.
- ✅ Promo code validation/linking flows exist.
- ✅ Custom-plan configurator/preview/manual-review/checkout flows exist.
- ✅ Manual quote lifecycle exists.
- ✅ Vendor rates exist.
- ✅ Infrastructure rates exist.
- ✅ Custom-plan pricing policy exists.
- ✅ Pricing snapshots/fingerprints protect automatic quote decisions.
- ✅ Accepted/private custom-plan protections are part of the current design.
- ✅ Monitoring frequency is configuration, not a fake standalone feature.

## Features and usage

- ✅ Feature catalog and plan-feature links exist.
- ✅ Feature access and metered entitlement checks are separate concepts.
- ✅ RAG assistant flow exists.
- ✅ Document extraction flow exists.
- ✅ Data-connection ingestion flow exists.
- ✅ Sentiment analysis/summary endpoints exist.
- ✅ MPI endpoint exists.
- ✅ Demand-prediction read endpoints exist.
- ✅ Dashboard aggregation exists.
- ✅ Competitor management exists.
- ✅ Opportunity/leaderboard endpoint exists.
- ✅ Market-intelligence endpoint exists.
- ✅ AI pricing recommendation endpoint exists.

## Testing/verification

- ✅ Unit tests exist.
- ✅ Route-contract verification exists.
- ✅ Security regression verification exists.
- ✅ Custom-plan contract verification exists.
- ✅ Feature-entitlement verification exists.
- ✅ `npm run validate` provides one full local validation command.

---

# In progress / immediate attention

## 1. Verification scripts after the domain refactor

**Status:** 🟡 In progress

The current source snapshot has two documentation/structure-related verification mismatches:

1. `scripts/verify-route-contract.mjs` expects `router.get("/",` as one exact text snippet, while the active `features-management.route.ts` formats that call across multiple lines. The route itself exists; the verifier is formatting-sensitive.
2. `scripts/verify-feature-entitlements.mjs` still expects `requireFeatureAccess("sentiment_analysis")` inside the shared `features/route/features.route.ts`, but sentiment now owns its dedicated router under `src/modules/sentiment`.

I do not want to weaken these checks; I want to update them so they verify the current architecture instead of legacy file placement/formatting.

### Next actions

- [ ] Make route-contract checks resilient to harmless formatting changes.
- [ ] Point sentiment entitlement verification at the dedicated sentiment route.
- [ ] Run the complete `npm run validate` suite after the script updates.
- [ ] Keep the checks behavior-focused rather than location-sensitive where possible.

---

## 2. Production AI workflow ownership

**Status:** 🟡 In progress

I need the final production trigger for:

```text
POST /features/extraction/process-pending
POST /features/sentiment/analyze-pending
```

My intended model is:

```text
scraping/ingestion completion
        ↓
trusted event or scheduled worker
        ↓
process pending work
        ↓
persist results
        ↓
frontend reads normal backend endpoints
```

The frontend should not detect spider completion itself.

### Next actions

- [ ] Decide which completion events the AI/scraping side can emit.
- [ ] Decide whether I also want a periodic backend worker as a fallback.
- [ ] Define retry/idempotency behavior.
- [ ] Define batch sizes and operational limits.
- [ ] Add monitoring/logging for failed background runs.

---

## 3. Pricing entitlement gate

**Status:** ⚠️ Decision required

The active route currently has the `ai_pricing` entitlement middleware commented out:

```text
POST /features/pricing/recommend
```

Authentication + tenant context are still enforced.

### I need to decide

- [ ] Re-enable `requireEntitlement("ai_pricing")`; or
- [ ] intentionally make pricing recommendation available under another feature/commercial rule.

Whichever choice I make, I should update the route, feature catalog, pricing/usage behavior, tests, and API docs together.

---

## 4. MPI / market-perception entitlement gate

**Status:** ⚠️ Decision required

The active MPI route currently has the `market_perception` feature-access middleware commented out:

```text
GET /features/mpi/summary
```

### I need to decide

- [ ] Re-enable the `market_perception` feature gate; or
- [ ] intentionally include MPI under a broader feature such as market intelligence.

I should not leave the commercial meaning ambiguous in production.

---

## 5. Auth router mounting

**Status:** ⚠️ Decision required

`src/modules/auth` contains:

```text
POST /login
GET  /session
POST /logout
GET  /invitations/:token
POST /invitations/:token/accept
```

but the current `src/app.ts` does not mount the auth router.

### I need to decide

- [ ] Mount the auth domain at the intended base path and test it end to end; or
- [ ] remove/replace the unused source if authentication is intentionally handled elsewhere.

Until then, I do not document those handlers as live routes.

---

## 6. Legacy duplicate source cleanup

**Status:** 🟡 In progress

The repository still contains some duplicate/older source paths from previous refactors.

Examples include old route/controller/provider locations and the old misspelled opportunity folder.

The active code is determined by imports, but leaving duplicates makes maintenance harder.

### Safe cleanup plan

- [ ] Build a complete import graph.
- [ ] Confirm each legacy file has no active imports.
- [ ] Delete inactive duplicates in a dedicated cleanup commit.
- [ ] Run `npm run validate`.
- [ ] Compare the mounted route table before/after.
- [ ] Do not combine this cleanup with business-logic changes.

---

# Next production-readiness phase

## Database

- ⬜ Run migrations against a clean production-like database.
- ⬜ Verify pgvector extension availability.
- ⬜ Verify required roles/catalog/configuration data after migrations.
- ⬜ Define exactly which bootstrap scripts are allowed in production.
- ⬜ Keep destructive feature bootstrap explicitly guarded.
- ⬜ Validate tenant/RLS behavior against real multi-tenant data.

## Stripe

- ⬜ Test onboarding/bootstrap against Stripe test mode.
- ⬜ Test new checkout.
- ⬜ Test existing customer reuse across different tenants.
- ⬜ Test invoice/payment webhook retries.
- ⬜ Test active/trialing/cancel-at-period-end flows.
- ⬜ Test plan upgrade/downgrade/mixed transitions.
- ⬜ Test fixed and percentage promotions.
- ⬜ Test test-clock behavior where used.
- ⬜ Verify webhook signatures through the real reverse proxy/deployment ingress.

## AI service

- ⬜ Disable mocks in the production environment.
- ⬜ Validate RAG success/failure/usage accounting.
- ⬜ Validate extraction upload and persisted object metadata.
- ⬜ Validate pending extraction processing.
- ⬜ Validate pricing `OK` and `UNKNOWN` responses.
- ⬜ Validate sentiment `OK`, low-sample, and pending-analysis flows.
- ⬜ Validate MPI `OK` and `UNKNOWN`.
- ⬜ Verify timeouts and malformed-response handling.
- ⬜ Verify forwarded auth context with the deployed AI service.

## Analytics/data quality

- ⬜ Validate dashboard metrics with production-shaped data.
- ⬜ Validate forecast coverage rules over real 30-day periods.
- ⬜ Validate market-intelligence score ranges and missing-data behavior.
- ⬜ Validate competitor mappings/prices before displaying derived rankings.
- ⬜ Keep `—`/unknown states when the backend genuinely lacks enough evidence.

## Observability

- ⬜ Define structured logs for external-service failures.
- ⬜ Track background ingestion/sentiment worker failures.
- ⬜ Track webhook failures/retries.
- ⬜ Add alerts for repeatedly failing AI/provider calls where appropriate.

---

# Product/architecture decisions I want to preserve

These are not temporary TODOs. They are design choices.

## Feature and pricing decisions

- `rag_assistant` is a metered token-oriented capability.
- Document extraction and document storage are separate concerns.
- Boolean feature access and numeric usage limits are not the same thing.
- Tracked competitor count is a capacity input.
- Monitoring frequency belongs to competitor-management configuration.
- Vendor/infrastructure costs are configurable inputs, not hardcoded constants.
- Custom-plan quote calculations stay server-authoritative.
- Accepted custom plans should not silently change underneath a customer.

## Data decisions

- Missing analytical data is not automatically zero.
- Incomplete forecast coverage should remain incomplete.
- Unknown sentiment/MPI should remain explicit.
- Production responses should not silently use mock data.

## Integration decisions

- CEOPRO owns auth, tenant rules, entitlements, persistence, and billing policy.
- AI services own AI computation.
- Stripe owns provider state, not CEOPRO authorization.
- Frontend code should not coordinate backend scraping/worker completion.

## Code-structure decisions

- Prefer feature domains.
- Keep controllers thin.
- Keep Prisma in repositories.
- Keep third-party transport in clients.
- Avoid classes when the domain is already functional.
- Do not create empty layers just for appearance.
- Preserve API contracts during structural refactors.

---

# Open decisions

I use this table for decisions that need a clear answer before production.

| Decision                                        | Status             | Owner           | Notes                                               |
| ----------------------------------------------- | ------------------ | --------------- | --------------------------------------------------- |
| Final trigger for extraction pending processing | ⚠️ Open            | Backend + AI    | Completion event vs scheduled worker, or both       |
| Final trigger for sentiment pending processing  | ⚠️ Open            | Backend + AI    | Should follow scraping/review ingestion completion  |
| Pricing feature gate                            | ⚠️ Open            | Backend/Product | `ai_pricing` gate is currently commented out        |
| MPI feature gate                                | ⚠️ Open            | Backend/Product | `market_perception` gate is currently commented out |
| Auth router public mount                        | ⚠️ Open            | Backend         | Source exists but is not mounted                    |
| Legacy duplicate source removal                 | 🟡 Planned cleanup | Backend         | Must be import/route verified before deletion       |

Add rows here instead of starting a new Markdown file for each decision.

---

# Production readiness checklist

I should not call the backend production-ready until the applicable items are green.

## Build and schema

- [ ] `npm ci`
- [ ] `npm run prisma:validate`
- [ ] `npm run build`
- [ ] `npm test`
- [ ] `npm run validate`
- [ ] production migrations tested from a clean database

## Security

- [ ] no real secrets committed
- [ ] production JWT secrets rotated and stored securely
- [ ] CORS production origins explicit
- [ ] upload/body limits appropriate
- [ ] tenant isolation verified with cross-tenant tests
- [ ] platform permissions verified
- [ ] provider errors do not leak secrets

## Billing

- [ ] Stripe test end-to-end passed
- [ ] webhook retries passed
- [ ] idempotency passed
- [ ] plan transitions passed
- [ ] promo-code isolation passed
- [ ] custom-plan privacy/immutability passed

## AI/data

- [ ] mocks disabled
- [ ] real AI auth works
- [ ] all AI contracts validated
- [ ] worker triggers implemented
- [ ] no fake fallback data in production
- [ ] analytics no-data states verified

## Deployment

- [ ] environment variables documented in deployment system
- [ ] database backups/restore procedure defined
- [ ] application health/log monitoring configured
- [ ] provider/AI failure monitoring configured

---

# Change log

I use this for meaningful backend milestones, not every commit.

## YYYY-MM-DD — Title

**Status:** ✅ Done / 🟡 In progress / ⬜ Planned

### What I changed

- ...

### Why I changed it

- ...

### What behavior must remain

- ...

### Verification

- ...

### Follow-up

- ...

---

# Decision log

When I make a decision that future maintainers need to understand, I add it here.

## DEC-XXX — Decision title

**Date:** YYYY-MM-DD  
**Status:** Accepted / Revisit / Rejected

### Context

What problem or ambiguity did I have?

### Decision

What did I decide?

### Why

Why is this the right behavior for CEOPRO?

### Consequences

What code/config/product behavior depends on this decision?

### Revisit when

What future condition would justify changing the decision?

---

# Notes inbox

Temporary notes can go here while I am actively working:

```text
- YYYY-MM-DD:
  - ...
```

When a note becomes a real decision, completed milestone, or next action, I move it into the structured section above instead of letting this become another permanent dump.
