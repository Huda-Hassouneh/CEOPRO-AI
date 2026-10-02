# CEOPRO AI — Project Progress Checklist

> Simple project-status view for quickly seeing what is done, what is currently being worked on, and what is still left before production readiness.

## Status

- [x] Done
- [ ] Not completed yet
- 🟡 Currently being worked on

---

# 🟡 Doing Now

- [ ] 🟡 **Subscription and billing UX hardening**
  - [ ] Confirm subscription success only for `active` and `trialing` states.
  - [ ] Keep `pending` as a processing state while webhook/payment completion is still in progress.
  - [ ] Add correct UX for `past_due` and `payment_failed`.
  - [ ] Add correct UX for `paused` subscriptions.
  - [ ] Add correct UX for `cancelled` / `canceled` and `expired` subscriptions.
  - [ ] Fail safely for unknown subscription statuses.
  - [ ] Improve failed-payment recovery instead of sending customers into duplicate checkout.
  - [ ] Verify renewal failure and recovery behavior.
  - [ ] Verify insufficient-funds and card-decline behavior.
  - [ ] Verify 3DS/SCA success, failure, and abandonment behavior.
  - [ ] Verify trial-to-paid and trial-end payment-failure behavior.
  - [ ] Verify webhook-delay and duplicate-webhook behavior.
  - [ ] Verify promo-code payment outcomes, including partial and zero-dollar invoices.
  - [ ] Run the full Stripe test-mode subscription scenario matrix.

- [ ] 🟡 **Production-readiness cleanup and verification**
  - [ ] Update verification scripts that still depend on old route/file locations.
  - [ ] Remove confirmed legacy duplicate source files safely.
  - [ ] Run the full validation suite after current fixes.

---

# ⬜ To Do Next

## Customer / Product Experience

- [ ] **Alert / notification system**
  - [ ] Define which customer/admin events should generate alerts.
  - [ ] Add alert delivery and persistence rules.
  - [ ] Add user-facing alert/notification UI where required.

- [ ] **Invitation system completion**
  - [ ] Finalize the public auth/invitation route mounting decision.
  - [ ] Complete invitation acceptance flow end to end.
  - [ ] Verify invitation security, expiration, and tenant/role handling.

- [ ] **Subscription payment-recovery experience**
  - [ ] Provide a clear recovery action for `past_due` / `payment_failed` customers.
  - [ ] Make sure customers repair the existing subscription instead of creating a duplicate one.
  - [ ] Verify access restoration after successful payment recovery.

## AI / Background Processing

- [ ] Finalize the production trigger for extraction pending processing.
- [ ] Finalize the production trigger for sentiment pending processing.
- [ ] Decide whether to use completion events, scheduled workers, or both.
- [ ] Add retry/idempotency rules for background processing.
- [ ] Add batch-size and operational limits.
- [ ] Add monitoring/logging for failed background jobs.

## Feature / Commercial Decisions

- [ ] Decide whether `ai_pricing` has its own entitlement gate or belongs under another commercial feature.
- [ ] Decide whether `market_perception` has its own feature gate or is included under Market Intelligence.
- [ ] Update feature catalog, tests, pricing behavior, and API docs after those decisions.

## Stripe / Billing Production Validation

- [ ] Test onboarding/bootstrap with Stripe test mode.
- [ ] Test successful new checkout.
- [ ] Test insufficient funds and generic declines.
- [ ] Test 3DS/SCA required, success, failure, and abandonment.
- [ ] Test trials and trial-end payment behavior.
- [ ] Test asynchronous browser-return vs webhook timing.
- [ ] Test renewal success and failure.
- [ ] Test `past_due`, recovery, `payment_failed` / unpaid behavior, and access restoration.
- [ ] Test pause, cancellation, expiration, and cancel-at-period-end.
- [ ] Test plan upgrades and downgrades.
- [ ] Test fixed and percentage promotions.
- [ ] Test zero-dollar and partially discounted payment outcomes.
- [ ] Test webhook retries and duplicate-delivery idempotency.
- [ ] Verify webhook signatures through the production reverse proxy / ingress.

## Database / Production Environment

- [ ] Run migrations against a clean production-like database.
- [ ] Verify pgvector availability.
- [ ] Verify required roles, catalog data, features, and configuration after migrations.
- [ ] Define which bootstrap scripts are allowed in production.
- [ ] Keep destructive bootstrap operations explicitly guarded.
- [ ] Validate tenant isolation against production-shaped multi-tenant data.

## AI Service Production Validation

- [ ] Disable AI mocks in production.
- [ ] Validate RAG success, failure, and usage accounting.
- [ ] Validate extraction upload and persisted metadata.
- [ ] Validate pending extraction processing.
- [ ] Validate pricing service `OK` / `UNKNOWN` behavior.
- [ ] Validate sentiment success, low-sample, and pending-analysis behavior.
- [ ] Validate MPI `OK` / `UNKNOWN` behavior.
- [ ] Verify AI timeouts and malformed-response handling.
- [ ] Verify forwarded authentication context with the deployed AI service.

## Analytics / Data Quality

- [ ] Validate dashboard metrics using production-shaped data.
- [ ] Validate demand-forecast coverage over real periods.
- [ ] Validate Market Intelligence score ranges and missing-data behavior.
- [ ] Validate competitor mappings/prices before showing derived rankings.
- [ ] Preserve `—` / unknown states when data is genuinely unavailable.

## Monitoring / Operations

