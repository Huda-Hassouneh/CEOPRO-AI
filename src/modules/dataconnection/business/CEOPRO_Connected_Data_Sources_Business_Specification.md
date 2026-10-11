# CEOPRO-AI — Connected Data Sources

## 1. Business purpose and practical scenario

`connected_data_sources` limits **how many persistent data-source registrations a tenant may keep active at one time**. This helps CEOPRO control integration infrastructure usage and provides an understandable commercial limit. It is **not a count of data records, sync runs, uploaded files, successful authentications, or monthly additions**.

For example, a Growth retailer (five-source allowance) registers Shopify, an internal PostgreSQL system, and GA4. The tenant has three occupied slots, even if the PostgreSQL source has never successfully synchronized. An old inactive website source and manual Excel upload normally do not occupy slots.

The business needs to know **how many slots remain, what uses those slots, and how to free one without losing historical business data**. A registered source should never be misrepresented as fully connected or verified.

## 2. Relationship with Data Integration and the feature catalog

| Catalog feature          | Type                        | Meaning                                                       | Enforcement                                        |
| ------------------------ | --------------------------- | ------------------------------------------------------------- | -------------------------------------------------- |
| `data_integration`       | Boolean; lifetime           | Permission to register/manage persistent external connections | Route guard on `POST /data-connection/sources`     |
| `connected_data_sources` | Limit; `max`; lifetime      | Maximum simultaneously active source registrations            | `assertFeatureCapacity` in source creation service |
| `document_extraction`    | Usage limit; billing period | Processing manual uploaded business documents, in KB          | Upload guard and consumption accounting            |
| `document_storage_mb`    | Capacity limit              | Uploaded knowledge-document storage in MB                     | Separate storage controls; **not** connector slots |

A tenant needs `data_integration` enabled **and** a remaining `connected_data_sources` slot to create a persistent registration. A manual business-file upload takes the separate `document_extraction` path, not a connected-source slot.

## 3. Standard-plan allowances and quota calculation

The saved `src/config/production-plans.ts` defines:

| Plan        | `data_integration`        |         `connected_data_sources` maximum |
| ----------- | ------------------------- | ---------------------------------------: |
| Starter     | Enabled                   |                                        1 |
| Growth      | Enabled                   |                                        5 |
| Enterprise  | Enabled                   |                                       20 |
| Custom plan | Per accepted entitlements | Per plan limit or unlimited when allowed |

Catalog definition: `type = limit`, `aggregationType = max`, `resetCycle = lifetime`, `unit = sources`.

**Actual current code formula** (`src/modules/features/service/capacity.service.ts`):

```sql
SELECT COUNT(*)
FROM data_sources
WHERE tenant_id = :tenant_id
  AND is_active = TRUE;
```

```text
current_usage = count(all tenant-owned active data_sources)
remaining = max(0, plan_limit - current_usage)
creation_allowed = current_usage + 1 <= plan_limit
```

For an unlimited entitlement (`limit_value = NULL`), the capacity helper allows additional sources and reports no numeric remaining value. At the exact finite limit, `is_exceeded` becomes true in the current usage response; this indicates **at capacity**, not necessarily already over capacity.

**Caveat:** The general capacity resolver counts every active source, regardless of `source_type`. The dedicated repository function `countActivePersistentSources` counts only six persistent types (`shopify`, `postgresql`, `mysql`, `sqlserver`, `ga4`, `website`), but **the entitlement capacity calculation does not use that filtered function**. AI-created `OWN_SYSTEM_CONNECTOR` sources or any other active source also count under the current implementation. Align both contracts intentionally; do not blindly replace the count until the intended treatment of AI and other internal sources is decided.

## 4. Source lifecycle: active is not connected

`data_sources.is_active` presently means **registered/enabled for consideration**, not **credentials verified**, **successfully synchronized**, or **fresh**.

| Scenario                                   | `is_active` in current implementation | Counts toward quota?    | Verified sync?                           |
| ------------------------------------------ | ------------------------------------- | ----------------------- | ---------------------------------------- |
| New persistent source created in Node      | `true`                                | Yes                     | No; no connection test performed         |
| Active source with failed last job         | `true`                                | Yes                     | No                                       |
| Active source with completed eligible sync | `true`                                | Yes                     | Depends on actual job/promotion evidence |
| Disabled/inactive source                   | `false`                               | No                      | Historical data may remain               |
| One-time manual business file              | `false` when Node creates it          | No                      | Import job tracked separately            |
| AI self-service source                     | `true` in AI registration path        | Yes under general count | Depends on AI connector execution        |

