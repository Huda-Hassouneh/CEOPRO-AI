# CEOPRO Backend Test Suite

This directory is organized by **product/domain responsibility**, so you can find a test by the CEOPRO feature it protects instead of searching a flat list.

Feature 14 Smart Alerts QA is in [`smart-alerts/README.md`](smart-alerts/README.md). Run `npm run test:smart-alerts` from `backend/`; the feature ZIP includes the suite and its current results.

Feature 15 AI Pricing QA is in [`ai-pricing/README.md`](ai-pricing/README.md), with its actual coverage matrix in [`ai-pricing/COVERAGE.md`](ai-pricing/COVERAGE.md). Run `npm run test:ai-pricing` from `backend/`. Its PostgreSQL and full hosted-Gradio paths are explicitly gated; read the feature README before setting test credentials.

## Folder map

```text
tests/
├── billing/
│   ├── core/                    # Small billing/subscription contract + pure logic tests
│   ├── custom-plan/             # Custom-plan validation/pricing/quote/security scenarios 01–11
│   ├── custom-plan-stripe/      # Real Stripe TEST-mode custom-plan scenarios 12–19
│   ├── subscription-lifecycle/  # Subscription lifecycle scenarios 20–26
│   └── production-plans/        # Production-plan/bootstrap scenarios 27–33
├── auth/                        # Registration, session, password, and membership selection
├── integrations/
│   ├── ai/                       # AI runtime config and feature-to-Gradio contracts
│   └── email/                    # Local SMTP protocol tests using a fake TLS socket
├── contracts/                   # Static cross-cutting source/schema/security contract verifiers
├── dashboard/                   # Dashboard formulas, tenant-safe API/UI checks, and coverage notes
├── e2e/dashboard/               # Playwright dashboard and opt-in live ingestion tests
├── e2e/market-intelligence/     # Market Intelligence overview diagnostics and opt-in AI pricing check
├── e2e/demand-prediction/       # Demand Prediction overview and opt-in live forecast check
├── market-intelligence/         # Market Intelligence source, metric, producer, and setup map
├── support/diagnostics/         # Read-only PostgreSQL verifier and structured reporter
├── features/                    # Canonical feature catalog + entitlement/capacity policy
├── forecasting/                 # Demand forecasting calculations, service/controller contracts
├── product-management/          # Product source/schema contracts and lifecycle coverage matrix
├── e2e/product-management/      # Product lifecycle, ingestion, security and integration BLOCKED diagnostics
├── connected-data-sources/      # Persistent-source quota, entitlement, RLS, and concurrency contracts
├── document-extraction/         # Upload, quota, Gradio, staging/worker, template and UI regression contracts
├── document-storage/            # Retained RAG storage, BYTEA, quota, UI parity, and MinIO diagnostics
├── rag/                          # RAG upload/query/citation contracts and fictional evaluation corpus
├── business-recommendations/    # AI/Node/catalog contracts and source-level regression diagnostics
├── ai-pricing/                  # Feature 15 source/Gradio contracts, pricing regressions, and coverage
├── e2e/ai-pricing/              # Opt-in real browser → Node → hosted Gradio pricing workflow
├── e2e/connected-data-sources/  # Real API/UI/SQL quota and Growth race checks (fixture-gated)
├── e2e/document-extraction/     # Upload, quota, worker, tenant, UI, and opt-in live-Gradio scenarios
├── e2e/document-storage/        # Storage, tenant, quota, deletion, and MinIO BLOCKED diagnostics
├── e2e/rag-assistant/           # RAG upload/chat/citation/quota/tenant diagnostics and opt-in AI specs
├── e2e/business-recommendations/ # Customer-flow BLOCKED diagnostics and opt-in local AI endpoint check
├── notifications/
│   ├── platform/                # Platform-admin notification definition/storage/producer/worker contracts
│   └── tenant/                  # Tenant notification definition/storage/producer/worker contracts
├── rag/                         # RAG document-upload route/client contract checks
├── onboarding/                  # Tenant onboarding validation and RLS-scoped persistence
└── runners/                     # Ordered suite runners
```

Every folder contains its own `README.md` with the exact files, behaviors covered, dependencies, and safety notes.

