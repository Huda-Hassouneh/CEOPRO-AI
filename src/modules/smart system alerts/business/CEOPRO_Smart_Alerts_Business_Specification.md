# CEOPRO-AI — Feature 14: Smart Alerts (`system_alerts`)

## 1. Business purpose, customer value and limits

Smart Alerts should surface meaningful tenant-specific business changes without requiring owners to watch dashboards constantly. An alert should identify **what changed, where, magnitude, observation time, reliable source, why it matters, and next action**. Initial high-value examples are competitor price changes and inventory threshold breaches; forecast, sentiment, and revenue anomalies are sensible future candidates but are **not implemented as Smart Alert producers** in the inspected Node code. Alert messages must not claim causality or certainty without evidence.

An _alert event_ records a triggered condition. A _notification_ delivers an alert to one or more eligible users. Read/acknowledge, resolve and archive are separate semantics and should not be conflated.

### Example

A competitor price moves from 100 to 85 JOD. The signed percentage change is `(85−100)/100 × 100 = −15%`. A rule `operator=LTE, threshold=−10` matches; `GTE +10` does not. The system should show the exact competitor, mapped product, old/new price and currency, observation time, source, threshold, recipient and link to evidence.

## 2. Subscription / entitlement availability

`src/modules/features/catalog.ts` (and mirrored `src/modules/features/types/feature.catalog.ts`) defines `system_alerts` as `FeatureType.boolean`, Arabic display name `التنبيهات الذكية`, aggregation `sum`, reset `lifetime`. **Lifetime is not an alert-volume limit.**

`src/config/production-plans.ts` contains **no `system_alerts` in Starter ($55 USD/month), Growth ($140) or Enterprise ($350)**. `tests/billing/production-plans/PRODUCTION_PLAN_BOOTSTRAP.md` explicitly lists Smart Alerts as excluded from initial launch. A tenant may potentially receive this boolean feature via an approved custom plan or entitlement assignment, subject to current checkout and entitlement semantics; **that alone does not wire any Smart Alert capability.**

**Commercial design decision required:** specify whether Smart Alerts are a paid add-on, a Growth/Enterprise option, or custom-plan-only. Do not block billing, security or custom-plan-offer inbox notifications for customers who do not have `system_alerts`; they are separate transactional notifications.

## 3. Separate systems and real implementation status

| Component                     | Database/API                                                                           | Verified in code                                                                        | Missing or unconnected                                                                                                                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| General business alerts       | `system_alerts` Prisma model                                                           | Tenant ID, `alert_type`, `severity`, message, resolution fields                         | No identified Node writer, evaluator, authenticated CRUD/resolve API, or frontend binding                                                                                                                  |
| Competitor rule configuration | `market_alert_rules`                                                                   | Competitor, metric, comparator, numeric threshold, active flag                          | No identified working Node rule CRUD or customer editing page; frontend form is placeholder                                                                                                                |
| Competitor trigger events     | `market_alert_events`                                                                  | AI scraper creates event when signed price delta crosses active rule                    | No verified propagation to `system_alerts` or `tenant_notification_outbox`, no tested deduplication                                                                                                        |
| Market history                | `market_events`                                                                        | AI scraper writes `PRICE_CHANGED`, `AVAILABILITY_CHANGED`, `PRODUCT_DISCOVERED` records | Events not automatically displayed as Smart Alerts                                                                                                                                                         |
| Customer inbox                | `tenant_notification_outbox` → `tenant_notifications` → `tenant_notification_receipts` | Node worker, outbox, read/archive APIs, React bell                                      | Only `CUSTOM_PLAN_OFFER_READY` event type supported in tenant notification definition/producer; no market-alert producer                                                                                   |
| Platform inbox                | `platform_*` notifications                                                             | Separate Platform Admin operational flow                                                | Explicitly not Smart Alerts; do not reuse blindly                                                                                                                                                          |
| Dashboard alert UI            | `AlertCard`, `AlertFeed`, `ActionableAlertCard`, `useRealtimeAlerts`                   | Placeholder components exist                                                            | `AlertCard` hardcodes translated headline; action has empty handler, `AlertFeed` static, `useRealtimeAlerts` calls nonexistent `dashboardApi.getAlerts`; DashboardHomePage does not mount these components |
| Preferences UI                | `NotificationSettings`, `preferencesApi`                                               | Page/shape present                                                                      | `getNotificationPreferences` returns `{preferences:[], channels:[], available:false}` and update is unsupported                                                                                            |
| Actual recipient UX           | `Topbar.jsx`, `useTenantNotifications`                                                 | Bell polls Node `/notifications` every 30 sec                                           | Targets currently cover custom-plan quotes only; no product/competitor alert action route                                                                                                                  |

