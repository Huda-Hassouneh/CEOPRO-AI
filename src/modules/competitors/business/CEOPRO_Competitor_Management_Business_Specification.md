# CEOPRO-AI — Feature 07: Competitor Management

**Feature code:** `competitor_management`  
**Feature type:** Boolean (`lifetime`)  
**Companion capacity entitlement:** `tracked_competitors` (maximum simultaneously tracked competitors)  
**Evidence:** Saved CEOPRO frontend (2026-10-09), backend (2026-10-10), and AI team repository (saved 2026-10-10). This is a source-code review, **not** proof of live production worker execution.  
**Status:** Partly implemented; core customer-facing creation and production enforcement need fixes.

## 1. Business purpose

Competitor Management helps a business owner identify relevant competing businesses, add or stop monitoring them, compare their overlapping products, and spot meaningful competitive changes. The decision is not simply “who is cheaper?” It is “who competes with the products I actually sell, and what changed that I should act on?”

**Example — a pharmacy:** The owner sells 30 skincare products. They track nearby and online pharmacies that stock competing or identical products. They want to know which pharmacies are relevant, whether their prices changed, when observations were made, and which competitor offers a valid comparison. Prices in different currencies, different pack sizes, outdated observations, and unapproved sites should **not** be compared as though equivalent.

A useful user journey: (1) add or discover competitor, (2) confirm identity and relevance, (3) map comparable products, (4) approve lawful/allowed collection source, (5) start scheduled monitoring, (6) view verified latest observations and history, (7) adjust or stop tracking. Discovery and monitoring are distinct operations.

### Boundaries

- **`competitor_management`** controls management/tracking access, not the number of competitors.
- **`tracked_competitors`** is a separate capacity ceiling, **not** a request/month allowance.
- **`market_intelligence`** reads competitor-related data for analysis; it does not replace managing relationships.
- **`ai_pricing`** and **`market_perception`** have separate entitlements. Tracking a competitor does not automatically include those features.
- **Monitoring frequency** is configuration/plan metadata of `competitor_management`, **not** a standalone feature or customer limit to invent.

## 2. Availability, quotas, and expected monitoring

The reviewed source of truth is `backend/src/config/production-plans.ts`, catalog `2026-10-v2`.

| Standard plan | Monthly base price | Competitor Management | Tracked competitor cap | Configured monitoring interval | Nominal checks/month per eligible source |
| --- | ---: | --- | ---: | --- | ---: |
| Starter | $55 | Not included | Not assigned | N/A | N/A |
| Growth | $140 | Included | 10 | 1,440 minutes (24 hours) | 30 |
| Enterprise | $350 | Included | 50 | 360 minutes (6 hours) | 120 |

The per-month checks are *catalog planning quantities*, not verified collection throughput. Provider policy, blocked sources, missing product mappings, worker availability, cost gates, and scheduling determine actual completed observations. The separate custom-plan configurator accepts monitoring frequency metadata and prices it with the competitor count; this must be mapped to actual eligible `data_sources.sync_frequency_minutes` and verified after checkout rather than left only in a quote snapshot. Do not automatically change legacy plan contracts.

**Entitlement rule:** On every create/reactivation/discovery that changes a tenant's tracked count, enforce `competitor_management` and the effective `tracked_competitors` ceiling in a race-safe database transaction. Reading or updating a competitor also requires tenant authorization. Untracking may free capacity; only an approved business rule should determine whether the historic evidence remains visible.

## 3. Current frontend — verified behavior

Files reviewed under `frontend/src/features/market-intelligence/`:

| Experience | Source | Actual behavior |
| --- | --- | --- |
| Tracked list | `pages/CompetitorsPage.jsx`, `hooks/useCompetitors.js`, `api/competitorsApi.js` | Fetches live `GET /competitors`; client-side search, sorting and 10-row pagination |
| Competitor details | `pages/CompetitorProfileDetailPage.jsx`, `hooks/useCompetitorProfile.js` | Fetches live `GET /competitors/:id`; shows mapped products/prices and a price-change timeline |
| Add competitor | `pages/AddCompetitorPage.jsx` | **Preview only**: calls `addPreviewCompetitor(values)` and navigates away, not the live create API |
| Create API / hook | `api/competitorsApi.js`, `hooks/useAddCompetitor.js` | Real POST client exists, but it is not used by Add page; the hook's mutation function also doesn't adapt the two-argument `create(companyId,payload)` signature |
| Route gate | `app/router/index.jsx` | Competitors list/profile/add require `market_intelligence` and `competitor_management` in UI |
| Capacity UI | Add page `FeatureGate featureCode="tracked_competitors" mode="consume"` | Frontend gate only; does not replace an authoritative server-side capacity check |

Additional UX discrepancies: the industry dropdown has only static Telecom/Internet/Analytics options; the filter button is not wired; the table has a visual action menu with no handler; the “updated” sort actually uses `addedAt`, not last scan time; no untrack/edit capability; competitor detail labels own price using **competitor currency**, which may be wrong; some error/empty messages are not translated. The preview array added by the Add page is **not** what the real list hook reads.

## 4. Current Node backend — verified behavior

Paths: `backend/src/modules/competitors/{route,controller,service,repo}/` and `backend/src/app.ts`.

| HTTP endpoint | Current behavior | Important limitation |
| --- | --- | --- |
| `GET /competitors` | Reads tracked tenant links joined to global competitors, newest `added_at` first | No explicit `competitor_management` entitlement middleware |
| `POST /competitors` | Requires name; finds global competitor by **exact name** or creates a `visibility='GLOBAL'` row; upserts tenant link with `is_tracked=true` | No entitlement/capacity guard, robust schema validation, canonical identity by website, or explicit authorization for altering shared global identity |
| `GET /competitors/:competitorId` | Reads tenant link, mapped own products, latest *available* prices and derived price changes | Does **not** require `is_tracked=true` once link exists; treats untracked records as viewable; does not filter observation source policy, freshness, exactness, or currency consistency |

The route uses `authenticateUser` and `requireTenant`, but not feature-specific access/limit middleware. The router is **actually mounted at `/competitors`**; route-file comments suggesting `/companies/:companyId/competitors` are stale. The service throws generic errors for invalid names and missing profiles, so review actual HTTP status mapping.

The profile API deliberately returns empty `metrics`, `strengths`, `weaknesses`, and `presence` structures. These are **not proof of zero market performance**; the profile repository does not calculate them.

A mapped product currently appears only when it has at least one available price. Better UX distinguishes **mapped but not yet scanned**, **restricted**, **unavailable**, and **stale** from **no mapping**.

## 5. Core database model and ownership

| Database table | Why needed | Main producer / owner |
| --- | --- | --- |
| `global_competitors` | Canonical competitor identity, website, scope, industry, country | Node manual create; AI discovery also creates tenant-private identities |
| `tenant_competitors` | Per-tenant competitor association; `is_tracked`, alias, classification, tier | Node manual create and AI discovery/classification |
| `products` | Tenant products to compare | Node ingestion; future Product Management CRUD |
| `competitor_product_mappings` | Map own product to competitor SKU/URL/source | AI discovery/mapping; product curation integration still needs verification |
| `data_sources` | Collection source, policy status, schedule, last sync, collector | AI policy/discovery; Node data-source endpoints manage other connectors |
| `competitor_prices` | Time-stamped tenant-scoped price/availability observations | AI market-scraper collectors |
| `market_observations`, `market_events` | Wider collected facts and meaningful changes | AI market scraper / analysis |
| `competitor_score_snapshots` | Comparative scoring | AI scoring pipeline; consumed by Market Intelligence |
| `reviews`, `sentiment_results` | Competitor feedback and sentiment | AI collector and sentiment pipeline |
| `market_alert_rules`, `market_alert_events` | Alert rules and triggered market alerts | Rule/alert handling; integration requires separate verification |
| `audit_logs`, scraping cost/quota tables | Audit, usage, discovery/provider spend | Relevant Node/AI runtime, policy, and logging services |

