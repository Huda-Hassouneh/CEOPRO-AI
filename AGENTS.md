# KEEL — Repository Instructions for Coding Agents

## Project and authority

KEEL is a multi-tenant, AI-powered SaaS for business intelligence and commerce operations. Its core capabilities include Dashboard Analytics, Product Management, Inventory Management, Data Connections and Document Extraction, Demand Prediction, Competitor Management, Market Intelligence and Customer Perception, Pricing Recommendations, RAG Assistant, Smart Alerts, Marketing Images, Billing and Subscriptions, Shopify and WooCommerce, Reports and Exports, and Platform Administration.

- **Authoritative implementation:** `E:\KEEL START\CEOPRO-AI` (Python/FastAPI, React/Vite, PostgreSQL with FORCE RLS, Redis, workers). Confirm the actual current checkout before working.
- **Legacy reference — strictly read-only:** `D:\freeup space\New folder\Keel\root`; Node backend at `...\backend`, React frontend at `...\frontend`. Inspect legacy code for approved behavior/UI parity, but never edit, install dependencies, build, write caches, run migrations, or change databases there. If execution is needed, use an isolated copy elsewhere.
- Python is the sole runtime authority for authentication, Stripe billing, subscriptions, entitlements, pricing, and usage/credit accounting. Do not introduce a parallel Node.js service or a second billing authority.
- Preserve existing Python-only functionality, AI models/workers, and all 15 features. Search for existing implementations before creating replacements.

## Business and security invariants

- Every request and persisted record must belong to the authenticated, authorized tenant. A new self-registering user must not inherit another user's tenant, onboarding, subscription, data, or credits. Tenant Owner/Admin is distinct from Platform Owner; only authorized Platform Owners may use platform administration APIs.
- Maintain PostgreSQL FORCE RLS and least-privilege runtime roles. Existing responsibilities are separated across `ceopro_app`, `ceopro_billing_setup`, `ceopro_billing_webhook`, and `ceopro_credit_accounting`. Never give application/worker processes migration-admin, SUPERUSER, BYPASSRLS, or broad DDL credentials as a workaround.
- Preserve signed Stripe webhook verification, tenant/customer/Checkout association, idempotency, out-of-order event handling, and payment-gated access. A Checkout redirect, scheduled plan change, draft invoice, or $0 trial invoice is not proof of a paid post-trial period.
- A downgrade must not truncate an existing trial, invent an active paid period, reset billing boundaries, or reset credits. Maintain the verified trial/downgrade integrity fix and credit-settlement invariants.
- Keep feature allowances, customer Data/AI Credits, and actual provider costs separate, auditable, and correctly settled. Financial amounts require precise monetary arithmetic and the approved policy/rounding rules.
- Stripe Test Clock is **local TEST-only**, controlled by `STRIPE_TEST_CLOCK_ENABLED` and `STRIPE_TEST_CLOCK_ID` in the private `.dev/integrations.env`. It must stay disabled by default and impossible to use with LIVE credentials or in production. Never assume it can be attached to an existing customer.
- Existing KEEL-approved ADR/business decisions override legacy code *only where they explicitly supersede it*. Never invent unresolved pricing rates, margin thresholds, approval rules, or commercial policies.

## Working procedure

1. Start by reading applicable `AGENTS.md`, the root README, and only the architecture/ADR/runbook documents relevant to the current task. Check `git branch --show-current`, `git rev-parse HEAD`, `git status --short`, current services, and protected modifications. Repository state and source code take precedence over historical handoffs.
2. Work on **one approved objective at a time**. Trace existing React → FastAPI → DB/worker behavior before editing. Prefer minimal, reviewable patches over broad refactors; preserve English/Arabic/RTL behavior.
3. Do not modify unrelated customer data or billing records. Use separate disposable test infrastructure and synthetic fixtures when possible. For any approved data-changing migration or rollout, create and verify a recoverable backup first. Migrations must be forward-only; do not rewrite applied migrations.
4. Test actual business outcomes, not just HTTP 200 or page rendering. Include relevant frontend, backend, restricted-role/RLS, tenant-isolation, and browser tests. Differentiate automated mocks from real external-provider acceptance. Report **PASS / FAIL / BLOCKED** and evidence; never invent test results.
5. For demo seeding, use one explicitly designated synthetic tenant, coherent source inputs, canonical supported ingestion/worker paths, and an idempotent seed procedure. Do not fabricate completed AI forecasts, RAG answers, reports, scraped prices, image generation, or payments. Produce known expected facts/metrics separately for validation.
6. Never print, commit, or upload secrets, API keys, access tokens, or private `.env` files. Do not perform Stripe LIVE operations, initiate real payments, push, merge, deploy, force-push, reset Git, or alter historical customer financial records without explicit authorization.
7. At major milestones, report changed files, verification evidence, current commit, current runtime status, known limitations, and what remains. Update existing relevant docs rather than generating duplicate reports. Do not assert full production or pixel-perfect parity without measured evidence.

## Where to find detail

Read the actual existing docs and source; do not assume a linked file exists without checking. Relevant past reports may include:

- `docs/PLATFORM_BILLING_LEGACY_PARITY_REPORT.md` — billing UI/pricing parity, known approved deviations and remaining gaps.
- `docs/TRIAL_DOWNGRADE_INTEGRITY_FIX.md` — confirmed trial/downgrade security incident and fix.
- `docs/STRIPE_TEST_CLOCK_LOCAL_GUIDE.md` — local Test Clock setup and limits.
- `docs/CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md` — scoped billing database roles.
- `docs/TEST_ENVIRONMENT_RECOVERY.md` — isolated environment/recovery.

For local operations, use the repository's documented `dev.ps1` commands (`doctor`, `up`, `status`, `test`) and **read the actual active ports from status/config**, rather than assuming an old port is still available.

**Do not place temporary task instructions or full chat transcripts in this file.** Give each new Codex conversation one focused task prompt; use a concise task handoff when a major milestone ends.