**Conclusion:** There are two usable foundations—AI-generated market threshold events and durable Node tenant notification delivery—but no complete, entitlement-aware customer Smart Alerts product.

## 4. Data ownership and authoritative sources

| Data source                                                                          | Fields and meaning                                                 | Owning subsystem                          | Smart Alerts responsibility                                                  |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------- |
| `products`                                                                           | Tenant product, name, price and status                             | Product Management / ingestion            | Reference target; filter inactive/deleted products                           |
| `tenant_competitors`, `global_competitors`                                           | Tenant-tracked competitor identity and alias                       | Competitor Management                     | Ensure monitored competitor is active/authorized                             |
| `competitor_product_mappings`                                                        | Tenant product ↔ competitor mapping                                | Market collection / competitor management | Resolve product context; validate mapping scope                              |
| `competitor_prices`                                                                  | Successive observed price/currency/time/status                     | AI market scraper                         | Source of price history and deltas; exclude unsafe/incomparable observations |
| `market_events`                                                                      | Market observation/event identity and `occurred_at`                | AI market scraper                         | Source event and evidence                                                    |
| `market_alert_rules`                                                                 | Tenant rule, metric, comparator, threshold                         | Customer rules service (missing)          | Create/update/disable rules securely                                         |
| `market_alert_events`                                                                | Trigger result, observed numeric value, message, `acknowledged_at` | AI market scraper                         | Canonical triggered market event                                             |
| `system_alerts`                                                                      | Generic alert, severity, resolution state                          | Proposed Node Smart Alerts domain         | Decide if it is canonical or a projection, avoid dual truth                  |
| `inventory`                                                                          | Quantity and reorder threshold                                     | Inventory management                      | Future inventory threshold trigger, not current production Smart Alert       |
| `demand_forecasts`, `invoices`, `invoice_items`, `transactions`, `sentiment_results` | Forecasts, sales and sentiment                                     | Other features                            | Future rule producers after contracts and freshness are defined              |
| `tenant_notification_outbox`                                                         | Durable delivery intents and dedupe keys                           | Node notification producer                | Bridge business events to inbox without losing events                        |
| `tenant_notifications` / `tenant_notification_receipts`                              | User-visible notifications and read/archive state                  | Tenant notification worker                | Deliver only to authorized tenant recipients                                 |
| `subscription` / plan features                                                       | Boolean feature authorization                                      | Billing / Features                        | Gate optional Smart Alert creation, rule editing, business feed              |

### State ownership

`market_alert_events.acknowledged_at` means a business alert was acknowledged. `system_alerts.is_resolved`/`resolved_at` means a general alert was resolved. `tenant_notification_receipts.readAt`/archived state means a _particular recipient_ read/archived delivery. These are **three different timelines**; do not map them to one boolean.

## 5. AI trigger calculation (actual code)

`src/market_scraper/market_repository.py`:

1. A validated observation is promoted via `save_market_record` and the market-event path.
2. `_previous_observation` selects the latest previously stored `competitor_prices` row for the **same tenant and mapping**.
3. When current price differs from previous price, `_derive_events` creates a `market_events` row with `event_type='PRICE_CHANGED'` and old/new data.
4. `_trigger_price_alerts` skips a baseline old price of zero, then computes:

   `signed_percent_change = (new_price - old_price) / old_price * 100`

5. It selects `market_alert_rules` for the same tenant/competitor, `metric='PRICE_CHANGE_PERCENT'`, `is_active=TRUE`.
6. Each rule is evaluated by `src/market_scraper/scoring.py::alert_matches`, supporting operators `GT`, `GTE`, `LT`, `LTE` and strict/inclusive bounds as named.
7. Matching rules create `market_alert_events(tenant_id, alert_rule_id, market_event_id, observed_value, message)`.

Threshold example: old=100, new=85; delta `−15%`. `LTE -10` matches; `LT -15` does not (strict boundary), `LTE -15` matches. Old=0 yields **no percent alert**, not division by zero.