## Test layers

- **Pure/unit tests:** deterministic calculation, validation, status, catalog, and policy behavior. These should not need a live DB or Stripe.
- **Source/migration contract tests:** read source or migration files and assert security/API/architecture invariants without starting external services.
- **Disposable DB tests:** require an explicitly configured test database and exercise Prisma-backed persistence/isolation behavior.
- **Stripe TEST-mode E2E:** require `sk_test_...` and a disposable migrated DB. They intentionally create remote Stripe test objects and refuse live keys.
- **Dashboard diagnostics:** `npm run test:dashboard:contract` checks the source contract without credentials; `npm run test:dashboard` runs only the Dashboard API/UI/DB checks. Live AI ingestion is separately opt-in. Read [Dashboard diagnostics](dashboard/README.md) before configuring it.
- **Market Intelligence diagnostics:** `npm run test:market-intelligence:contract` checks source/security contracts; `npm run test:market-intelligence` runs real API/UI/read-only DB comparisons and labels missing setup BLOCKED. The on-demand AI pricing call is isolated behind an explicit opt-in. Read [Market Intelligence diagnostics](market-intelligence/README.md) before configuring it.
- **Demand Prediction diagnostics:** `npm run test:demand-prediction:contract` runs horizon calculations, AI client request/response contracts, controller/service, and entitlement checks. `npm run test:demand-prediction:e2e` runs authenticated API/UI checks and optional RLS-scoped independent DB calculations; real AI generation is opt-in only. Read [Demand Prediction testing](forecasting/README.md) for source ownership, forecast formulas, the PowerShell setup, and known integration risks.
- **Product Management diagnostics:** `npm run test:product-management:contract` verifies the current frontend stubs, backend route gap, schema/trigger/RLS rules, plan limits, import matching/capacity, and the separate AI Quick Sale path. `npm run test:product-management:e2e` records real lifecycle scenarios as BLOCKED until the customer product CRUD UI/API and safe test fixtures exist; it does not fake persistence. Read [Product Management diagnostics](product-management/README.md) for the verified implementation map, coverage matrix, risk findings, and PowerShell commands.
- **Competitor Management diagnostics:** `npm run test:competitor-management:contract` verifies UI wiring, authenticated tenant API routes, exact-name identity, plan configuration, RLS/schema boundaries, profile price behavior, and the AI discovery event boundary. The real Playwright scenarios are recorded as BLOCKED until a disposable database, verified tenant identities, and cleanup contract are configured. Read [Competitor Management diagnostics](competitor-management/README.md) for verified behavior and PowerShell commands.
- **Connected Data Sources diagnostics:** `npm run test:connected-data-sources:contract` checks the separate boolean access/numeric capacity features, standard limits, active-source accounting, manual uploads, RLS, and known Node/AI/UI regressions. `npm run test:connected-data-sources:e2e` runs real API/UI/SQL checks only with disposable tenant fixtures; concurrency is separately runnable. Read [Connected Data Sources testing](connected-data-sources/README.md) for setup, quota rules, commands, and current blockers.
- **Document Extraction diagnostics:** `npm run test:document-extraction:contract` reuses file validation, sales-row, worker, and Gradio client contracts, then checks the extraction route, usage order, ownership, worker lifecycle, RLS, templates, frontend upload copy, and known quota/idempotency risks. Real API/UI/database scenarios require explicit disposable fixtures; live Gradio calls are opt-in only. Read [Document Extraction testing](document-extraction/README.md) for the verified ownership map, supported formats, quota semantics, and blockers.
- **Document Storage diagnostics:** `npm run test:document-storage:contract` audits RAG BYTEA retention, lifetime capacity, tenant scoping, upload limits, business-upload accounting, billing units, and MinIO object paths. Real PostgreSQL and MinIO scenarios are registered as BLOCKED until disposable fixtures and owned cleanup are configured. Read [Document Storage diagnostics](document-storage/README.md) for the ownership map, findings, and PowerShell commands.
- **RAG Assistant diagnostics:** `npm run test:rag-assistant` runs source regressions, a controlled Node Gradio client contract, existing AI-team retrieval/generation unit tests, and shared Playwright diagnostics. Live Gradio and AI-team FastAPI queries are separate opt-ins; neither path is treated as proof of the other. Read [RAG Assistant testing](rag/RAG_ASSISTANT_TESTING.md) for the architecture, citation/token gaps, evaluation fixtures, safety rules, and Windows commands.
- **Business Recommendations diagnostics:** `npm run test:business-recommendations` runs deterministic AI rules/source checks, the Node catalog/plan/API architecture audit, existing Python API/unit tests when pytest is installed, safe-gated PostgreSQL integration, and shared Playwright diagnostics. The AI `GET /dashboard/recommendations` exists, but the customer Node entitlement proxy and live frontend are absent. The three standard plans do not grant the boolean feature. Read [Business Recommendations testing](business-recommendations/README.md) for the signal formulas, data-source mismatch, defects, gates, reports, and PowerShell commands.
- **Data Integration diagnostics:** `npm run test:data-integration:contract` reuses upload validation, extraction-response, sales-row, worker migration and Gradio transport tests and checks source ownership, quotas, frontend actions, connector staging/promotion boundaries, RLS and worker roles. `npm run test:data-integration:e2e` records real upload, worker, duplicate, connector, quota, security and downstream scenarios as BLOCKED until safe DB/tenant/worker fixtures are configured. Read [Data Integration testing](dataconnection/README.md) for the implementation map, defects, PowerShell commands and live-test prerequisites.
- **Combined E2E/contracts:** `npm run test:e2e` runs all feature Playwright suites using the shared config/reporter. `npm run test:feature-e2e` runs feature E2E directories, including Business Recommendations. `npm run test:all-features` runs feature contracts and then E2E, collecting every suite result even when an earlier contract fails. Business Recommendations reuses the same Playwright settings/reporter and keeps its output under `tests/reports/business-recommendations/` so it does not overwrite the shared feature report.

