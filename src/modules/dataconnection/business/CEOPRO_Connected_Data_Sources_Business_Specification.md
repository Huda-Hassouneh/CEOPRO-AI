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

**Current capacity formula** (`src/constants/data-source-types.ts`, `src/modules/features/service/capacity.service.ts`, and `src/modules/features/repo/usage.repo.ts`):

```sql
SELECT COUNT(*)
FROM data_sources
WHERE tenant_id = :tenant_id
  AND is_active = TRUE
  AND source_type IN (
    'shopify', 'postgresql', 'mysql', 'sqlserver', 'ga4', 'website',
    'OWN_SYSTEM_CONNECTOR'
  );
```

```text
current_usage = count(active tenant-owned persistent connector source types)
remaining = max(0, plan_limit - current_usage)
creation_allowed = current_usage + 1 <= plan_limit
```

For an unlimited entitlement (`limit_value = NULL`), the capacity helper allows additional sources and reports no numeric remaining value. At the exact finite limit, `is_exceeded` becomes true in the current usage response; this indicates **at capacity**, not necessarily already over capacity.

The Node capacity resolver, transactional registration path, source list, and database trigger use the same allow-list. AI `OWN_SYSTEM_CONNECTOR` sources count; manual upload and unrelated source types such as `documents`, `<EXT>_UPLOAD`, and `WEB_SCRAPE` do not. `NULL` remains the explicit unlimited custom-plan value.

## 4. Source lifecycle: active is not connected

`data_sources.is_active` presently means **registered/enabled for consideration**, not **credentials verified**, **successfully synchronized**, or **fresh**.

| Scenario                                   | `is_active` in current implementation | Counts toward quota?    | Verified sync?                           |
| ------------------------------------------ | ------------------------------------- | ----------------------- | ---------------------------------------- |
| New persistent source created in Node      | `true`                                | Yes                     | No; no connection test performed         |
| Active source with failed last job         | `true`                                | Yes                     | No                                       |
| Active source with completed eligible sync | `true`                                | Yes                     | Depends on actual job/promotion evidence |
| Disabled/inactive source                   | `false`                               | No                      | Historical data may remain               |
| One-time manual business file              | `false` when Node creates it          | No                      | Import job tracked separately            |
| AI self-service source                     | `true` in AI registration path        | Yes under shared allow-list | Depends on AI connector execution     |

The Connect Data overview derives `configured`, `processing`, `synced`, `needsAttention`, `paused`, and `disconnected` states. A configured source is not provider-verified. `synced` requires a completed job with promoted staging rows; registration alone never establishes a successful connection. Pending/unverified active registrations occupy slots.

Authenticated pause and reactivation routes persist `is_active`; reactivation re-checks the current boolean and numeric entitlements under the tenant capacity lock. Disconnect also sets the source inactive and clears `connection_credentials_vault`, while retaining the source row, jobs, staging, and imported business data. Existing sources are not silently disabled on plan downgrade; new registration and reactivation are blocked until the tenant is eligible and has capacity. Pause and disconnect remain available so the tenant can reduce usage.

## 5. Reviewed Node backend path and source types

**Route and service**:

1. `POST /data-connection/sources` (subject to actual router mount) runs authentication, tenant verification, and `requireEntitlement('data_integration')`.
2. `src/modules/dataconnection/service/dataconnection.service.ts` validates the payload and calls the repository.
3. `src/modules/dataconnection/repo/dataconnection.repo.ts` takes a tenant-scoped PostgreSQL advisory transaction lock, checks identity and capacity, then writes under transaction-scoped RLS context.
4. The database trigger in `prisma/migrations/20261012000000_enforce_connected_source_capacity/migration.sql` repeats the boolean/limit/duplicate checks for direct writers using the same lock. The migration has not yet been exercised against PostgreSQL in this workspace.
5. New rows default to `is_active: true`, `connection_credentials_vault: null`, and a desired `sync_frequency_minutes` (default 1,440). This is **metadata registration, not a successful connection**.