**Recommended lifecycle:** Registered/Pending Setup → Verified → Syncing → Synced/Healthy, with Error, Paused/Inactive, and Disconnected branches. These are **business statuses to design**, not claims that matching database enum values or routes already exist. Keep `is_active` for capacity and eligibility, and derive truthful connection health from credentials verification, job state, last successful sync, and record promotion. Explicitly define whether pending/unverified registrations occupy slots (the current behavior says **yes**).

Disabling/untracking a source should release its slot only after a successful persisted transition to inactive. Historical `ingestion_jobs`, provenance, and downstream business records should remain according to retention rules. Reactivating must re-check quota transactionally. No complete disable/reactivate/disconnect Node routes were found in the reviewed snapshot.

## 5. Reviewed Node backend path and source types

**Route and service**:

1. `POST /data-connection/sources` (subject to actual router mount) runs authentication, tenant verification, and `requireEntitlement('data_integration')`.
2. `src/modules/dataconnection/service/dataconnection.service.ts` validates the payload, then invokes `assertFeatureCapacity({ featureCode: 'connected_data_sources', additionalAmount: 1 })`.
3. `src/modules/features/repo/usage.repo.ts` resolves current entitlement and usage; `src/modules/features/service/capacity.service.ts` counts active sources.
4. `src/modules/dataconnection/repo/dataconnection.repo.ts` writes the new `data_sources` row under transaction-scoped RLS context.
5. New rows default to `is_active: true`, `connection_credentials_vault: null`, and a desired `sync_frequency_minutes` (default 1,440). This is **metadata registration, not a successful connection**.

Accepted `sourceType` values: `shopify`, `postgresql`, `mysql`, `sqlserver`, `ga4`, `website`. The frontend's `analytics`, `website`, `businessSystem`, and `documents` are UI categories, not necessarily backend connector types.

**Read path:** `GET /data-connection` lists tenant-owned active source rows and derives a display status from the most recent `ingestion_jobs` entry. It also lists recent imports, including inactive one-time document sources. The current response assigns `dataStatus: 'verified'` unconditionally—**not evidence of connection verification**.

**Frontend:** `src/features/data-connections/pages/ConnectDataPage.jsx`, `api/dataConnectionsApi.js`, and `components/ConnectedSourceCard.jsx`. Website creation calls source registration, but provides `url` as a top-level field while the backend expects permitted data in `metadata` and does not persist `source_url` in this create path. Some other connect/reconnect/sync methods are preview/error fallbacks, while the page can display a success toast without checking `ok`.

## 6. Database data ownership

| Table / column                                      | Purpose                                                                                             | Main owner / source                                                       |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `data_sources`                                      | Persistent source identity, tenant, active flag, type, policy, schedule, config and vault reference | Node registration; AI connector/onboarding tooling also writes rows       |
| `data_sources.is_active`                            | Current active-capacity count and eligibility                                                       | Source lifecycle manager; must be authoritative                           |
| `data_sources.source_type` / `collector_key`        | Provider category and concrete AI collector routing                                                 | Node + AI need one agreed contract                                        |
| `data_sources.policy_status`                        | Collection eligibility/policy                                                                       | Authorized policy management / AI connector registration                  |
| `data_sources.connection_credentials_vault`         | Encrypted connector credential envelope                                                             | Secure credentials system; Node source registration currently leaves null |
| `data_sources.sync_frequency_minutes`               | Intended polling interval, **not actual sync evidence**                                             | Subscription/configuration and source manager                             |
| `data_sources.last_synced_at`                       | Synchronization watermark                                                                           | AI/job completion logic when successful                                   |
| `ingestion_jobs`                                    | Per-source extraction/sync activity, outcome and status                                             | Node ingestion worker and AI connector jobs                               |
| `import_staging_rows`                               | Extracted or fetched records pending validation/promotion                                           | Ingestion pipelines                                                       |
| `products`, `transactions`, `inventory`, `invoices` | Actual business data                                                                                | Correct canonical ingestion owners; not the source-limit feature itself   |
| Plans, feature mappings, subscriptions              | Plan allowance and tenant entitlement                                                               | Billing/subscription backend                                              |

