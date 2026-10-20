# KEEL — Unified Python Backend Integration: Master GPT Work Execution Contract

**Purpose:** Preserve and integrate the selected Node KEEL capabilities into the AI team's existing Python/FastAPI main repository, retaining and improving Python's existing overlapping capabilities without creating competing implementations. This is an **implementation contract**, not permission to replace entire subsystems blindly.

**Input snapshots supplied for reference (19 October 2026):**
- `my-version(1).zip` → `keel/`: original Node/Express/TypeScript/Prisma backend, frontend, and a `keel/ai/` subtree containing provider connectors. **ALL contents strictly read-only.**
- `main-repo(1).zip` → `CEOPRO-AI/`: AI team's Python/FastAPI backend, its PostgreSQL migrations, workers and frontend. **Destination**, but replace this snapshot with the **verified post-Task-6 main HEAD** before implementation.
- Prior findings: `KEEL_SUBSCRIPTION_ENTITLEMENT_PRESERVATION_SPEC.md`, `KEEL_NODE_VS_PYTHON_SUBSCRIPTIONS_ENTITLEMENTS_AUDIT_20261019.md`, `KEEL_TARGET_BILLING_ENTITLEMENT_ARCHITECTURE_20261019.md`, `KEEL_ZERO_LOSS_BACKEND_MIGRATION_PROTOCOL_AND_WORK_PROMPT.md`. These are reference evidence, **not proof of complete parity**.

> **IMPORTANT TO GPT WORK:** Execute this contract as a **series of bounded, verifiable phases**, not as one uncontrolled huge patch. First inventory and design; then implement selected, approved phases. Do not stop at creating reports when implementation has been authorized. Do not claim the overall integration is complete if any required phase is outstanding or blocked. If time, context, credentials or tests prevent completion, leave an accurate resumable handoff with exact status, commit and remaining tasks.

---

## READY-TO-PASTE GPT WORK PROMPT

### 0. Role, goal and irreversible rules

You are the lead backend architect, migration engineer and test engineer integrating **two real KEEL codebases**. This is an expensive, production-sensitive migration. Deliver implementation, not merely an architecture proposal, **after the required inspection and approval gates**.

**My objective:** The final production product is the AI team's **Python/FastAPI main** implementation. The original Node.js repository is **read-only** and provides source-level requirements. Preserve Python-only features, reuse equivalent Python code, improve overlapping features by adopting the strongest *approved* behavior, and implement Node-only functionality in idiomatic Python using the main repository's architecture. Do not preserve Node as a second runtime just because its original implementation uses TypeScript.

**In-scope migration domains, all mandatory**:
1. Authentication, onboarding, authorization, tenant membership, roles and platform/tenant-admin boundaries.
2. Complete subscriptions and billing: plans/catalog, Stripe, trials, checkout, renewal, cancellation, resubscription, invoices, promotions/promo codes, plan-feature links, custom plans, customer-facing configurators, price/cost engines, custom quotes/approvals, and the related user/admin/platform dashboards.
3. All feature entitlements, Boolean gates, metered usage/quota enforcement, resource capacities, per-period tracking, refunds/releases, plan changes, concurrent requests, background worker enforcement and separate Data/AI Credit accounting.
4. Shopify and WooCommerce **dedicated adapters and the full persistent connection/sync workers**, not merely generic API connector configuration.
5. Other Data Connections required by those flows, especially manual uploads, extraction, staging, review, validation, promotion to canonical products/inventory/sales/invoices/reviews where supported, duplicate prevention and import job status.
6. Pricing recommendations end to end: market-source evidence, eligibility, policies/guardrails, inputs, inference contracts, persistence, quota/credit charging, API and dashboard.
7. Market Perception Index (MPI) at **BUSINESS, PRODUCT and COMPETITOR scopes** (called MPI levels in this request): review eligibility, minimum sample, pipeline/model contract, evidence, persistence, status semantics, access/usage and dashboard.

**Explicitly not a wholesale migration of all unrelated features:** trace any shared helper, dependency, database entity, frontend contract, worker, notification, product/sales path, competitor source, reporting or AI/RAG component used by the above features. Port only what is required for coherent, functioning end-to-end behavior; record out-of-scope dependencies as blockers, not invisible omissions. Do not rewrite forecasting or other unrelated AI functions merely because they're present.

