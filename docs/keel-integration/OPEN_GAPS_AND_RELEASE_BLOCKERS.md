> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Open gaps and release blockers

**Overall verdict BLOCKED; no integration implementation is complete.** This is a bounded Phase 0 review pack, with explicit incomplete verification rather than invented parity.

| ID | Severity | Evidence / missing capability | Required unblock |
|---|---|---|---|
| SOURCE-001 | P0 | Supplied main HEAD predates uncommitted Task 6 code/migration/tests; no clean verified post-Task-6 SHA | Owner/team supplies or establishes clean reviewed commit, exact diff and test logs; compare frozen content and re-trace changed branches |
| VERIFY-001 | P0 | No native PostgreSQL server; 94 DB checks skipped here; Task 6 native races skipped | Dedicated PG17 native multi-session suite, runtime-role login, RLS/catalog verification, concurrency and populated migration rehearsal |
| AUTH-001/AUTH-002 | P0 | Bootstrap/session outage policy unresolved; platform permission/activation enforcement not equivalent | Approve identity/authority ADRs and implement authorized Python boundaries without second issuer |
| ENT-001..011 | P0 | 21-code mismatch, missing-limit fail-open outside four codes, source/cap competitor policy, execution-time and multi-replica cache obligations | Approve ENT-001 and accounting, implement one evaluator/receipt/worker model and last-slot tests |
| SUB-001..014 | P0 | Task 6 repaired only targeted defects; effective entitlement transition, catalog and grace/currency decisions remain | Approve catalog/transition ADR; retain Task 6; run full native/Stripe TEST and UI contracts |
| PROMO-001..005 | P0 | Hosted promo entry is not Node managed lifecycle; no native reservation/redemption race proof | Approve reuse/terms/currency/stacking/redemption rules and implement Python/API/UI/provider mapping |
| CUSTOM-001..013; PLATFORM-* | P0 | Node configurator/economics/quote/operator workflows absent/partial; current Python manual contract grants are different authority condition | Approve quote activation/cost/role ADRs; preserve current grants/provider costs; implement UI/API/DB/outbox |
| IMPORT-001..012; CONNECT-004 | P1 | Structured invoice/inventory preview/identity differences; generic connectors stop at staging | Approve canonical ownership/review rules; implement lineage/durable canonical promotion and preserve Python invoice mirrors |
| STORE-*, SHOP-*, WOO-* | P0 security / P1 delivery | Dedicated Python store lifecycle/adapters/OAuth/webhook/privacy absent; generic API cannot certify them | Implement approved Phase 4, validate credentials/signatures/SSRF/fencing/refunds/native cross-layer; live authorized sandboxes |
| PRICE-001..008 | P0 access / P1 behavior | Pricing routes have tenant auth but no approved ai_pricing gate/count; policy/FX/freshness/fallback conflicts | Approve policy and quotas; protect single/bulk/aliases; preserve Python algorithm, evidence/request/settlement and modal contract |
| MPI-001..010 | P1 | Three Python subject calculations exist; review/subject safety and low-sample contract differ; no direct three-scope UI found | Approve sample/right semantics; add subject/eligible/provenance/refresh orchestration and UI while preserving score math |
| ACCOUNTING-001 | P0 | Partial committed imports/provider billed failures/replayed reports must not be refunded or double-debited blindly | Approve failure-charge policy; durable receipts, settlement/reconciliation and crash tests |
| PRIVACY-001 | P0 | Shopify redaction/retained financial/manual shared data conflict not owner-approved | Define attributable fields/retention/exclusions/audit; signed durable processing and tests |
| PROVIDER-001 | P0 | Stripe TEST, Shopify dev app/store, Woo sandbox, verified paid-provider schedules not available | Supply authorized test resources locally; unknown rates stay fail-closed; run real-provider tests |
| TRACE-001 | P1 | Static evidence indexes include unresolved dynamic imports/callback/function and SQL terminal branches | Resolve each affected branch before implementation slice; live route/schema/worker coverage reconciliation; no code declared dead/equivalent from filename |
| RELEASE-001 | P0 | Full original suites, browser E2E, populated data/grant totals, monitoring/disable drill unrun | Phase 6 acceptance; ledger exact to clean Git base; explicit owner merge/deployment approval |

No passwords/tokens are requested in chat. Configure test credentials locally through existing secrets conventions. No invented commercial prices/FX/provider outputs, no production mock data and no fabricated end-to-end success are acceptable unblocks.

## Preservation register

All Python-only rows CREDIT-001..006 and CONNECT-001/003 are mandatory regression obligations. Preserve credit price verification, spending caps/kill switches, separate budgets, append-only ledger, conservative stale-charge/reconcile, existing manual contracts/CLI, workspaces, generic DB/API/vault, weighted MPI/compare, pricing estimation/demand, RAG references, marketing, discovery/enrichment, forecasts and historical/user/business data. Touch unrelated models only for separately approved corrections, never as an integration shortcut.

Capabilities that were mentioned in a checklist but not proven implemented in either source remain UNVERIFIED (for example all advertised secondary data provider choices, full refund support, broad session migration and legal retention terms). Their dependency is explicit; no new capability is invented from a name.


## Phase 0R refinement

See [PHASE0R_README.md](PHASE0R_README.md), [SOURCE_SNAPSHOT_RECONCILIATION.md](SOURCE_SNAPSHOT_RECONCILIATION.md), [SCHEMA_VERIFICATION.md](SCHEMA_VERIFICATION.md) and [DOMAIN_READINESS.md](DOMAIN_READINESS.md). Exact capability source roots, real schema lineage and thirteen concrete owner questions have been refined; no implementation or approval occurred. Earlier 56-pass/94-skip backend and 90-pass frontend/build logs are prior Phase 0 evidence, not rerun Phase 0R acceptance. SOURCE-001 and VERIFY-001 remain blocked. Raw lexical DB evidence is nonauthoritative.