### Edge cases and defects to investigate

- **Currency:** Previous price query doesn't select currency, so a switch from USD to JOD can produce an invalid percentage; require same-currency or authorized FX normalization.
- **Ordering/freshness:** `_previous_observation` sorts by observed timestamp; late-arriving historical observations can cause misleading change detection; specify event-time ordering and stale detection.
- **Duplicate/retry:** No unique (rule,event) constraint was apparent in the Prisma `market_alert_events` model; retry/replayed promotions need idempotent alert production.
- **Rule semantics:** Signed deltas are essential. A -10% drop is not +10% and absolute-value thresholds must never silently replace the signed contract.
- **Credibility:** Filter unsupported, blocked, quarantined, imprecise or stale observations in accordance with market collection policy. Validate existing pipeline decisions before production claims.
- **Dedup/suppression:** Avoid repeated notification flooding for minor repeated changes; define cooldown, incident grouping, escalation and re-arm policy.
- **No baseline:** First sighting produces discovery event, not a price-change percentage alert.
- **No inventory or sales Smart Alerts found:** The AI `src/ai/dashboard/inventory.py` calculates low-stock counts, but does not emit notifications. It does not prove a Smart Alert producer exists.

## 6. Node customer-notification delivery foundation

`src/modules/tenant-notifications/TENANT_NOTIFICATIONS_POLICY.md` documents:

`business action → tenant_notification_outbox → tenant notification worker → tenant_notifications → tenant_notification_receipts → /notifications → customer bell`.

The first and currently supported event is **`CUSTOM_PLAN_OFFER_READY`**, emitted transactionally when a quote becomes sent. `tenant-notification.definition.ts` handles this case only and throws for unrecognized event types. `tenant-notification.producer.ts` supplies a dedupe key for that one event. `tenant-notification.dispatcher.ts` resolves permission-eligible members and creates final notifications/receipts transactionally, while `src/workers/tenant-notification.worker.ts` polls every **10 seconds**, batches up to 20 and retries up to 5 times with backoff. `src/features/notifications/hooks/useTenantNotifications.js` polls **every 30 seconds** and the `Topbar.jsx` bell links only known custom-plan quote resources.

This foundation does **not** currently subscribe to `market_alert_events`. A market alert is not delivered just because an AI row was inserted. End-to-end business alerts require a durable producer/bridge and new notification event definitions, recipient policy, deeplink, and permission model; preserve existing transactional notifications.

**Real-time wording:** Scheduled scraping plus 10-second worker polling plus 30-second browser polling is near-real-time _after detection_, not instantaneous observation of upstream changes. Do not promise true real-time delivery or mobile push without corresponding infrastructure.

## 7. Recommended architecture and domain ownership

1. **Market scraper owns safe observations and trigger evaluation** (or calls a dedicated rule evaluator once available). Emit a stable `market_alert_event_id`.
2. **CEOPRO Node Smart Alerts owns business authorization, rule CRUD, alert APIs, acknowledgement, resolution, evidence retrieval, and source-specific target routes**, all with verified tenant and RLS context. Avoid duplicating alert calculations in the frontend.
3. **Tenant notification producer owns reliable fanout**: atomically link a business event to a deduplicated tenant notification outbox entry; if cross-service/DB transaction is impossible, use idempotent polling/CDC or a transactional handoff with reconciliation.
4. **Notification worker owns recipient selection and delivery**. Do not send tenant business alerts to Platform Admin inbox unless operational escalation is separately required.
5. **Frontend owns display, filtering, confirmation UX, acknowledged/resolved state, and Arabic/English presentation**; alerts link to real product/competitor/evidence pages.
6. **Features/Billing owns entitlement**. Evaluate `system_alerts` at customer-facing routes and alert-rule creation; define whether already-created business events are retained/readable after downgrade and whether notification delivery stops upon feature removal. Never gate legally or operationally essential account notices on this add-on.
7. **Operational observability** owns queue lag, failed/poison events, age, duplicate rate, and worker health.

### Suggested minimal API contracts (proposed, not implemented)

