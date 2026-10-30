# KEEL Backend Target Architecture

## Status, scope and interpretation

This document is the architectural contract for KEEL's incremental backend
refactor. Future backend refactor tasks must read it together with root
`AGENTS.md` and the current source before changing implementation.

Architecture style: **Modular Monolith with Vertical Feature Boundaries**.

The contract is supported by application/use-case boundaries, Functional Core /
Imperative Shell, Ports and Adapters where side effects exist, explicit
dependency direction, and selective DDD concepts where useful. Use domain
language, value objects and explicit invariants when they clarify behavior;
do not impose aggregates or other DDD machinery without a concrete need.

This is a target and migration contract, not a claim that the code already has
these boundaries. It authorizes no implementation, rollout or policy change.
The current Git checkout remains the source of truth for runtime behavior.

- **CURRENT:** an observed implementation fact at the recorded baseline.
- **TARGET:** the desired architecture after separately authorized migration.
- **MIGRATION RULE:** a constraint on how to reach the target safely.
- **KNOWN ISSUE:** a current boundary problem, not permission to fix it globally.

Source baseline: `integration/keel-full-migration` at
`3a32a59b8d3aa600f598e0d41c4c97c29e5a4933`. This contract was introduced on
`refactor/backend-architecture-contract` from that exact commit. Later tasks
must verify their actual checkout and base rather than assume this remains HEAD.

The target does not prescribe microservices, a generic enterprise repository
framework, one global Service layer, one global Repository layer, or a
folder-heavy textbook Clean Architecture. The existing Python API and worker
processes can remain separately executed parts of one modular backend.

## 1. Decision priority and protected invariants

When decisions conflict, apply this order:

1. Security / tenant isolation invariants.
2. Financial/accounting correctness.
3. Existing explicitly characterized runtime behavior.
4. Approved product policy.
5. This `BACKEND_TARGET_ARCHITECTURE.md` contract.
6. Local package/folder aesthetics.

**MIGRATION RULE:** This ordering is not permission to perpetuate a known
security defect or ignore approved policy. If a target conflicts with observed
runtime behavior or policy, stop the affected change, characterize the conflict
and resolve the decision explicitly. Do not silently choose new behavior.
Architecture contract changes must be deliberate and reviewable.

**Every backend refactor must preserve:**

- Tenant isolation, PostgreSQL FORCE RLS semantics and least-privilege identities.
- Principal verification, tenant membership, authorization behavior and the
  separation of Tenant Owner/Admin from Platform Owner.
- Billing accuracy, subscription/trial semantics and payment-gated access.
- Data Credit / AI Credit separation, provider-price fail-closed behavior,
  provider-cost settlement and separate feature allowances.
- Transaction semantics, idempotency/replay, operation fencing and checkpoints.
- Audit trails, evidence provenance and customer-visible history.
- Existing Python functionality, model/worker behavior and all product features.
- English/Arabic behavior, localization and RTL contracts where applicable.

Preserve signed Stripe webhook verification, tenant/customer/Checkout association
and out-of-order reconciliation. A redirect, scheduled change, draft invoice or
zero-dollar trial invoice does not establish a paid post-trial period. Preserve
the trial/downgrade integrity fix: no trial truncation, invented paid term,
reset billing boundary or reset Credits. Use precise monetary arithmetic and
the approved rounding policy.

Never give runtime processes migration-admin, SUPERUSER, BYPASSRLS or broad DDL
authority. Stripe Test Clock remains local TEST-only, disabled by default and
forbidden with LIVE credentials or in production. Its private configuration
remains private. Legacy Node/reference code remains strictly read-only; Python
remains the sole operational identity, billing and accounting authority.

Refactoring is not authorization to change product/business policy. Unresolved
rates, thresholds, sampling rules, commercial terms, approval rules and privacy
requirements remain unresolved until separately approved. In particular, the
decision register's outstanding MPI eligibility/sampling specifics are not
settled by choosing MPI as the first refactor.