**Critical identity difference:** Node's `POST /competitors` creates/reuses a **GLOBAL** competitor by *exact display name*. AI's product discovery uses tenant-private `visibility='PRIVATE'` entries, website identity keys, and tenant-scoped mappings. These two registration paths need a common deduplication/visibility policy; otherwise the same company can be tracked twice, or an unverified name can be exposed globally.

## 6. AI-team infrastructure and data flow

AI team source under `ai/src/market_scraper/` and `ai/src/ai/main.py`:

1. `tenant_discovery.py` discovers product/domain-level competitor candidates using the tenant's own products, product family grouping, country/geography context and quotas.
2. `discovery.py` registers tenant-scoped competitor identities, links, mappings and associated data sources. Its registration logic marks discovered identities PRIVATE and classifies candidates.
3. `policy.py` and source decisions distinguish `ALLOWED`, `RESTRICTED` and `BLOCKED`; discovery is **not permission to scrape**.
4. `discovery_worker.py` consumes Redis `market.discovery.requested`, discovers candidates and queues collection for **already-approved ALLOWED** sources. `src/ai/main.py` publishes this event when its **own** `/extraction/upload` path promotes newly created products.
5. `enqueue.py` validates source policy, collector support and a cost-to-margin gate before publishing `market.scrape.requested`.
6. `worker.py` / reviewed Scrapy/Playwright or official API collectors write eligible `competitor_prices`, `market_observations`, reviews and events.
7. AI market analysis/classification/scoring and market-intelligence repositories consume collected records and produce scores/snapshots or alerts as their actual pipelines permit.

**Known integration caveats:** The Node `POST /data-connection` uses a separate hosted Gradio extraction path. Its ability to trigger the AI FastAPI Redis discovery event is **not established** by the supplied code. The AI worker code existing on disk does not prove Redis, workers, approvals or collectors are operating in production. The AI team's separate `POST /competitors` manual-add endpoint is **not the same endpoint** as Node's `POST /competitors` and should not be mistaken for active integration.

**Source cadence caveat:** `data_sources.sync_frequency_minutes` exists, and the production subscription manifest stores monitoring cadence metadata. A complete, continuously running scraper scheduler honoring that plan-level cadence for every approved competitor source has **not been verified** end-to-end. Do not promise 6-hour observations purely from entitlement metadata.

## 7. Metrics and calculations

### Implemented now

**Tracked competitor count:**

`COUNT(tenant_competitors WHERE tenant_id = T AND is_tracked = TRUE)`.

This is the basis for `tracked_competitors` capacity. Treat it as a count of tenant-competitor **relationships**, not the number of valid scraped prices or linked products.

**Latest displayed competitor price:** The backend picks the newest available `competitor_prices` row for an active mapped product. It does **not** currently apply all source-policy, freshness, exactness and currency controls needed for safe business decisions.

**Profile price-change history:** For each mapping, sort available observations by `observed_at DESC`, compare each with the next older record, emit a change when numeric scraped prices differ, and combine all mapping events newest first. Compare only compatible currencies, units, product variants, and observation types.

### Recommended / acceptance formulas (not all implemented in Product UI)

- **Difference versus our price (%):** `(competitor comparable price - own comparable price) / own comparable price × 100`. Both prices must use the same currency and comparable unit. If own price is zero or data is not comparable, show unavailable—not infinity or a fabricated percentage.
- **Monitoring coverage (%):** `number of actively tracked product mappings with an eligible current observation / number of actively tracked mappings × 100`, with a defined freshness SLA; not currently exposed by the competitor-management API.
- **Observation freshness:** `now - observed_at`, with locale-aware reporting and plan/policy context. `addedAt` (when competitor was tracked) is not a scrape timestamp.
- **Monitoring success rate (%):** `successful eligible collection jobs / collection jobs due for the period × 100`; requires verified job/scheduler data, not inferred from the existence of rows.

A change in one competitor's product price does **not** imply a business-level price-index change unless a valid product comparison set and weighting scheme is defined.

## 8. Important gaps and production priorities