The quota is **derived from current source rows**, not from cumulatively incrementing a `subscription_usage` counter whenever a new source is added. Lifetime reset means no monthly reset, but switching a source off can reduce current usage.

## 7. AI team connector infrastructure and ownership boundary

The reviewed AI repository includes:

- `src/market_scraper/connector_sync.py` — PostgreSQL client DB sync and due-date evaluation.
- `src/market_scraper/api_connector_sync.py` — generic API source sync.
- `src/market_scraper/connector_worker.py` — polling-based worker and tenant discovery. **Implemented in source**, not evidence that it is deployed or running.
- `src/market_scraper/data_access.py::register_self_service_data_source` — separate AI-side registration that assigns `source_type='OWN_SYSTEM_CONNECTOR'`, collector key `db_connector` or `api_connector`, allowed policy and optional encrypted credentials.

The AI worker only selects eligible sources when `is_active=TRUE`, `policy_status='ALLOWED'`, the relevant `collector_key` is present, and synchronization is due by `last_synced_at` and `sync_frequency_minutes`.

**Contract gap:** The Node `POST /data-connection/sources` writes an allowed `source_type` such as `postgresql`, but does not populate `collector_key`, approved source policy, or encrypted connection credentials. The AI worker cannot simply treat such a source as a ready-to-sync AI connector. Conversely, the AI-side registration path may create active sources without routing through the Node `connected_data_sources` quota. Neither path should be mistaken for an integrated customer lifecycle.

The AI connector implementations stage records through `process_records`; confirmation of final promotion into canonical business tables is still needed. Source count validation is independent from that ingestion correctness.

## 8. Gaps and release risks (priority ordered)

1. **High — Race-safe quota enforcement:** `assertFeatureCapacity` is run before a separate repository insert. Concurrent requests near the limit can both pass unless serialized by a tenant-scoped lock/transaction or equivalent safe mechanism. Also test RLS behavior of the capacity resolver's standalone Prisma query using the actual runtime DB role.
2. **High — Cross-writer quota consistency:** AI self-service registration and other source writers must participate in one authoritative quota check, or be distinctly excluded by a verified policy; prevent accidental bypass.
3. **High — Truthful status:** `is_active` and hard-coded `dataStatus: 'verified'` misrepresent setup and verification. Show registered, verified, synced and failed separately based on real evidence.
4. **High — Complete lifecycle:** Add authenticated source listing/details, disable/pause/reactivate/remove controls, and server-side quota checks when reactivating. Define retention and historical-data policy.
5. **High — Source-contract alignment:** Node source types, collector keys, credentials vault, policy approval, URL/config and AI scheduler requirements do not currently meet one end-to-end contract.
6. **High — Frontend false positives:** Fix connect, sync and reconnect handlers that report success for preview or failed results; persist website URL in the actual backend schema.
7. **Medium — Quota semantics:** Decide which active source kinds count, and ensure the usage dashboard, create handler, AI registration, source list and billing all use the same rule.
8. **Medium — Subscription transitions:** Define what happens when a plan downgrades below existing active usage; block new additions/reactivation while over limit and apply an explicit policy to existing sources.
9. **Medium — De-duplication:** Prevent multiple active registrations for the same provider/account/URL, including normalization and concurrent requests; do not globally merge tenant-private credentials.
10. **Medium — Operational visibility:** Report latest completed sync, failure reason, data age, job state, and actual record promotion instead of treating registration as a health check.

## 9. Subscription and policy scenarios

- **Starter:** 0→1 allowed; 1→2 denied.
- **Growth:** 4→5 allowed; 5→6 denied.
- **Enterprise:** 19→20 allowed; 20→21 denied.
- **Custom plans:** use the actual accepted per-tenant allowance, including explicit unlimited where supported.
- **At limit:** usage=limit; remaining=0; no new slot unless one is released or the limit increases.
- **Failed synchronization:** keep slot occupied while active; do not mark verified.
- **Inactive source:** consumes 0 in current count; retains history subject to policy.
- **Reactivate:** must re-check quota, authorization, and source state in one safe operation.
- **Plan downgrade:** determine and document treatment of preexisting excess registrations; no silent deletion.
- **Concurrent registration:** two requests for the last slot must not both succeed.
- **Cross-tenant:** all counts, source reads and operations must be tenant-isolated; authorize source IDs server-side.