## 2. CURRENT architecture and migration drivers

The backend is FastAPI/Python with PostgreSQL/pgvector, Redis, MinIO and separate
workers. `backend/src/ai/main.py` wires HTTP routers and lifespan tasks.
Feature orchestration, SQL and provider work are distributed across
`backend/src/ai/`, `backend/src/market_scraper/` and infrastructure modules.
Existing folders do not prove independence or architectural layering.

| CURRENT / KNOWN ISSUE | Source evidence | Migration implication |
|---|---|---|
| Shared capability policy lives partly under RAG | `core/permissions.py` consumes `rag/access.py` | Establish a stable authority contract before relocating policy; never duplicate the role matrix. |
| Shared LLM transport lives under RAG | `rag/llm_client.py` serves assistant, marketing, discovery and comparison callers | Migrate consumers through a stable model boundary before package movement. |
| Router internals are application dependencies | Production imports of `routers.products` include commerce, extraction, dashboard and assistant code | Put reusable canonical product behavior behind an application contract before migrating callers. |
| Feature dependencies are cyclic | Reconnaissance traced a multi-module cycle spanning RAG, marketing, discovery/enrichment and comparison | Break one characterized dependency at a time; directory-by-directory moves are unsafe. |
| Retrieval can write and commit | `rag/pipeline.py::build_hybrid_index` can call embedding backfill, which persists vectors and commits | Characterize the mutation and transaction lifetime before separating read/rebuild use cases. |
| Credits use independent transactions | `billing/credits.py` opens the accounting connection for reservation/settlement | A feature rollback cannot erase a valid provider cost. |
| Forecast completion invokes RAG summary orchestration | `forecasting/consumer.py` calls structured-summary regeneration | Preserve completion/failure semantics before replacing this cross-feature choreography. |
| MPI has implicit inputs and durable output | Scoring/cold-start modules read environment globally; pipeline defaults to `date.today()` and commits evidence | Capture policy/time and persistence behavior before extracting boundaries. |

These are migration drivers, not a finding that every named path is broken.
The preceding architecture reconnaissance was static inspection; it did not
certify live providers or execute the backend test suite.

## 3. TARGET: three conceptual categories

```text
KEEL Backend
|
+-- Platform Authorities
|
+-- Feature Modules
|
+-- Infrastructure Adapters
```

These categories describe responsibility and ownership, not mandatory new
directories or a requirement to move existing packages immediately.

### Platform Authorities

Established authorities include authentication/principal verification,
TenantContext, authorization/capability policy, PostgreSQL RLS/restricted
identities, billing/subscriptions, usage/entitlements, AI Credits, Data Credits,
provider accounting, operation receipts/fencing and audit/history.

They are not feature-owned implementations. Features consume their stable
contracts without reproducing policy. Authorities may combine Python logic,
database commands, policies, constraints and triggers; a Python wrapper alone
does not replace database enforcement.

### Feature Modules

Vertical feature boundaries follow actual business responsibilities:

- Market Perception Index (MPI); deterministic Insights; Reporting/exports.
- Products/Inventory; Sales/quick sale; Reviews/Sentiment; Forecasting; Pricing.
- Documents/knowledge ingestion/retrieval; Assistant/RAG.
- Discovery; Competitor enrichment; Market analysis; Market collection/price lookup.
- Marketing; Notifications/alerts; Extraction/ingestion; Commerce/connectors.
- Dashboard/read models, workspace/onboarding workflows and application knowledge
  where they own bounded use cases.

CURRENT package names include `ai/mpi`, `ai/insights`, `ai/dashboard`,
`ai/extraction`, `ai/forecasting`, `ai/pricing`, `ai/rag`, `ai/marketing`,
`ai/market_inputs`, `ai/sales`, `ai/sentiment` and `market_scraper` modules.
Logical feature boundaries need not equal those package boundaries.