- `GET /smart-alerts` — tenant-scoped paged business alert feed.
- `GET /smart-alerts/unread-count` — business unread count (distinct from tenant inbox receipts).
- `POST /smart-alerts/rules`, `PATCH /smart-alerts/rules/:id`, `GET /smart-alerts/rules` — rule CRUD.
- `POST /smart-alerts/:id/acknowledge` and `POST /smart-alerts/:id/resolve` — independent transitions, permission controlled.
- Producer bridge: `MARKET_PRICE_THRESHOLD_TRIGGERED` notification with stable source ID, source refs, severity, localized title key/body key, and target product/competitor URL.

These are design proposals; first agree whether market and generic alert stores remain separate, and whether acknowledgement is per-user or tenant-wide.

## 8. Subscription, recipient policy and preferences

- **Standard plans:** `system_alerts` excluded. Do not accidentally expose premium feature through the public API just because a tenant has general `/notifications` access.
- **Custom plans:** test enabled, disabled, revoked, suspended and expired cases. Boolean means access/no access, not 1 alert per month.
- **Recipient policy:** owner plus selected tenant roles/permissions; use actual membership status and prefer explicit `alerts.read/manage` permissions (proposed) rather than infer every member should receive alert details.
- **Preferences:** `src/features/settings/api/preferencesApi.js` returns `available:false`; email/SMS/push routing and schedules are not verified. Browser inbox exists; preference editing is not a working source of truth.
- **Privacy:** alert message may include confidential prices or product IDs; every recipient and deeplink must reauthorize within tenant.
- **Downgrade:** decide whether historical alerts remain visible after removing entitlement; avoid deleting records merely because entitlement changed.

## 9. Business metrics and calculations

A Smart Alerts dashboard needs defensible aggregates, not just a message list. Define:

- **Triggered count** = `COUNT(*)` over canonical tenant-specific, non-duplicate source alert records filtered to `[start,end)` by event occurrence time, not necessarily created time.
- **Unacknowledged market count** = `COUNT(market_alert_events WHERE tenant_id=? AND acknowledged_at IS NULL)`, provided membership and cross-table IDs are validated.
- **Unresolved general alerts** = `COUNT(system_alerts WHERE tenant_id=? AND is_resolved=FALSE)`.
- **Unread recipient notifications** = `COUNT(tenant_notification_receipts WHERE recipient_user_id=? AND readAt IS NULL ...)`, following actual schema and archived semantics.
- **Delivery rate** = distinct successful intended deliveries / distinct valid delivery intents; define recipient-vs-event denominator before implementation.
- **Delivery latency** = displayed-at/delivered-at minus originating `market_events.occurred_at`; separate scraper observation delay from worker dispatch delay.
- **Duplicate rate** = repeated source/incident keys per tenant; avoid using only identical messages for identity.

**Do not sum these counts together.** An event, an incident, a generic alert and a user receipt may represent the same underlying business condition multiple times.

## 10. UI and localization acceptance

`AlertFeed.jsx` currently renders only `Alerts`. `ActionableAlertCard.jsx` only renders `Analyze Impact`. `AlertCard.jsx` shows localized static text, empty `View Product` handler and a dismiss callback unrelated to a persisted alert. `useRealtimeAlerts.js` calls `dashboardApi.getAlerts`, but inspected `dashboardApi.js` only contains `getAggregate`. `DashboardHomePage.jsx` does not render the alerts widgets. `CompetitorAlertThresholdForm.jsx` is a static placeholder. `NotificationSettings.jsx` shows unavailable settings and the preferences API returns preview data. A functional customer UI must display actual event-level data, not treat these static assets as evidence of production readiness.

Build business alerts as a filtered feed with severity, timestamp/time zone, affected product/competitor, source, status, dismiss/ack/resolve distinction, stable deeplink and pagination. Display Arabic/English via translation keys or authorized localized rendering, not by assuming AI-produced English messages are translated. Update immediately following acknowledgement and use proper RTL alignment; do not claim instant provider detection because UI polls.

## 11. High-priority implementation gaps and recommended sequence