Accepted `sourceType` values: `shopify`, `postgresql`, `mysql`, `sqlserver`, `ga4`, `website`. The frontend's `analytics`, `website`, `businessSystem`, and `documents` are UI categories, not necessarily backend connector types.

**Read path:** `GET /data-connection` lists tenant-owned persistent sources, including paused/disconnected rows, derives state from latest jobs and promotion records, and returns current/remaining capacity. It also lists recent imports, including inactive one-time document sources. Read and cleanup operations remain available after `data_integration` is removed so downgraded tenants can review and release source slots.

**Frontend:** `src/features/data-connections/pages/ConnectDataPage.jsx`, `api/dataConnectionsApi.js`, and `components/ConnectedSourceCard.jsx`. Website creation validates and persists a normalized `sourceUrl`. Persistent registrations are gated by both entitlements; manual file upload uses document extraction and sits outside the connector-slot gate. The page shows used/remaining slots, plan-overage state, and confirmed pause/reactivate/disconnect outcomes.

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

**Contract gap:** The Node `POST /data-connection/sources` writes an allowed `source_type` such as `postgresql`, but does not populate `collector_key`, approved source policy, or encrypted connection credentials. The AI worker cannot simply treat such a source as a ready-to-sync AI connector. A new database trigger now protects the AI direct-registration path against missing `data_integration`, source-capacity overflow, and active duplicate identities without changing AI code. The AI endpoint's error translation and live database behavior still require the opt-in integration test.

The AI connector implementations stage records through `process_records`; confirmation of final promotion into canonical business tables is still needed. Source count validation is independent from that ingestion correctness.

## 8. Gaps and release risks (priority ordered)

1. **Implemented; database evidence pending — Race-safe quota enforcement:** Node registration/reactivation and the shared database trigger use a tenant advisory lock. Run the disposable-database concurrency/RLS tests before release.
2. **Implemented; AI response handling pending — Cross-writer quota consistency:** The trigger guards AI direct source writes. The AI endpoint is not changed and may map database rejections to a generic server error.
3. **Implemented for local status evidence — Truthful status:** Registration is configured, not verified; successful sync requires job/promotion evidence. Provider-specific connection verification remains Data Integration work.
4. **Implemented in Node — Source lifecycle:** Authenticated source list, pause, capacity-checked reactivation, and credential-clearing disconnect are available; real API/database and retention E2E evidence remains pending.
5. **Open — Source-contract alignment:** Node source types still lack the AI worker collector key, approved policy, credential-vault setup, and provider-specific configuration needed for an end-to-end AI sync.
6. **Implemented in current UI — Frontend actions:** Success is shown only after successful API results; unsupported sync/reconnect actions are not exposed; website URLs persist and slot usage is visible.
7. **Implemented in code; live verification pending — Quota semantics:** Node usage, AI connector writes, and source listing use the agreed seven-type allow-list.
8. **Implemented policy — Subscription transitions:** Existing sources remain intact after downgrade; additions/reactivation are blocked and cleanup remains available. Exercise custom-plan and downgrade fixtures before release.
9. **Implemented in Node and trigger — Active duplicate prevention:** Normalized website identity and connector endpoint/name identity are checked under the tenant lock.
10. **Partially implemented — Operational visibility:** Overview reports latest job state, last successful promotion time, and promoted-row count; live connector freshness and provider failure detail remain dependent on Feature 8 integration.

## 9. Subscription and policy scenarios

- **Starter:** 0→1 allowed; 1→2 denied.
- **Growth:** 4→5 allowed; 5→6 denied.
- **Enterprise:** 19→20 allowed; 20→21 denied.
- **Custom plans:** use the actual accepted per-tenant allowance, including explicit unlimited where supported.
- **At limit:** usage=limit; remaining=0; no new slot unless one is released or the limit increases.
- **Failed synchronization:** keep slot occupied while active; do not mark verified.
- **Inactive source:** consumes 0 in current count; retains history subject to policy.
- **Reactivate:** must re-check quota, authorization, and source state in one safe operation.
- **Plan downgrade:** keep existing registrations and history; report excess usage, block additions/reactivation, and allow pause/disconnect to release slots.
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