| Severity | Issue | Recommended next action |
| --- | --- | --- |
| Critical | Add Competitor UI only modifies local preview data | Use live API mutation, await persistence, show real error/success and invalidate competitor list |
| Critical | Node competitor endpoints do not enforce `competitor_management` | Apply authoritative tenant-scoped entitlement guard to read/create/profile and appropriate role permission checks |
| Critical | No `tracked_competitors` capacity check on create/reactivation | Enforce active count transactionally, including AI discovery/manual workflows and concurrent requests |
| High | Node GLOBAL name-matching conflicts with AI PRIVATE domain-based identity | Agree on canonical identity/visibility policy, URL normalization, tenant privacy, and safe duplicate merging |
| High | No untrack, reactivate management, edit alias or approved mapping management flow | Define management lifecycle and add only agreed functionality; preserve evidence/history |
| High | Price profile ignores source status, exactness, staleness and own currency | Apply eligibility rules, distinguish no observation from no mapping, and avoid false comparisons |
| High | Monitoring cadence is configured in plan metadata but execution unverified | Bind accepted plan cadence to actual approved sources and validate scheduled worker behavior |
| High | Node/Gradio product import not verified to publish competitor discovery event | Connect an explicit, safe discovery trigger or agreed recurring discovery job and test it |
| Medium | Fixed industry filter, inert UI actions and misleading added/updated labels | Generate filter options from data, wire actions, show last scan separate from date tracked |
| Medium | Profile metrics intentionally empty and no detailed verification states | Clearly label unsupported/unavailable outputs rather than zeros |
| Medium | AI scraping has provider/policy/cost constraints | Provide users with clear statuses and monitoring diagnostics |

## 9. Subscription and authorization scenarios

- **Starter:** Cannot create, view or manage the protected competitor-management domain unless a properly assigned custom plan explicitly includes it.
- **Growth:** Can manage at most 10 tracked competitors; nominal 24-hour monitoring configuration for eligible approved sources.
- **Enterprise:** Can manage at most 50 tracked competitors; nominal 6-hour monitoring configuration for eligible approved sources.
- **Custom plan:** Respect stored accepted `competitor_management` monitoring configuration and positive `tracked_competitors` cap; ensure changes to vendor rates/quotes do not silently change accepted plans.
- **Reactivate/untrack:** Re-enable counts against capacity. Exclude untracked competitors from the active list and protect their profile/mappings according to documented authorization policy.
- **Tenant privacy:** Tenant A cannot view or modify Tenant B links, mappings, prices, private discovered competitor identities or discovery/scraper requests.
- **Role permissions:** Only authorized tenant roles can change monitored competitors; read-only access should not imply permission to add, delete or change source approvals.

## 10. End-to-end and integration testing scenarios

Reuse the Playwright/Prisma test infrastructure already built for Dashboard Analytics, Market Intelligence, Demand Prediction and Product Management. Use a dedicated test database, not production Render, and separate deterministic tests from opt-in real AI worker/scraper tests.

1. **Live add**: submit frontend form; verify `POST /competitors`, real DB `global_competitors` and `tenant_competitors` rows, updated frontend list; reject preview-only fake success.
2. **Identity**: add same competitor twice, vary URL casing/hostname and display name, test tenant-private identity and concurrent additions; no duplicate or shared-visibility leakage.
3. **Tracked cap**: Growth 9→10 allowed, 10→11 rejected; Enterprise 49→50 allowed, 50→51 rejected; test AI discovery and simultaneous creation near cap.
4. **Entitlement**: Starter denied at backend; Growth and Enterprise allowed; disabled custom-plan case; route guards cannot bypass server checks.
5. **List**: accurate tenant-scoped tracked count, search, pagination, industry filter, translations and empty/error states.
6. **Details**: confirm active mappings, latest eligible price, own currency, product matching, timestamps, and no-prices/unapproved/stale states.
7. **History**: deterministic adjacent price observations yield correct timeline; currency or unit changes not reported as ordinary price moves.
8. **Lifecycle**: untrack/reactivate behavior, limit release and re-acquisition, and preservation of historical data after untracking.
9. **Policy**: RESTRICTED/BLOCKED sources never scraped; approved ALLOWED sources can enqueue; verify explicit policy evidence and cost gate.
10. **Discovery**: real product ingestion triggers discovery only through supported pipeline; classification/mapping and tenant isolation verified.
11. **Cadence**: approved source's effective `sync_frequency_minutes` matches Growth/Enterprise/custom plan; real scheduler logs actual due/skipped/completed jobs.
12. **Failure handling**: Redis down, worker down, provider credentials missing, rate limit exhausted, data stale, malformed price, missing mapping, retries/dead-letter reporting.
13. **Downstream**: Dashboard tracked competitors, Market Intelligence competitor metrics and price comparisons agree with database; no unauthorized feature leakage.
14. **Cross-tenant/RLS**: deliberate attempts to fetch another tenant's competitor, prices, sources, private identities or scraper jobs must fail.