### Infrastructure Adapters

Concrete mechanisms include PostgreSQL, Redis, MinIO, HTTP providers, Stripe,
LLM/model providers, search/data providers, SMTP, queue/worker transport,
filesystem and local model runtime. Adapters implement needed contracts;
they do not acquire ownership of business or financial policy.

## 4. TARGET dependency direction

```text
HTTP / Worker / CLI Adapter
          |
          v
Application Use Case
          |
          v
Domain / Functional Core
          |
          v
Narrow Ports
          ^
          |
Infrastructure Adapters
```

The arrows express source dependency direction toward business intent, not a
requirement for pure domain functions to perform I/O. Usually the application
use case invokes ports and passes explicit values to the functional core.
Ports belong with the application/domain responsibility that needs them;
infrastructure depends on those contracts. Composition wires implementations
at the delivery/bootstrap boundary without making domain code import adapters.

Application boundaries may invoke platform authorities through stable
contracts. A feature must not import FastAPI or a provider SDK merely to
express a business decision.

## 5. Routers and delivery adapters

**TARGET:** Routers are thin HTTP delivery adapters. Allowed responsibilities:

- HTTP parsing, request schemas and authentication dependencies.
- Calling an application use case with established caller context.
- Mapping application results/errors into HTTP responses.

Routers must not house business rules, shared canonical mutations, provider SDK
calls, credit formulas, arbitrary commits, cross-domain orchestration or reusable
application services. Worker/CLI adapters likewise translate delivery inputs,
invoke handlers and map outcomes to their transport contracts.

**KNOWN ISSUE:** `routers.products` currently supplies reusable internals to
production modules. **MIGRATION RULE:** Introduce a public product application
contract around existing behavior, characterize it and migrate callers before
removing old paths. Do not fix all callers during an unrelated feature refactor.

## 6. Application/use-case boundaries

**TARGET:** An application use case answers: **What steps make up this operation?**
It owns business-operation choreography: domain decisions, readers/writers and
other ports, transaction ownership, platform-authority calls, post-commit actions
and external side effects where appropriate.

Illustrative target names, not claims of existing classes, are
`ComputeMpiSummary`, `GenerateInsights`, `ExportSalesReport`, `RecordQuickSale`,
`CreateProduct`, `RunForecast`, `AskQuestion` and `EnrichCompetitor`.
Functions are valid use-case boundaries; classes and naming conventions are
optional. Inputs/results should express business intent without raw HTTP
responses or provider payloads. Provider transport details do not belong here.

Use cases receive dependencies explicitly through ordinary construction or
function parameters. Do not require a DI framework or a global service locator.
State transaction and side-effect expectations in the public contract.

## 7. Domain / Functional Core

**TARGET:** Business decisions are pure or deterministic where practical:
MPI scoring, insight ranking, pricing guardrails, forecast choice, landed-cost
calculation, eligibility, classification/ranking and citation validation.

Domain decisions generally know nothing about FastAPI, psycopg, Redis, MinIO,
Stripe, Tavily, Groq, HTTP response JSON or environment variables. Supply explicit
values and immutable policies instead. Serializable business results are fine;
provider/HTTP response shapes must not become domain contracts by accident.

Not every feature needs a `domain/` directory. A bounded pure calculation can
remain a simple module. Selective value objects such as Money must preserve
existing currency/precision/rounding semantics rather than unify unlike policies.

## 8. Narrow ports and concrete adapters

**TARGET:** Ports are task-oriented contracts describing what a use case needs:
`ReviewReader`, `SubjectReader`, `EvidenceWriter`, `SalesReportReader`,
`PdfRenderer`, `LanguageModel` and `PublicResearchSource`.

Do not impose universal `Repository.get/save/update/delete` interfaces across
features. Ports must not expose generic database connections, query builders,
SDK clients or provider JSON as the default business interface. Existing
connections may remain within a bounded transitional adapter until transaction
semantics have been characterized.