## 10. E2E and integration testing checklist

Use the existing Dashboard Analytics, Market Intelligence, Demand Prediction, Product Management, Competitor Management and Data Integration Playwright/DB diagnostic infrastructure. Separate deterministic real-stack tests, contract tests and opt-in live connectors.

- [ ] Verify real plan catalog: 1 / 5 / 20 and custom-plan override/unlimited behavior.
- [ ] Verify both `data_integration` and `connected_data_sources` gates on source creation.
- [ ] Verify exact-at-limit and over-limit API responses and user-facing messages.
- [ ] Independently calculate usage from `data_sources` and compare API + subscription UI.
- [ ] Verify `is_active=true/false` transitions count correctly and history remains intact.
- [ ] Test all six Node persistent types and any AI-created active source types.
- [ ] Test whether manual file imports consume zero connection slots even across retries.
- [ ] Test failure of connection verification while the registration remains active.
- [ ] Verify zero-job sources are not labeled connected or verified.
- [ ] Test real sync-job status, last sync, freshness, and no fabricated 'verified' state.
- [ ] Verify frontend false-success scenarios for unsupported/preview methods.
- [ ] Test source disabling, reactivation, and quota release when lifecycle endpoints exist.
- [ ] Test concurrent requests for the final available slot.
- [ ] Test AI direct-registration quota behavior and consistency with Node registrations.
- [ ] Test duplicate provider/URL/account registration and idempotent retries.
- [ ] Test upgrade/downgrade and custom-plan quota changes.
- [ ] Test tenant isolation, source-ID tampering and PostgreSQL RLS with restricted roles.
- [ ] Verify credentials never appear in API responses, browser state or logs.
- [ ] Opt-in: verify approved AI connector discovery, synchronization and final promotion with real evidence.
- [ ] Verify English/Arabic strings, RTL layout, and accurate usage display.

Use evidence-backed PASS, FAIL, BLOCKED, SKIP or ERROR outcomes. Save actual API payloads (redacted), expected/actual database counts, browser traces and screenshots, and worker/job evidence when supported. Missing implementation is not a passing test.

## 11. Proposed safe implementation order

1. Agree on countable source types and pending/failed/paused source semantics with billing, backend, and AI teams.
2. Centralize source-capacity resolution and make **all** registration/reactivation writers enforce it atomically.
3. Complete source lifecycle and truthful verification/status model.
4. Align Node/AI source registration and encrypted credentials contract; use approved policy and collector keys.
5. Correct frontend success/error display and source configuration payloads.
6. Add deterministic, security and concurrency regression tests; then opt-in real connector runs.

Avoid changing the public entitlement codes or converting `connected_data_sources` into cumulative usage. Preserve compatible plan and custom-plan contracts.

## 12. Completion criteria and accountable evidence

The feature is complete when every authorized tenant can see a **correct, current and tenant-isolated count of occupied source slots**, register only when permitted, disable/re-enable sources according to a documented policy, and never receive a false connection-success message. Direct API calls, AI-side writers, concurrent requests and plan changes cannot bypass quota rules. Source health is based on verified connectivity and completed synchronization, not merely registration. The automated suite demonstrates each scenario in a dedicated test environment.

### Reviewed code paths

- Backend `src/config/production-plans.ts` — standard allowances.
- Backend `src/modules/features/catalog.ts` — feature type, aggregation and reset cycle.
- Backend `src/modules/features/service/capacity.service.ts` and `src/modules/features/repo/usage.repo.ts` — authoritative usage and capacity checks.
- Backend `src/modules/dataconnection/{route,service,repo}/...` — create and overview implementation.
- Backend `prisma/schema.prisma` — `data_sources`, jobs and subscription models.
- Frontend `src/features/data-connections/{api,hooks,pages,components}/...` — registration and source UI.
- AI `src/market_scraper/{connector_sync.py,api_connector_sync.py,connector_worker.py,data_access.py}` — connector registration, scheduling and sync.

_All findings are based on reviewed repository snapshots, not a live production audit._