## Numbered billing flow

The original scenario sequence is preserved:

```text
01–11  billing/custom-plan
12–19  billing/custom-plan-stripe
20–26  billing/subscription-lifecycle
27–33  billing/production-plans
```

That sequence makes failures easy to locate from configuration/pricing → Stripe → lifecycle → production bootstrap.

## Running an individual TypeScript test

From the backend repository root:

```bash
node --import tsx --test tests/<folder>/<file>.ts
```

Auth/onboarding checks can be run together with:

```bash
npm run test:auth-onboarding
node --import tsx --test tests/auth/*.test.ts tests/onboarding/*.test.ts
```

Run the AI and email integration checks together with:

```bash
npm run test:integration-services
```

These tests use fake HTTP/SSE and SMTP transports. They do not require a database, Hugging Face token, Gmail credentials, or Resend API key.

For the numbered suites, prefer the project npm scripts described in each suite README because their runners enforce test-DB / Stripe safety checks.

## Path migration map

Files were moved for navigation; test intent was not changed. If `package.json`, CI, or external scripts directly reference old paths, update them using this map:

| Old path | New path |
| --- | --- |
| `tests/*.test.ts` billing/subscription files | `tests/billing/core/*.test.ts` |
| `tests/custom-plan-pricing.test.ts` | `tests/billing/custom-plan/custom-plan-pricing.test.ts` |
| `tests/custom-plan/` | `tests/billing/custom-plan/` |
| `tests/custom-plan-stripe/` | `tests/billing/custom-plan-stripe/` |
| `tests/subscription-lifecycle/` | `tests/billing/subscription-lifecycle/` |
| `tests/production-plans/` | `tests/billing/production-plans/` |
| `tests/feature-catalog.test.ts` | `tests/features/feature-catalog.test.ts` |
| `tests/feature-entitlement-policy.test.ts` | `tests/features/feature-entitlement-policy.test.ts` |
| `tests/platform-notifications/` | `tests/notifications/platform/` |
| `tests/tenant-notifications/` | `tests/notifications/tenant/` |

`forecasting/`, `rag/`, `contracts/`, and `runners/` remain at the same top-level paths.

## Important execution rule

Run path-sensitive tests from the **backend repository root**. Several contract tests intentionally resolve `src/`, `prisma/`, or `package.json` from the repository root.