Illustrative adapter relationships:

| Infrastructure adapter | Contract implemented |
|---|---|
| `PostgresReviewReader` | `ReviewReader` |
| `PostgresEvidenceWriter` | `EvidenceWriter` |
| `TavilySearchAdapter` | `PublicSearch` |
| `MeteredModelGateway` | `LanguageModel` |
| `MinIOAssetStore` | `AssetStore` |
| `SMTPMailer` | `Mailer` |

Credentials, SDKs, HTTP payloads, response parsing, timeouts and provider-specific
retry behavior belong on the infrastructure side. The application retains
operation-level retry/idempotency policy. Preserve the existing metering,
network-security and failure-mapping controls when wrapping an adapter.

## 9. Consume platform authorities; do not duplicate them

**MIGRATION RULE:** TenantContext, RLS, authorization, billing, subscriptions,
usage, Data/AI Credits, provider cost schedules/settlement, operation receipts
and audit retain their established authority during feature refactors.

- RAG does not calculate AI Credit pricing.
- Market Intelligence does not calculate Data Credit pricing.
- Marketing does not create a second provider-cost ledger.
- Feature code does not recreate the role matrix or paid-access policy.
- An adapter must not bypass receipt fencing, RLS or accounting for convenience.

CURRENT authority locations include `ai/core/security.py`, `core/permissions.py`,
`rag/access.py`, `ai/db.py`, `infrastructure/db_pool.py`, `ai/billing/`,
`core/usage.py`, `core/entitlements.py`, `core/operation_receipts.py` and SQL
schema/migrations. Audit/history is distributed across command/trigger audit,
financial ledgers, receipts and feature evidence; no new generic audit service
may silently replace those records.

Preserve responsibilities of `ceopro_app`, `ceopro_billing_setup`,
`ceopro_billing_webhook` and `ceopro_credit_accounting`. Renaming or wrapping
an authority does not authorize expanding its permissions.

## 10. Transactions must model reality

**MIGRATION RULE: Transaction boundaries must model reality.**

```text
feature business transaction != provider-credit/accounting transaction
```

A provider cost can remain valid even if later feature persistence rolls back.
Do not introduce a generic UnitOfWork that pretends all effects share one atomic
transaction. A narrowly scoped database transaction helper may be useful only
when it represents a real existing boundary and preserves its semantics.

Object storage, remote provider calls, SMTP delivery and queue dispatch are not
fictionally atomic with PostgreSQL. Use cases must state transaction ownership,
durable state transitions, compensation, retry and uncertain-outcome behavior.
Do not label every external failure refundable or every retry safe.

**CURRENT:** Internal commits exist in feature pipelines, accounting and helper
calls. Pooled connection wrappers restore tenant/user/language/timezone context
after commits/rollbacks. Stripe event serialization includes session-level locks
that intentionally survive commits. These mechanisms must be understood first.

**MIGRATION RULE:** Characterize existing ownership, commit placement, rollback,
savepoints, post-commit actions and partial failure before moving boundaries.
Preserve provider-start/settlement distinctions and durable history. A business
transaction, accounting transaction and storage compensation may intentionally
have different lifetimes.

## 11. Workers, queues and execution

**TARGET:** Delivery paths reuse the same application operation where their
business intent is the same:

```text
HTTP -----+
          |
Worker ---+--> same Application Use Case
          |
CLI ------+
```

Workers are delivery/execution adapters around application handlers, not
alternative business-rule implementations. Transport-specific authentication,
worker identity, payload validation, acknowledgment and scheduling still differ
from HTTP delivery; do not fabricate a human principal for background work.

Preserve receipt fencing, leases, idempotency, retry/replay, provider-start state,
checkpoint semantics, pending/dead-letter handling and job heartbeats. Redis
signals do not replace durable receipt authority. Multi-process behavior,
process-local caches/locks and outage fallbacks require explicit tests.