- [ ] Add structured logs for provider/external-service failures.
- [ ] Track webhook failures and retries.
- [ ] Track background extraction/sentiment failures.
- [ ] Add alerts for repeatedly failing provider/AI operations.
- [ ] Configure application health monitoring.
- [ ] Define database backup and restore procedure.
- [ ] Document production environment variables in the deployment system.

## Final Production Checks

- [ ] `npm ci`
- [ ] `npm run prisma:validate`
- [ ] `npm run build`
- [ ] `npm test`
- [ ] `npm run validate`
- [ ] Confirm no real secrets are committed.
- [ ] Rotate/store production JWT secrets securely.
- [ ] Verify production CORS origins.
- [ ] Verify upload/body limits.
- [ ] Verify tenant isolation and platform permissions.
- [ ] Verify provider errors do not leak sensitive information.

---

# ✅ Done

## Core Architecture

- [x] Backend organized by feature domains.
- [x] Route → Controller → Service → Repo/client responsibilities established.
- [x] Functional programming style preserved where used by the project.
- [x] Prisma persistence kept in repository layers.
- [x] External provider transport isolated in clients.
- [x] Stripe provider code isolated under the subscription domain.
- [x] Stripe webhook raw-body handling preserved.

## Security / Multi-Tenancy

- [x] Server-side tenant membership checks.
- [x] Platform role and permission checks.
- [x] Centralized JWT verification.
- [x] Environment-driven CORS.
- [x] Tenant-aware Stripe customer reuse.
- [x] Stripe webhook signature verification.
- [x] Global JSON error handling.
- [x] Configurable request/upload size limits.
- [x] Custom-plan tenant privacy protections.
- [x] Accepted custom-plan immutability protections.

## Subscription / Billing Foundation

- [x] Plan management.
- [x] Plan-feature assignments.
- [x] Standard subscription checkout.
- [x] Subscription plan-change flow.
- [x] Subscription cancellation flow.
- [x] Current subscription retrieval.
- [x] Invoice retrieval.
- [x] Promo-code validation and linking.
- [x] Stripe webhook integration.
- [x] Webhook idempotency protections.
- [x] Server-authoritative pricing rules.
- [x] Custom-plan configurator.
- [x] Automatic custom-plan quote flow.
- [x] Manual-review custom-plan quote flow.
- [x] Custom-plan checkout.
- [x] Manual quote lifecycle.
- [x] Vendor rate cards.
- [x] Infrastructure rates.
- [x] Custom-plan pricing policy.
- [x] Pricing snapshots and fingerprints.
- [x] Monitoring frequency stored as competitor-management configuration rather than a fake standalone feature.

## Feature / Entitlement Foundation

- [x] Feature catalog.
- [x] Boolean feature-access rules.
- [x] Metered usage/limit rules.
- [x] Plan-feature entitlement mapping.
- [x] Usage accounting infrastructure.
- [x] RAG Assistant.
- [x] Document Extraction.
- [x] Document Storage commercial model.
- [x] Dashboard Analytics.
- [x] Market Intelligence.
- [x] Tracked Competitors / competitor management.
- [x] Demand Prediction / forecasting read flows.
- [x] Data Connections / ingestion foundation.
- [x] Sentiment analysis endpoints.
- [x] Market Perception Index endpoint.
- [x] AI pricing recommendation endpoint.

## Product Modules

- [x] Dashboard aggregation.
- [x] Competitor management.
- [x] Opportunity / leaderboard flow.
- [x] Market Intelligence metrics flow.
- [x] Demand Forecasting pages/data flow.
- [x] Knowledge Base / RAG flow.
- [x] Data-connection file ingestion flow.
- [x] Market Intelligence PDF export.
- [x] Demand Prediction PDF export pattern.

## Admin / Owner Platform Foundation

- [x] Platform owner/admin role model.
- [x] Platform admin permission checks.
- [x] Companies management/read flows.
- [x] Users management/read flows.
- [x] Plans/features/billing administration foundation.
- [x] Custom-plan policies/rates administration foundation.
- [x] Owner protection rules.
- [x] Admin-team permission model foundation.

## Verification / Testing Foundation

- [x] Unit tests exist.
- [x] Route-contract verification exists.
- [x] Security-regression verification exists.
- [x] Subscription-integration verification exists.
- [x] Custom-plan contract verification exists.
- [x] Feature-entitlement verification exists.
- [x] Full local validation command exists.

---

# Quick View

## Doing now

- [ ] 🟡 Fixing and enhancing subscription/payment UX and lifecycle correctness.

## Next major items

- [ ] Alert / notification system.
- [ ] Invitation system completion.
- [ ] Payment-recovery UX.
- [ ] AI/background worker triggers.
- [ ] Remaining feature-gate decisions.
- [ ] Full Stripe production scenario validation.
- [ ] Production database/environment validation.
- [ ] Monitoring and operational alerts.
- [ ] Final production-readiness checks.

## Main completed areas

- [x] Core backend architecture.
- [x] Multi-tenant security foundation.
- [x] Subscription/billing foundation.
- [x] Custom plans and pricing foundation.
- [x] Feature catalog and entitlements.
- [x] RAG and document ingestion.
- [x] Market Intelligence.
- [x] Demand Prediction.
- [x] Competitor management.
- [x] Sentiment and MPI integration foundation.
- [x] Platform admin / owner foundation.
- [x] Verification/test foundation.

---

_Last updated: 2026-10-02_