| Priority | Gap                                                                 | Required direction                                                                                                          |
| -------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Critical | Not offered on standard plans; entitlement absent at API            | Decide commercial access and gate all business-specific routes while leaving transactional notifications working            |
| Critical | No market-event-to-inbox delivery                                   | Durable idempotent bridge from `market_alert_events` to tenant outbox, new event definition, recipient policy and deep link |
| Critical | `system_alerts` generic table has no identified producer or API     | Define canonical event/incident store; implement tenant-scoped list, acknowledge, resolve with history                      |
| High     | No working alert-rule CRUD                                          | Validated tenant+competitor scoped rule creation/edit/disable; numeric thresholds and operators                             |
| High     | UI alerts are placeholders / `getAlerts` missing                    | Real API-backed feed and meaningful actionable navigation                                                                   |
| High     | Signed comparison and currency/freshness                            | Unit, currency, old-vs-new chronology and source safety validation                                                          |
| High     | Duplicates/race conditions                                          | Stable event dedupe keys, unique constraints, retries and suppressed repeat alerts                                          |
| High     | Tenant boundaries and roles                                         | Cross-tenant, cross-recipient RLS and scoped notification payloads                                                          |
| Medium   | No configurable preferences/channels                                | Decide available delivery channels, quiet hours and preference persistence                                                  |
| Medium   | Missing notification lifecycle coherence                            | Define acknowledge/resolve/read/archive; synchronized user-visible updates                                                  |
| Medium   | Missing business alert observability                                | Detection-to-display latency, retry/fail states, delivery health                                                            |
| Medium   | No implemented inventory/forecast/sentiment/revenue alert producers | Add only after source validity, entitlement, freshness, suppression and E2E tests are agreed                                |

## 12. E2E and integration acceptance plan

Tests must reuse existing Node `tests/notifications/` worker/producer contracts, Python `src/market_scraper/tests/test_scoring.py`, Playwright/React tests and isolated PostgreSQL test DB. Don't claim live provider data, delivered notifications, or functioning endpoints based on fixtures or mocks.

1. **Catalog**: boolean/lifetime definition; standard plans exclude Smart Alerts; custom plan enabled/disabled behavior.
2. **Entitlement**: authenticated tenant with feature disabled cannot configure/read paid Smart Alerts; existing billing offer notifications remain accessible.
3. **Rule CRUD**: create/update/disable on owned active tracked competitor; cross-tenant competitor rejected.
4. **Rule operators**: GT/GTE/LT/LTE boundary equality/strictness, signed negative thresholds and invalid operator.
5. **Price formula**: old 100 → new 85 = −15%; old 100 → new 115 = +15%; no divide-by-zero at old zero.
6. **Currency**: USD→JOD price change must not trigger false percentage without valid conversion.
7. **Event chronology**: out-of-order timestamps, stale observation and repeated scraper records.
8. **Evidence**: verify mapping, old/new price, currency, observed time, safety status, URL and originating event ID.
9. **Source quarantine**: blocked/unsafe/no-price observations must not produce customer alerts contrary to policy.
10. **Duplicate handling**: replay same event, two simultaneous workers and identical rule/source event produce one canonical alert/intent.
11. **Debounce/re-arm**: repeated price oscillations follow agreed cooldown and incident policies.
12. **Trigger persistence**: validate `market_alert_events`, `market_events`, `market_alert_rules` relationships and tenant attribution.
13. **Outbox bridge**: real detected alert enters durable outbox exactly once; failures retry safely.
14. **Worker dispatch**: eligible member receives correct notification; unauthorized/non-active user excluded.
15. **Recipient permissions**: owner, authorized admin, ordinary member and removed user, tested separately.
16. **Unread counts**: compare direct alert counts versus recipient unread counts without conflation.
17. **Read/ack/resolve/archive**: per-recipient read does not tenant-resolve an incident, and resolving does not silently mark all receipts read.
18. **Failure recovery**: worker stops after claim, restarts, retries and eventually marks error without duplicate delivery.
19. **UI**: real feed and bell display persisted events and genuine routing to product/competitor context.
20. **Threshold form**: frontend validation, persistence, refresh and permission failures.
21. **Localization**: Arabic/English content and labels, RTL, timestamps and safe message rendering.
22. **Settings**: missing delivery channels truthfully shown as unavailable; future preferences tested only when implemented.
23. **Tenant isolation**: direct API, database RLS, worker fanout, receipt updates, notifications and deep links for tenant A/B.
24. **Subscription transitions**: grants, revocations, downgrades, historical data policy and ongoing detector behavior.
25. **Observability**: distinguish `occurred_at`, detected, queued, dispatched, read and resolved timestamps; verify delivery lag.
26. **Downstream signals**: inventory/revenue/forecast/sentiment alerts marked BLOCKED until real producers and contracts exist.
27. **Regression**: platform-admin billing notifications and `CUSTOM_PLAN_OFFER_READY` continue working unchanged.
28. **No false passes**: distinguish unit/contract, deterministic integration, frontend E2E and opt-in live scrape→AI→Node worker→browser.