CURRENT execution includes forecast, image, connector, price-collection,
analysis, discovery, enrichment and maintenance workers plus API lifespan tasks.
Forecasting also has threaded/API generation paths. Worker migration comes
later; neither this contract nor a thin-wrapper exercise authorizes changing
delivery guarantees or restructuring workers now.

## 12. Cross-feature communication and shared code

**TARGET:** Feature A calls Feature B's explicit public application contract.

```text
Feature A -> Feature B public contract

Avoid: Feature A -> Feature B router -> private repository/helper
```

Current dependencies requiring eventual correction include production imports
of `routers.products`, `core.permissions -> rag.access`,
marketing/discovery/comparison access to `rag.llm_client`, and forecast completion
calling RAG summary orchestration. The cyclic RAG/marketing/discovery/enrichment/
comparison graph must be reduced through characterized boundaries, not hidden
by moving imports into a new folder or making them lazy.

Shared code must earn shared status. Do not create dumping grounds named
`utils/`, `helpers/`, `common/`, `services/` or `repositories/`. Promote a concept
only when multiple bounded features need the same stable abstraction and its
ownership is clear. TenantContext, Money, language/business-time context and
logging/redaction contracts may legitimately be shared. Feature-specific
concepts remain feature-owned. Similar-looking formulas are not proof of the
same business policy.

## 13. Configuration, time and error boundaries

**TARGET configuration flow:**

```text
environment/settings -> configuration adapter -> immutable policy/config value
                                                -> application/domain
```

Avoid hidden import-time `os.getenv(...)` reads in deterministic decisions.
CURRENT MPI scoring and cold-start modules capture policy values globally.
Migrate those inputs incrementally while preserving current defaults and
configuration failure behavior. Do not perform one global settings rewrite.

**TARGET time:** Make today, timezone, recency, expiry, billing windows and period
boundaries explicit through an injected or established business-time/clock
contract. Preserve tenant calendars/timezones and existing database/Python clock
semantics until characterized. Replacing scattered `date.today()` or
`datetime.now()` calls must not silently change boundary-day results.

**TARGET errors:**

```text
Domain/Application Errors -> Delivery Adapter Mapping
                          -> HTTP status / worker failure / CLI output
```

Business and infrastructure layers should not casually raise FastAPI
`HTTPException`. Translate provider/database failures to the appropriate stable
application outcome; delivery adapters map it to transport semantics. Preserve
existing public status codes, reason codes, localized messages, denial behavior,
redaction and retryability until a separately approved change says otherwise.
This document changes no current errors.

## 14. Folder guidance: physical movement last

For a sufficiently complex feature the eventual conceptual shape may be:

```text
feature/
    application/
    domain/
    ports/
    infrastructure/
    api/
```

This is optional guidance, not a uniform tree. A simple feature may remain
`trade/landed_cost.py`. Do not add empty layers, mandatory classes or one-file
interfaces without a useful boundary.

**MIGRATION RULE: Do not begin a refactor by moving folders.**

```text
responsibility boundaries
        |
        v
dependency direction
        |
        v
behavior verified
        |
        v
caller migration
        |
        v
physical package movement
```

A directory named `domain/` that imports FastAPI, PostgreSQL or provider code
does not establish clean architecture. Dependency contracts and behavior matter
more than folder names or counts.

## 15. Standard lifecycle for each subsystem

Each phase must be independently reviewable. Scope phases to bounded milestones;
do not use this sequence to justify a giant backend rewrite.