**Immutable rules:**
- Node repository (including `keel/ai/` connectors): read only. Do not edit, format, regenerate, commit, delete, migrate or reconfigure it. Record its commit/hash and check that it remains unchanged.
- Python `main` is the only production code destination. Work on a clean integration branch from the **post-Task-6 verified commit**, not on a concurrent or dirty Task 6 worktree. No pushes, merges or deployments without my approval.
- One authoritative Python-issued identity/token system, membership/role source, tenant/RLS context, subscription assignment, Stripe webhook processor, entitlement evaluator, usage ledger and credit/cost ledger. **No duplicate Node/Express/Prisma service, second Stripe processor, shadow tenant catalog or competing usage database.**
- Prefer the existing Python directory, router, service, repository, worker, SQL migration, dependency-injection, testing and error conventions. Introduce cohesive Python modules only if the existing architecture cannot appropriately accommodate the functionality.
- Preserve working Python capabilities, user data, plan assignments, credits, historical prices, business data, consent, audit records and AI outputs. Avoid unrelated rewrites/refactors. **No mocks as production behavior** and no invented provider data, live prices, commercial policy or credentials.
- Preserve the **current Python public contracts** unless a user-approved change requires a compatible adapter and frontend update. The user explicitly requires **dashboard-to-API-to-worker-to-database end-to-end** flows; make focused changes to Python main's frontend as needed. Do not migrate the Node frontend wholesale or casually redesign UI.
- Do not change Python inference algorithms, trained models or mathematical behavior just to port backend orchestration. Existing AI inference implementations generally remain source of truth unless a verified bug/change is separately approved.
- Never silently overwrite plan prices, limits, feature access, subscription periods, promo terms, currencies, granted rights or existing customers. Such differences require an explicit commercial decision.
- Do not print, hardcode or commit actual secrets. Use existing encrypted vault/KMS and environment/secrets conventions.

### 1. Mandatory work prerequisites and baselines

1. Confirm Task 6's final source commit, complete diff, migrations and test logs. Verify the reported fixes for late paid-invoice failure events, old-subscription cancellation, forecast entitlement alias, replayed report key after cancellation, cross-period idempotency and invalid quota amounts. If Task 6 has not finished, **STOP any overlapping implementation** and produce the prerequisites report instead of risking conflicts.
2. Freeze exact Node and post-Task-6 Python commit IDs/ZIP hashes, versions of Python/PostgreSQL/Redis/Stripe SDK and main entrypoints. Record active branch and working tree status. Distinguish old supplied Python ZIP from newer main HEAD.
3. Locate source-of-truth startup instructions, configuration, environment examples, migration runner, SQL RLS policies, API registrations, worker/scheduler registrations, tests and frontend API call sites. Record actual execution commands instead of inventing them.
4. Establish a disposable local/staging **native PostgreSQL 17** test database and associated Redis/minimal infrastructure. Never run destructive migrations/seeds/test transactions against a shared or production database. Test accounts and Stripe **test-mode** resources only, when allowed.
5. Save a baseline suite summary: passing/failing/skipped, exact commands, reasons, environment and pre-existing failures. No new migration or patch may hide failed baseline tests.

### 2. Exhaustive source tracing — REQUIRED for EACH listed feature

Before designing or editing, trace **both implementations** to their actual runtime entrypoints. Matching names or documentation are not proof of equivalent behavior.

For **each atomic behavior**, record the complete chain in both repos where present:

`User/admin dashboard → frontend API client/validation → mounted HTTP endpoint or webhook → authentication → tenant membership & role authorization → input validation → plan access → quota/capacity reservation / credit budget → application service & recursively called helpers → database reads/writes and transaction boundaries → queue/job producer → scheduled/background consumer → third-party API / existing inference pipeline → canonical data/evidence persistence → audit/idempotency/error handling → usage settle/refund → API status/error/response → frontend state/visualization`.

Trace *all relevant helper functions, repository calls, utility modules, constants, migrations, indexes, SQL functions, RLS policies, triggers, DTOs, schemas, cron/streams, workers, test fixtures, feature flags and secret/env names*. Include conditional and failure paths. Classify files as mounted/active, indirectly reachable, legacy/dead or unverified. Do not copy legacy code merely because its filename looks relevant.

**Evidence per behavior:** stable capability ID; exact source files **and functions** in both repositories; entry and caller chains; inputs/outputs, types, units, state transitions, eligibility and roles; DB tables/columns/constraints/RLS and migration that created them; worker event names/job states; external provider assumptions; present tests; edge cases; and gap verdict. Use a transitive dependency graph, not just a directory listing.