### Test outcomes and diagnostics

Use `PASS/FAIL/SKIP/BLOCKED/ERROR`, with tenant, event ID, rule ID, threshold/operator, old/new value and currency, AI event ID, notification outbox key, recipient ID, severity, actual timestamps, HTTP/API status, database verification, screenshot/trace and evidence-backed responsible component. Use _BLOCKED_ for missing app functionality, never _PASS_. PowerShell commands must match existing project scripts and a verified non-production database, without RLS bypass, customer data, real credentials or uncontrolled scraping costs.

## 13. Implementation ownership and phase gates

**Phase A — Define product contract:** entitled plans, supported alert categories, source credibility, event vs incident semantics, recipient roles, re-arm/cooldown, retention and message localization. **Phase B — Connect existing producers:** validate AI alert math and idempotency, build authorized Node rule CRUD and durable outbox bridge. **Phase C — Customer UX:** API-backed alerts list, detail, actions and preferences; unify read/ack/resolve semantics. **Phase D — Safety/reliability:** RLS, retries, dedupe, queue metrics and downgrade logic. **Phase E — E2E:** deterministic DB/worker/UI tests, opt-in live monitored competitor with controlled price observations, full reporting.

## 14. Source file index

**Node backend**

- `src/modules/features/catalog.ts` and `src/modules/features/types/feature.catalog.ts` — canonical Smart Alerts definition.
- `src/config/production-plans.ts` and `tests/billing/production-plans/PRODUCTION_PLAN_BOOTSTRAP.md` — launch exclusion.
- `prisma/schema.prisma` — `system_alerts`, `market_alert_rules`, `market_alert_events`, `market_events`, tenant notification tables.
- `src/modules/tenant-notifications/TENANT_NOTIFICATIONS_POLICY.md` — explicitly separate customer notifications.
- `src/modules/tenant-notifications/tenant-notification.definition.ts` / `tenant-notification.producer.ts` / `tenant-notification.dispatcher.ts` — custom-plan-only notification definitions and routing.
- `src/modules/tenant-notifications/route/tenant-notification.route.ts` / `service/tenant-notification.service.ts` — read/archive customer inbox.
- `src/workers/tenant-notification.worker.ts` — polling, bounded delivery and retries.
- `src/modules/platform-notifications/PLATFORM_NOTIFICATIONS_POLICY.md` — distinct Platform Admin channel.

**Frontend**

- `src/features/dashboard/components/AlertFeed.jsx`, `AlertCard.jsx`, `ActionableAlertCard.jsx` — placeholder/static smart alerts.
- `src/features/dashboard/hooks/useRealtimeAlerts.js` and `src/features/dashboard/api/dashboardApi.js` — nonexistent `getAlerts` call.
- `src/features/market-intelligence/components/CompetitorAlertThresholdForm.jsx` — placeholder rule form.
- `src/features/notifications/api/notificationsApi.js`, `hooks/useTenantNotifications.js`, `src/shared/components/layout/Topbar.jsx` — working transactional tenant inbox, 30-second polling, custom-plan link only.
- `src/features/settings/api/preferencesApi.js`, `components/NotificationSettings.jsx` — not-yet-supported settings.

**AI team**

- `src/market_scraper/market_repository.py` — `save_market_record`, `_previous_observation`, `_derive_events`, `_trigger_price_alerts`.
- `src/market_scraper/scoring.py` — `alert_matches` and comparator definitions.
- `src/market_scraper/tests/test_scoring.py` — existing comparator tests.
- `src/infrastructure/database/migrations/20260829020000_add_market_collection_intelligence.sql` — rule/event schema.
- `src/ai/dashboard/inventory.py` — inventory status calculation, **not** an alert producer.

### Audit limitation

This is a **source-code/static audit** of archived snapshots. Existence of code and DB models is not proof of a running service, deployed migration, correct privilege grants, recent market observations, delivery to a browser, or tested commercial gates. Verify these E2E before claiming production readiness.