| Phase | Required purpose |
|---|---|
| 0 - Characterize current behavior | Freeze inputs/results/errors, permissions, side effects, persistence, transactions and callers. |
| 1 - Identify/extract deterministic decisions | Make decision inputs explicit without changing formulas or policy. |
| 2 - Establish application/use-case boundary | Describe the existing operation and delegate to existing behavior initially where useful. |
| 3 - Introduce narrow ports | Define only the capabilities this operation needs. |
| 4 - Adapt existing DB/external effects | Wrap current mechanisms while preserving authority and failure semantics. |
| 5 - Make transaction ownership explicit | Move ownership only after failure/commit characterization; represent compensation honestly. |
| 6 - Simplify orchestration and migrate callers | Migrate delivery and cross-feature callers incrementally. |
| 7 - Remove obsolete dependency paths | Verify imports, dynamic calls, workers and SQL integration no longer depend on them. |
| 8 - Move/package files | Move only after boundaries and callers are stable. |
| 9 - Final regression characterization | Verify business outcomes and record actual evidence and remaining limits. |

Use appropriate unit, API, native DB/restricted-role/RLS, transaction-failure,
worker/concurrency and browser tests. Use disposable infrastructure and synthetic
fixtures for mutation tests. Distinguish mocks/fakes from real provider acceptance;
never claim a 200 response or heartbeat proves a completed business outcome.
Report PASS / FAIL / BLOCKED and exact scope. Any separately authorized
data-changing rollout requires a verified recoverable backup; migrations remain
forward-only. This contract authorizes no such rollout or provider test.

## 16. Mandatory Git strategy

Protected integration/base branch: `integration/keel-full-migration`.

**MIGRATION RULE:** Never implement or commit architecture/refactor changes
directly on that branch. For each authorized implementation milestone:

1. Read applicable instructions; verify repository root, intended integration
   base, exact base commit, working-tree status and protected modifications.
2. Create and switch to a new dedicated local branch from the verified exact
   base before modifying source or architecture documentation.
3. Verify the current branch is no longer `integration/keel-full-migration`.
   If branch creation/switching fails, stop before editing.
4. Keep one bounded subsystem/milestone per branch; preserve unrelated changes
   and untracked files. Stage only intended files.
5. Review and run appropriate checks before integration; commit only on the
   dedicated branch when authorized.
6. Never merge, rebase or push without explicit authorization.

Examples: `refactor/backend-mpi-phase-0`, `refactor/backend-mpi-phase-1`,
`refactor/backend-insights-phase-0`, `refactor/backend-rag-phase-0`.
When a task resumes on an already-created dedicated branch, verify its identity
and base rather than recreating or switching branches unnecessarily.

## 17. Whole-backend migration waves

| Wave | Scope | Rationale and deliberately preserved dependencies |
|---|---|---|
| 0 | Architecture contract and characterization baseline | Record authorities, dependency/transaction contracts and test strategy; no implementation implied. |
| 1 | Market Perception Index (MPI) | Establish the first bounded feature pattern while consuming current auth/RLS/entitlements and evidence storage. |
| 2 | Deterministic insights; reporting/exports; selected simple pure contracts | Build read/decision boundaries, then streaming/rendering/allowance lifetime patterns; preserve authority engines. |
| 3 | External boundaries: HTTP/search/provider seams, SMTP, selected storage/model facades | Make side effects explicit before complex orchestration; wrap existing accounting/network controls without replacing them. |
| 4 | Canonical business use cases: products/inventory, quick sale, review import/sentiment, deterministic analytics/pricing portions | Remove business dependence on routers using stable application contracts; preserve history and canonical transaction policy. |
| 5 | Ingestion and commerce orchestration | Reuse canonical contracts for review/promotion/posting; retain receipts, source identity, checkpoints and provenance. |
| 6 | Complex intelligence: documents/retrieval, assistant/RAG, discovery, competitor enrichment, market analysis, marketing | Reduce cycles and explicit side-effect choreography using earlier patterns; retain grounding, metering and customer history. |
| 7 | Workers/queues/concurrency-heavy execution | Migrate handlers after application contracts stabilize; preserve leases, replay, locks and acknowledgment semantics. |
| 8 | Shared runtime infrastructure | Refactor cache/index lifecycle, transport/storage/session integration after dependents expose tested contracts. |
| 9 | Financial/security core: billing, Credits, usage/entitlements, authentication, authorization, platform commands; DB/session wrapper last if justified | Highest-blast-radius internals move only after consumer contracts and native failure/concurrency evidence exist. |