Perform mechanical coverage reconciliation of active routes, frontend feature entrypoints, webhook topics, jobs, scheduled processes, entitlement codes, and relevant write surfaces so that no behavior is silently omitted. Unknown or unreachable code must be explicitly documented; lack of a test does not prove absence of functionality.

### 3. Conflict-resolution process — architecture BEFORE implementation

For each atomic capability mark **EXACT_EQUIVALENT / PYTHON_STRONGER / NODE_STRONGER / PARTIAL_OVERLAP / NODE_ONLY / PYTHON_ONLY / DIFFERENT_BUSINESS_POLICY / UNVERIFIED**. Attach source evidence and behavior—not subjective judgments about language quality.

Apply these rules:
- Equivalent: **reuse Python**, add parity/regression tests; no rebuild.
- Python stronger/only: **preserve Python**, including its Data/AI Credits, provider-cost ledgers, spending caps, monitoring and tenant protections.
- Node stronger or Node only: implement the missing approved Node business behavior in **Python main**, using Python's authoritative identity, persistence, billing and job conventions. Preserve existing Python stronger guarantees.
- Partial overlap: design ONE merged behavior and data model with explicit transition semantics; implement a narrow extension rather than a second parallel subsystem.
- Conflict in price/limits/trial eligibility/contract terms/legal retention/admin authority/security or provider semantics: create an Architecture Decision Record (ADR), present options and evidence, and **request my decision BEFORE the affected implementation**. Other nonblocked, independent work may continue safely.
- Unverified: mark as `BLOCKED` or `NOT VERIFIED`, never `DONE`.

**Each feature needs an architecture note. Any conflict MUST have an ADR** at `docs/keel-integration/architecture/ADR-<capability-id>-<slug>.md`, containing context, confirmed Node/Python behavior, tradeoffs, selected architecture, alternatives rejected, API/data schema/worker flow, security/RLS, entitlement/credits, backfill/migration, error handling, frontend contracts, compatibility, operational risks and test proof. Explicitly identify what *Node functionality survived* and what *Python functionality was retained*. Add simple Mermaid sequence/data diagrams when they clarify complex behavior.

Do not implement contested business policy until I approve the ADR/decision register. Do not turn unresolved approval items into arbitrary defaults.

### 4. Feature-specific non-negotiable tracing and preservation

#### 4A. Authentication, onboarding and authorization

Trace signup, duplicate/pending accounts, email verification, login, refresh/session revocation, expiry, reset password, invitations/acceptance, user activation, tenant creation, membership changes, role change/permission matrix, tenant switching, platform owner/admin vs tenant owner/admin, middleware, background service identities, audit, throttling, validation, and the Python JWT claim contract.

Protect tenant isolation under PostgreSQL RLS **including login/bootstrap paths and service-role execution**. Avoid recursive policies, superuser application connections, privilege escalation or token acceptance from an untrusted issuer. Existing Node behavior missing in Python is ported only when consistent with Python's identity ownership; do not create dual auth stacks. Test unauthenticated, wrong-role, cross-tenant, membership-revoked, expired token, CSRF/replay where applicable, and concurrent onboarding/invitation flows.

#### 4B. Subscription, plans, promotions and dashboards

Trace plan listing, canonical feature catalog, plan feature association, Boolean rights, SUM consumption, MAX live capacity, source counting, plan/version and historic Stripe price mapping, monthly and 3-/6-month terms if supported, trials and eligibility, checkout, portal, taxes/currency policy, renewal, invoice/payment state, refunds if implemented, past_due/grace, cancellation at period end/immediate, resubscription, upgrades/downgrades, switching paid plans, proration and trial conversion. Follow actual webhook event-to-state and admin override paths.

**Promo codes:** trace complete Node lifecycle: create/update/disable; allowed plans, currencies/billing terms, date windows, redemption/max counts, per-customer/tenant eligibility, repeat redemption policy, Stripe coupling, atomic redemption and audit; verify if equivalent Python code genuinely exists. **Do not confuse Python `extraction/promotion.py` (ingestion promotion) with subscription promotional codes.** Decide which rules/discounts Stripe owns vs which Python must enforce; no unauthorized discount stacking or replays.