Capture PASS/FAIL/BLOCKED/SKIP results, database/API/UI expected-vs-actual, screenshots, traces, provider/job evidence and clear responsible layers. Never claim a live scrape passed on the basis of deterministic fixtures.

## 11. Ordered implementation checklist

- [ ] Connect Add Competitor form to the real Node API; remove preview-only success.
- [ ] Enforce server-side `competitor_management` access and authorized role permissions on all competitor routes.
- [ ] Enforce `tracked_competitors` capacity atomically for manual creation, reactivation, and AI discovery.
- [ ] Unify Node manual competitor identity with AI private/domain-based discovery to prevent duplicates and unwanted global visibility.
- [ ] Implement a clear manage/untrack/reactivate lifecycle and safe history-preservation rules.
- [ ] Validate price observations for currency, exactness, policy and freshness before comparison.
- [ ] Make mapped-but-unscanned and blocked/restricted source states explicit in the UI.
- [ ] Verify that product ingestion initiates the intended AI competitor discovery process.
- [ ] Apply and verify Growth/Enterprise/custom-plan monitoring cadence on approved collector sources.
- [ ] Verify AI collection/score pipelines, source approvals, monitoring jobs, and failure diagnostics with real evidence.
- [ ] Fix industry filters, inert controls, translations and last-updated labels.
- [ ] Run deterministic + opt-in live AI E2E tests, quota/race tests, RLS tests and downstream metric verification.

## 12. Acceptance criteria and file map

**The feature is ready only when:** (a) users can add/manage competitors and see real persisted changes, (b) subscribed caps and roles cannot be bypassed by UI, API or AI writers, (c) discovered identities respect tenant boundaries, (d) approved collection operates according to a verified effective schedule, (e) recent comparable price evidence is surfaced accurately, (f) unavailable/blocked data is labeled rather than fabricated, and (g) automated tests prove these claims.

**Source files reviewed:**

- Backend: `src/modules/competitors/route/competitors.route.ts`, `controller/competitors.controller.ts`, `service/competitors.service.ts`, `repo/competitors.repo.ts`; `src/app.ts`; `src/modules/features/service/capacity.service.ts`; `src/config/production-plans.ts`; `prisma/schema.prisma`; custom-plan configuration/pricing services.
- Frontend: `src/features/market-intelligence/pages/CompetitorsPage.jsx`, `AddCompetitorPage.jsx`, `CompetitorProfileDetailPage.jsx`; `api/competitorsApi.js`; `hooks/useCompetitors.js`, `useAddCompetitor.js`, `useCompetitorProfile.js`; `components/CompetitorTable.jsx`; `config/competitorPreviewData.js`; `src/app/router/index.jsx`.
- AI: `src/market_scraper/README.md`, `tenant_discovery.py`, `discovery.py`, `discovery_worker.py`, `enqueue.py`, `worker.py`, `data_access.py`, `policy.py`; `src/ai/main.py`.

**Verification status:** Code-level audit complete for listed implementations. Live PostgreSQL/Render production data, enabled worker deployment, Stripe entitlements, provider credentials, actual scraper policy approvals, and end-to-end runtime results were **not** checked in this specification.