Wave membership may evolve as characterization reveals new dependencies.
Changes must be deliberate, evidence-backed architecture decisions, not an
excuse to expand an implementation branch. Worker/concurrency characterization
starts early; Wave 7 is when execution machinery changes. Likewise establish
seams around financial/security authorities early, but preserve their policy and
implementation until the late-stage work is separately authorized.

## 18. First reference refactor: MPI

```text
FIRST REFERENCE REFACTOR:
Market Perception Index (MPI)
```

MPI combines low coupling, meaningful scoring logic, tenant/RLS consumption,
bounded evidence persistence, HTTP APIs and strong existing characterization
foundations. It has no external paid-provider call, worker/queue or financial
authority. It can establish application, functional-core, reader/writer port,
adapter, injection, error-mapping and transaction patterns without changing
the most central KEEL authorities.

**CURRENT:** `GET /mpi/summary` computes and persists FACT/UNKNOWN evidence and
the pipeline commits. The router also commits. `GET /mpi/history` reads existing
evidence. MPI is not assumed to be stateless or a pure read feature. The frontend
`MarketPerceptionPanel` reaches these endpoints through `mpiApi`.

Phase 0 must characterize scoring, eligibility/subject visibility, evidence and
history payloads, errors, current authorization/entitlements, repeated requests,
time/configuration defaults, commits and persistence failures. Existing scoring,
cold-start, pipeline, router, native DB/RLS and history tests are foundations,
not proof of current passing results. Preserve current policy while unresolved
MPI policy decisions are addressed separately. Do not start by moving `mpi/`
or removing internal commits.

## 19. Explicit anti-patterns

Avoid god services, god repositories, shared-utility dumping grounds, business
logic in routers, provider SDKs in domain/application logic, cross-feature private
imports, hidden commits/network calls, environment reads inside pure decisions,
duplicate authorization/pricing/Credit rules, fake atomicity across DB/provider/
storage effects, architecture-by-folder-name and big-bang migrations.

Transitional wrappers are acceptable when their limitations and exit criteria
are explicit. Renaming existing coupling is not completion of a migration.

## 20. Source references and contract maintenance

Use the current source and these verified repository references when applying
the contract. They supply runtime/decision context, not blanket implementation
or provider-operation authorization:

- [Repository instructions](../AGENTS.md).
- [Current system architecture](ARCHITECTURE.md).
- [Backend guide](../backend/README.md).
- [Workers](WORKERS.md) and [testing](TESTING.md).
- [Database roles and migrations](DATABASE.md).
- [Decision register and outstanding policy specifics](keel-integration/DECISION_REGISTER.md).
- [Trial/downgrade integrity](TRIAL_DOWNGRADE_INTEGRITY_FIX.md).
- [Checkout database privilege review](CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md).
- [MPI pipeline](../backend/src/ai/mpi/pipeline.py) and
  [MPI routes](../backend/src/ai/routers/mpi.py).
- [Retrieval/index pipeline](../backend/src/ai/rag/pipeline.py),
  [capability policy](../backend/src/ai/rag/access.py) and
  [shared LLM transport](../backend/src/ai/rag/llm_client.py).
- [Credit accounting](../backend/src/ai/billing/credits.py),
  [operation receipts](../backend/src/ai/core/operation_receipts.py) and
  [tenant connection wrapper](../backend/src/infrastructure/db_pool.py).

Update this contract deliberately when an approved architecture decision changes.
Update existing relevant documentation with measured implementation progress;
do not describe an unimplemented target as completed or generate competing
architecture contracts. Task authorization, root instructions, invariants and
the decision priority above remain binding.