**Custom plans and costs:** trace Node configurator, feature selection and per-feature limits, competitor monitoring cadence, vendor/API unit costs, infrastructure, usage forecast, margins, currency conversions/rounding, cost/price preview, approval thresholds, operator review, quote revisions, expiry, acceptance/rejection, offer/contract history, quote-to-Stripe mapping, paid activation, customer self-service and platform-admin controls. Preserve cost calculation inputs and formulas only after establishing actual code behavior and compatibility with Python's verified provider-cost ledger. **Accepting a quote must not activate paid entitlements until existing authorized billing/administrative activation conditions are satisfied.** Never invent FX rates/provider costs.

**Dashboards end to end:** inspect and integrate the actual Python frontend for plan comparisons, subscription/current usage, invoices, promo entry/validation/feedback, customer custom-plan builder/quote tracking and operator approval/pricing administration. Backend route → permission → DB → frontend should be executable, not just a newly added API endpoint. Preserve Python UI patterns and supported roles and provide loading/empty/error/conflict states without mock billing values.

**Plan transition logic:** compare effective feature grants/allowances (including private custom contracts) before and after—not just price or tier. Determine upgrade/downgrade/mixed changes, schedule reductions where contractually required and keep old/new subscription event identity linked to Stripe. Never let delayed events for subscription A change the current state of subscription B; reconcile invoice state and protect idempotency.

#### 4C. Entitlements, usage, capacities, credits and costs

Map **every one of Node's 21 registered feature codes** individually to Python names and actual gates; retain every Python-only permission and resource. For each record Boolean vs SUM vs MAX vs time/cadence vs AI/Data Credits, canonical units (tokens, KB, MB, products, connected sources, competitors, reports, seats), plan missing vs disabled vs unlimited, custom overrides, status requirements, ownership, reset boundary and actual server-side enforcement point. Do not treat a missing plan-limit row as unlimited by accident.

Trace reserve/commit/settle/release (including failures, retry, cancellation and crash), same-key idempotency, cross-period key use, late workers, concurrency/last-slot capacity, cache invalidation, quota visibility in dashboards, plan downgrade with already-consumed amounts, timezones, and budget reconciliations. Charge/authorize at enqueue and **revalidate at execution** where the action is deferred. Python provider spending budgets and immutable credit ledgers must remain distinct from customer-facing feature quotas. All paid providers with unknown verified rates must stay fail-closed.

#### 4D. Shopify and WooCommerce adapters, workers and Data Connections

**Source evidence to inspect in read-only Node:** `keel/backend/src/modules/dataconnection/store/`, `store/shopify/`, `keel/backend/src/workers/store-connectors.worker.ts`, `keel/ai/src/ai/connectors/shopify.py`, `woocommerce.py`, `app.py`, transport/orders/inventory helpers, and migrations beginning `20261017150000_woocommerce_connections`, `20261017180000_woocommerce_inventory_invoices`, `20261017220000_shopify_store_connector`. **Python destination snapshot has generic API/database connectors but no corresponding dedicated `shopify`/`woocommerce` source files**; reverify against post-Task-6 HEAD, not merely by filename.

**Shopify:** actual OAuth/app-install/callback, HMAC/state/nonce verification and expiry, authorized scopes, shop identity binding, encrypted tokens, connection ownership, reconnect/disconnect, app uninstall, required privacy/GDPR webhooks, webhook signature, replay/idempotency, bounded queues, initial backfill, incremental sync, GraphQL cursor pagination, product variants/barcodes/SKUs, inventory locations, sales/order lines, monetary fields/tax/shipping/discount, refunds/cancellations and test-order policy. Preserve security semantics, not Node-specific syntax.

**WooCommerce:** verified shop URL and SSRF/DNS/IP protections, HTTPS and REST credential verification/scopes, encrypted storage and rotation, pagination/rate limit/backoff, variations, stock/warehouse representation, order statuses and quantities, taxes/currency/discounts/shipping, refunds/cancellations, historical imports and incremental changes, reconnect/sync/disconnect/retries. Trace exact actual Node implementation; do not invent capabilities merely because this checklist mentions them.

**Shared integration contract:** The final Python production runtime owns API and canonical connection state, schedules worker execution, maintains tenant-scoped source limits, encrypted secrets, job/checkpoint state, source-specific idempotency, dedupe and conflict policy, and writes canonical products/inventory/sales/invoices according to the approved unified Python schema. Determine one data ownership model and avoid double counting store imports versus manual uploads. Maintain traceable source lineage. Preserve Python's existing database/API connectors and promotion pipeline while extending them; do not replace a working existing path or leave Node workers as mandatory runtime dependencies.

