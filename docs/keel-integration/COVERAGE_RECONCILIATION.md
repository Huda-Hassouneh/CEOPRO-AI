# Mechanical coverage reconciliation

This is source coverage, not runtime equivalence or test coverage. Every source candidate remains in the index, including out-of-scope preservation dependencies; no unknown is silently discarded.

- Indexed source files: 1564.
- Python mounted HTTP decorator handlers: 148, all assigned a capability family or preservation dependency.
- Frontend HTTP call candidates: 338 in both trees.
- Static reachable files from API/frontend/scripts/worker roots: 1068; nonreached source files: 496, explicitly UNVERIFIED, never automatically dead.
- Resolved local import edges: 4391; attribute/external/unresolved terminals: 836.

| Mounted route family | Handler count |
|---|---:|
| AUTH | 14 |
| AUTH/ENT | 19 |
| CONNECT | 6 |
| IMPORT | 5 |
| IMPORT/ENT | 6 |
| IMPORT/MPI | 2 |
| IMPORT/PRICE/MPI/ENT shared read/write dependency | 19 |
| MPI | 1 |
| MPI/ENT | 2 |
| PRICE | 2 |
| PYTHON_PRESERVE_DEPENDENCY | 60 |
| SUB/PROMO/CUSTOM | 12 |

## Required closure before phase completion

Use ACTIVE_PYTHON_ROUTES.csv for mounted route/handler/dependency; FRONTEND_HTTP_CONTRACTS.csv for actual client methods/payload callsites; ROUTE_CANDIDATES.csv for Node routers/mount declarations and legacy candidates; REACHABILITY.csv plus IMPORT_GRAPH_RESOLVED.csv for static transitive imports; FUNCTION_CALL_INDEX.csv for helper call targets; PERSISTENCE_SURFACES.csv and SQL_OBJECT_LINEAGE.csv for read/write/policy surfaces; ENVIRONMENT_DEPENDENCIES.csv and TEST_CATALOG.csv for external/runtime/test dependencies.

Plan/source code constants reconcile to **21 Node codes** and three Python-only codes; report_generation/monthly_reports and team_members/team_seats are mapped once. Marketing/RAG/report/forecast/competitor rights are retained dependency obligations even where their algorithms are out of scope.

Webhook topics are explicitly enumerated in FEATURE-stores.md; Stripe event handling branches are _handle_locked in billing/webhooks.py and referenced in SUB-008..010. Stream registration is market.scrape.requested/dead and connector polling in DEPENDENCY_AND_SCHEMA_MAP.md. Notification outbox/quote consumer are proposed, not mounted existing behavior.

A human/runtime closure pass must resolve dynamic imports, callback callsites, SQL function caller grants and frontend-to-handler DTO/status/role joins for each implementation slice, then produce distinct endpoint/job/gate/write coverage with zero unexplained in-scope surfaces. These indexes intentionally do not pretend 2,596 raw route/client matches are 2,596 active server endpoints. TRACE-001 remains open until those joins are verified.


## Phase 0R refinement

See [PHASE0R_README.md](PHASE0R_README.md), [SOURCE_SNAPSHOT_RECONCILIATION.md](SOURCE_SNAPSHOT_RECONCILIATION.md), [SCHEMA_VERIFICATION.md](SCHEMA_VERIFICATION.md) and [DOMAIN_READINESS.md](DOMAIN_READINESS.md). Exact capability source roots, real schema lineage and thirteen concrete owner questions have been refined; no implementation or approval occurred. Earlier 56-pass/94-skip backend and 90-pass frontend/build logs are prior Phase 0 evidence, not rerun Phase 0R acceptance. SOURCE-001 and VERIFY-001 remain blocked. Raw lexical DB evidence is nonauthoritative.