Test both provider contracts with realistic fixture cases and isolated HTTP fakes, cross-layer import and native PostgreSQL persistence. Run live end-to-end tests against explicitly authorized Shopify development store and local WooCommerce sandbox **only when test credentials are supplied**; otherwise report them as unverified and not production-certified.

#### 4E. Manual uploads, extraction and canonical imports

Trace all file categories actually supported in Node and Python (sales, invoices, inventory, reviews, documents, etc.), extensions/MIME/file signatures, file size, template/version/header rules, SKU/name/product-ID matching, tenant-scoped uniqueness and disagreements, date/currency/decimal/quantity parsing, upload storage, extraction client, job state transitions, staging, preview/review/approval, canonical promotion, identity deduplication, partial failures/quarantine, retry/resume, duplicate files and jobs, deletion, cleanup and usage/storage accounting.

Preserve clear separation of **RAG knowledge documents** vs **canonical business transaction uploads**; do not assume every extracted PDF becomes a validated sale. Make bulk imports safe under transaction expiry and worker crashes, with realistic large-file tests. Do not create fake catalog rows or silently accept malformed/ambiguous data. Verify affected product, inventory, transaction, invoice, dashboard and quota views against actual persisted DB rows.

#### 4F. Pricing recommendations

Trace entrypoint/roles/subscription check, sales/cost/stock/competitor price inputs, source approval and provenance, currency conversion/freshness, cost-floor/margin/maximum-change/competitiveness guardrails, cold-start/no-market-data behavior, request state, upstream Python inference contract, result validation, confidence, evidence shape, persisted recommendation history, dashboard output and quota/credits. Compare Node `src/modules/pricing/service/pricing.policy.ts`, repo/service/client and Python `src/ai/pricing/*`, `routers/pricing.py` rather than assuming one is better.

Include regression coverage for the previously seen `evidence_records` / `chk_evidence_shape` failure. Keep the Python inference algorithm unless a separately approved scoped correction is necessary. No fabricated recommendations on upstream outage.

#### 4G. MPI BUSINESS / PRODUCT / COMPETITOR scopes

Trace review collection/provenance and subject ownership, review dedup and eligibility, recency, sample cap/minimum, statuses (OK vs UNKNOWN/insufficient/unavailable), confidence, sentiment counts, MPI scale and scoring, subject-specific access, provider/model version, evidence shape/IDs, worker refresh where present, persistence, credit/quota accounting and dashboard per-scope handling. Source starting points: Node `src/modules/mpi/{route,service,repo,types}`, especially `mpi.policy.ts`, and Python `src/ai/routers/mpi.py` and `src/ai/mpi/*`.

Do not confuse a lack of eligible reviews with a numeric zero MPI score. Prevent cross-tenant subject lookup, unsupported subject types, fabricated sentiment/evidence and stale “success” results. Preserve/model test the applicable Python calculation instead of rewriting it automatically. Regression test evidence-record constraints.

### 5. Unified architecture and file ownership

Design and implement within the existing Python main structure. As a starting point (verify actual code):
- Public ASGI API & routers: `CEOPRO-AI/backend/src/ai/main.py`, `src/ai/routers/`.
- Auth, quotas and tenant context: `src/ai/core/security.py`, `core/usage.py`, `core/entitlements.py`, `src/ai/db.py`.
- Stripe, subscription, contracts and provider credits: `src/ai/billing/`.
- Data collection and scheduler: `src/market_scraper/`, Python ingestion and new Python store-provider modules as appropriate.
- PostgreSQL schema/RLS: append-only migration files in `src/infrastructure/database/migrations/`, applied through existing `scripts/apply_migrations.py`.
- Frontend customer/platform workflows: existing `CEOPRO-AI/frontend/src/features/` and current API client/state conventions.

Actual exact placement is a design decision informed by the main repository's current conventions; document deviations. One subsystem/route should have one authoritative owner. Use durable jobs with clear transitions, retries/dead-letter queues, telemetry and transactional outbox/idempotency when necessary. Encrypt provider tokens, enforce tenant scope and feature rights in backend regardless of frontend state.

### 6. Mandatory documentation, architecture and one unified change ledger

Create `docs/keel-integration/` in **Python main** (do not edit Node). Keep these as **living artifacts updated in every phase**:

- `SOURCE_BASELINES.md`: read-only Node hash, Python base/current commit, Task 6 completion evidence, environment and test baseline.
- `CAPABILITY_TRACEABILITY.csv`: one row **per atomic behavior** with unique stable ID; domain, Node entry/function/recursive helpers/DB/migrations/tests, Python equivalent/DB/migrations/tests, scenario/edges, verdict, selected design, risk, phase, test IDs, status; include Python-only features.
- `FEATURE_AND_ENTITLEMENT_CROSSWALK.csv`: all Node and Python codes and their grants, limits, units, actual gate points, dashboard usage views, unresolved conflicts and approved policies.
- `DEPENDENCY_AND_SCHEMA_MAP.md`: calls/side effects, queues, workers, provider dependencies, canonical table ownership, RLS, API/UI flow, migrations/versions and seed dependencies.
- `DECISION_REGISTER.md`: every conflict and decision including commercial settings, alternatives/owner approval/date, and intentional deviations. **No blank approvals masquerading as consent.**
- `architecture/FEATURE-<domain>.md`: per-domain component ownership, end-to-end diagrams, transaction boundaries and consistency model. **ADR per overlap conflict**, before implementation; include old vs new flow and why better.
- `IMPLEMENTATION_PHASES.md`: dependency order, capability IDs, exact file scopes, prerequisite approvals, migration impact, test scope, rollback/disable strategy, acceptance and phase status.
- `TEST_EVIDENCE.md`: executable commands/results, real vs mock/fake provider, PostgreSQL version, passing/failing/skipped counts, screenshots or route response examples for dashboard flows when possible, known limitations.
- `OPEN_GAPS_AND_RELEASE_BLOCKERS.md`: uncovered requirements, unresolved approvals, required external accounts, failed/skipped integration checks, release readiness and owner decisions.
- **`UNIFIED_FILE_CHANGE_LEDGER.md` — mandatory authoritative record of EVERY added/modified/deleted/renamed file.** Include Python code, frontend, SQL, worker, tests, fixtures, configuration, lockfiles, docs and scripts. For each file: phase, exact relative path, `ADD|MODIFY|DELETE|RENAME`, why it was necessary, details of new/modified logic, capability ID(s), downstream behavior/contracts impacted, migration and test evidence, risk/compatibility, implementation status and commit/hash. For renames record both paths. No generic “misc fixes” descriptions.

**Automated ledger reconciliation:** At each phase boundary, programmatically generate `git diff --name-status <phase-base>...HEAD` and capture untracked files. Compare every changed path against `UNIFIED_FILE_CHANGE_LEDGER.md`. A missing or vague entry blocks completion. Include the change ledger itself and all newly created architecture/report files. Do not count ignored/generated caches/venv as deliverable changes. Show added vs modified vs deleted counts.

### 7. Actual implementation workflow — don't stop after analysis

Perform phases **sequentially**, in small reviewable diffs, each with a clear acceptance gate. Suggested order (adjust only with dependency evidence, record rationale):

**Phase 0 — establish baselines, exhaustive source trace and decisions (NO production edits).** Trace all scoped behaviors and dependencies; map overlapping and missing features. Produce architecture alternatives, required owner approvals and an implementation plan with bounded phases. Ask approval only for real business/policy choices, not trivial coding decisions.

**Phase 1 — consolidate shared tenant/auth/authorization and entitlements.** Reuse Python identity/billing/credit stacks. Implement approved missing Node authorization and entitlement semantics plus database constraints and feature crosswalk; carry existing Python routes/roles. Preserve Task 6 repairs. Provide native RLS/concurrency tests.

**Phase 2 — plans, Stripe, promos, custom-plan pricing/workflows and dashboards.** Implement approved differences within Python billing. Add lifecycle/quote/promo tables and UI only where needed. Test exact discounts, approvals, taxes/currency/rounding, resubscription, late webhooks, usage enforcement and status/role-based UI, using Stripe test-mode flows where possible.

**Phase 3 — canonical import contract and manual upload end-to-end.** Map data ownership and ingestion process first; adapt Node's stronger validation, staging, promotion, matching and retries into Python without damaging existing imports. Verify product/inventory/invoice/transaction state, usage and dashboard.

**Phase 4 — Shopify and WooCommerce.** Introduce dedicated Python provider adapters, secure connection/auth and scheduled workers/canonical imports using Phase 3's shared pipeline. Bring over Node code logic, policies and tests by behavior—not syntax. Build connected-source API/frontend contracts and operator observability. Provider test accounts required for live provider certification.

**Phase 5 — pricing recommendations and MPI three-scope lifecycle.** Reconcile policy/guardrails, evidence, feature/credit gates, persistence and corresponding frontend dashboards. Preserve Python algorithms, use real approved inputs, test insufficient/no-data/invalid/late/failure cases.

**Phase 6 — cross-feature verification and readiness.** Execute integrated journeys; reconcile the entire matrix, file ledger, API contract diff and migrations. Report outstanding external-provider tests and any BLOCKED results. No automatic deploy/merge.

**IMPORTANT:** If current Work execution cannot finish all phases, implement only the phase explicitly authorized for this run. Return a precise resumable handoff: immutable base/current commit, completed IDs, unresolved IDs, all file changes, tests, migrations, user decisions needed and exact next prompt. Do not combine half-tested phases or call the final system integrated.

### 8. Acceptance tests REQUIRED for every implemented capability

At minimum, implement and run applicable **unit**, **service**, **HTTP contract**, **database/RLS**, **worker/queue**, **frontend integration**, and **cross-layer end-to-end** tests. Tests must include:

- Valid happy paths and negative inputs; membership and role denial; cross-tenant isolation; no superuser bypass; missing subscription or feature.
- Quota remaining = 1 under **concurrent native PostgreSQL** requests, idempotent retry, cross-period key reuse, exact usage release on failed work, status changes between enqueue and execution, capacity race and expiry.
- Stripe reordered/duplicate signed events, wrong subscription identity, trial/cancel/reactivation/payment failure, provider reconciliation and refusal of unapproved entitlement activation; real Stripe **test-mode** lifecycle where authorized.
- Promo expiry and plan restriction, max redemption races, repeated customer use, mixed discount handling, quote revisions and custom price/cost numerical correctness including rounding.
- Shopify invalid signature/state, replay, scope shortfall, uninstall, webhook order, cursor pagination/edge responses, orders/refunds and data minimization; WooCommerce invalid/private URLs, credential failures, pagination, refunds/variations and rate limits.
- Manual upload template errors, ID vs SKU/name disagreement, malformed data, oversized/invalid file, duplicate import, partial rows, worker restart, reprocessing and canonical accounting.
- Pricing missing competitor prices/FX/cost, guardrail edges, evidence shape and upstream failures; MPI BUSINESS/PRODUCT/COMPETITOR eligible/insufficient/future/duplicate reviews, subject ownership and evidence constraints.
- UI-to-API-to-DB contract for customer and platform admin dashboards: plan pricing/usage, promo validation, custom quote and decision, connection status/imports, pricing recommendation, MPI states; no frontend-only enforcement.
- Migration up on a disposable **populated** Postgres copy; row grants/RLS/indexes/locks, historical data, repeat-run behavior, and a tested rollback or feature-disable/recovery plan. Do not edit applied historical migrations.
- Python-only billing credit/cost functions still pass; no loss of pre-existing functionality, baseline regression tests unchanged except intentional documented improvements.

**Tests must be run, not just written.** Log exact command, commit, scope, machine/DB conditions, result counts and skipped/blocked reasons. If test credentials or external access are missing, use contract fakes for code coverage but label real-provider testing `NOT RUN` and production readiness `BLOCKED` where necessary. Do not claim native concurrency success using SQLite/PGlite or that HTTP mocks prove live Shopify/Stripe behavior.

### 9. Merge and release gates (absolute)

A phase is **DONE** only if all its capability IDs are implemented/reused as designed, architecture is saved, current/full relevant tests pass, the unified ledger matches the actual diff, data migration is verified, frontend/API behavior works when applicable, and no P0/P1 security, payment, accounting or data-integrity blocker remains.

**Do not merge/deploy** if there are unresolved: tenant/RLS leaks; payment/plan state ambiguity; unapproved commercial rights changes; entitlements or credits bypass; duplicate canonical imports; insecure OAuth/webhook/credential handling; migration failures; failed applicable tests; unexamined changed files; broken dashboards; or any open `BLOCKED` capability required for that release. Existing production users/Stripe state must not be changed during development. No irreversible schema deletion without an independently approved data migration/cutover plan.

A true “zero risk of crash” guarantee is impossible. Instead demonstrate safe additive rollout, backups, reversible feature flags/traffic routing, preflight checks, staging validation, monitoring/alerting, and clear stop/go checkpoints.

### 10. Required final response from GPT Work at the end of each phase

Provide this exact structured summary with genuine evidence:

1. **Phase and branch/base/current commit**, Node read-only hash, exact scope of capability IDs.
2. **Architecture decisions**: Python reused, Node logic ported, merged design, open owner approvals, links to ADRs.
3. **End-to-end flows now operational**: dashboard → API → auth/permission → usage → DB/worker/provider → response/DB/UI; note any segments not tested.
4. **Changed files**: total add/modify/delete/rename and link to `UNIFIED_FILE_CHANGE_LEDGER.md`; show diff reconciliation result.
5. **Database migrations**: identifiers, grants/RLS, rehearsal results, data compatibility and disable/rollback plan.
6. **Tests actually executed**: commands, pass/fail/skip, native PostgreSQL concurrency, provider test mode and E2E status; baseline comparison.
7. **Remaining gaps/blockers**: exact IDs, severity, reason, whether external credentials or my policy approval are required.
8. **Verdict**: `READY FOR REVIEW`, `BLOCKED`, or `IN PROGRESS`; never label overall migration complete if future phases remain.
9. **Exact next Work task/prompt**, referencing the frozen commit and open IDs, not a vague suggestion.

**Final instruction:** Protect the business value and data-integrity rules of BOTH repositories. Reuse Python where already correct, extend it when Node adds meaningful business behavior, and implement missing capabilities in Python. No hidden feature losses, no second authority, no unverified claims, and no unlogged file changes.

---

## HOW TO RUN THIS SAFELY (for the KEEL owner)

1. Let Task 6 finish; save the code/commit, migrations and test report. The October 19 `main-repo(1).zip` is **not proof of Task 6's updated Python files**.
2. Give GPT Work this document, the frozen **read-only Node ZIP**, the **latest Python main after Task 6**, and Task 6's final report. Tell it to **execute Phase 0 only** first. The full contract stays in context for subsequent phases.
3. Review `CAPABILITY_TRACEABILITY.csv` and `DECISION_REGISTER.md`. Approve commercial/behavioral conflicts explicitly (plan limits, promos, custom contracts, credit-vs-count source policies). Do not approve generic "make it best" decisions without seeing the scenarios and affected existing users.
4. Run one bounded Work task for each approved phase, with all accumulated `docs/keel-integration/` files available. Rebase on the prior phase's verified Python commit; never run overlapping billing edits in parallel in one workspace.
5. After every phase, compare `UNIFIED_FILE_CHANGE_LEDGER.md` against real `git diff`, inspect native DB tests, API flows and frontend. Stop at any `BLOCKED` gate and fix before merging further changes.
6. Run Phase 6 and deployment rehearsal only when all scoped behavior IDs have evidence and open decisions are resolved. You, not the agent, authorize merge/deployment.

### Source-specific caveats checked from the supplied ZIPs

- Node's read-only tree contains **actual Shopify implementation files** under `keel/backend/src/modules/dataconnection/store/shopify/`, `keel/ai/src/ai/connectors/shopify.py` and a Shopify migration; it also contains **WooCommerce integration files** and store-connector workers/tests. The supplied AI Python main ZIP does **not** contain matching dedicated Shopify/WooCommerce adapter filenames. This is strong evidence for a missing dedicated implementation in the supplied snapshot, but only a current-main full flow inspection establishes the final gap.
- The Node MPI API uses `BUSINESS`, `PRODUCT`, `COMPETITOR` as the three subject types and explicitly distinguishes `UNKNOWN` from calculated scores; investigate Python's actual pipeline and dashboards before selecting its handling.
- Node pricing policy and Python pricing calculations both exist; merge validated security/guardrails around Python's model, do not transplant an AI inference implementation by default.
- Python already includes Stripe subscriptions, quota/credit infrastructure, and existing frontend billing screens. Node custom-plan and promo-code modules must be mapped against actual Python contract/credit models, not merely added as a second plan framework.
- The previous Python snapshot still had known Task 5 defects. Only the **post-Task-6** diff/tests can establish that they're repaired.

**Document status:** Prepared as a source-grounded Work execution contract. It is **not** a claim that the migration has been implemented, that tests have passed, or that the implementation architecture has received final owner approval.
