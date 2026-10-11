# CEOPRO-AI — Dashboard Analytics

## How to use this document

This document defines **what the business needs**, **what the product must show**, **how each number should be calculated**, **which data must exist**, and **how to verify it**. Business rules are the target contract, not a claim that these rules already exist in the repository. Check items only after live, tenant-scoped verification.

**Contents**

1. [Business purpose and measurable value](#1-business-purpose-and-measurable-value)
2. [Business scenarios and decisions](#2-business-scenarios-and-decisions)
3. [Feature boundaries and ownership](#3-feature-boundaries-and-ownership)
4. [What the dashboard should display](#4-what-the-dashboard-should-display)
5. [KPI catalog and calculation contracts](#5-kpi-catalog-and-calculation-contracts)
6. [Data requirements and relationships](#6-data-requirements-and-relationships)
7. [Source readiness, correctness, and freshness](#7-source-readiness-correctness-and-freshness)
8. [Plans, permissions, and cross-feature entitlements](#8-plans-permissions-and-cross-feature-entitlements)
9. [Recommended user experience](#9-recommended-user-experience)
10. [Architecture and API responsibilities](#10-architecture-and-api-responsibilities)
11. [End-to-end business test scenarios](#11-end-to-end-business-test-scenarios)
12. [Acceptance and integration checklists](#12-acceptance-and-integration-checklists)
13. [Release plan and measurement of success](#13-release-plan-and-measurement-of-success)
14. [Decisions to finalize before implementation](#14-decisions-to-finalize-before-implementation)
15. [Terminology](#15-terminology)

---

## 1. Business purpose and measurable value

### 1.1 The business problem

A typical shop, distributor, online retailer, or small service business may know that it is selling, but cannot quickly answer **whether the business is doing better**, **what changed**, **where performance is weakest**, or **whether its records are current**. Its sales can be spread across invoices, spreadsheets, point-of-sale systems, imported files, and inventory records. Business owners should not need to manually reconcile these every morning.

**CEOPRO's promise:** After valid business data is connected or uploaded, show a trustworthy picture of current and historical business performance in one place, with clear definitions, comparisons, and paths to investigate.

### 1.2 Who benefits?

| Persona                    | What they need                                                             | Decision enabled                                                               |
| -------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Business owner             | Revenue, growth, sales activity, stock health, and data freshness          | Where should I focus today?                                                    |
| Operations / store manager | Best- and worst-selling products, missing stock information, sales changes | What should I investigate or replenish?                                        |
| Finance / business analyst | Reproducible KPIs, periods, currencies, reconciliation                     | Can I trust and explain these numbers?                                         |
| Team member (authorized)   | Appropriate subset of operational metrics                                  | Can I make an informed operational decision without accessing restricted data? |

These are **business personas**, not a claim that the current CEOPRO authorization model has each named role.

### 1.3 Jobs to be done

- **On login:** “Show me whether my business is healthy, compared with the previous equivalent period.”
- **After an import:** “Show which KPIs became available and which inputs are still missing.”
- **When revenue falls:** “Let me determine whether the problem is fewer orders, lower average order value, or a particular product.”
- **When a product underperforms:** “Let me see its sales trend and underlying records.”
- **Before a meeting:** “Give me defensible metrics with a clear as-of date and calculation basis.”

### 1.4 Success criteria

Business success is not “number of charts.” It is the ability to **make a sound decision from trusted numbers**. Evaluate the feature through KPI correctness, data readiness, time to first meaningful insight, successful drill-downs, and whether users can identify changes without spreadsheet work. Avoid treating dashboard page views as the only success metric.

---

## 2. Business scenarios and decisions

| Scenario                            | Business question                                | Dashboard evidence                                     | Possible next action                        | Boundary                                    |
| ----------------------------------- | ------------------------------------------------ | ------------------------------------------------------ | ------------------------------------------- | ------------------------------------------- |
| Morning business check              | Are sales improving?                             | Revenue, completed orders, growth vs comparable period | Investigate the weakest area                | Descriptive analytics                       |
| Revenue drops but orders are stable | Why did revenue decline?                         | Revenue, order count, average order value              | Check lower-priced mix or increased refunds | Do not invent a cause without data          |
| Revenue increases but orders fall   | Are customers spending more per order?           | Revenue + order count + AOV comparison                 | Review customer/product mix                 | Explanation requires drill-down             |
| Owner uploads first sales file      | Is the system ready to show performance?         | Import state, last successful sync, available KPIs     | Fix mapping or add missing records          | Zero is not the same as missing             |
| Top product stops selling           | Which products account for decline?              | Product sales ranking and time trend                   | Inspect product details and stock           | Forecasting is separate                     |
| Many products have no stock values  | Can I rely on inventory health?                  | Stock availability **and coverage**                    | Add stock information                       | Do not present incomplete stock as complete |
| Business uses multiple currencies   | What is actual revenue in my reporting currency? | Converted net revenue + FX basis                       | Verify currency configuration               | Never silently sum currencies               |
| A file is uploaded twice            | Did performance double?                          | Stable KPI total, dedupe/import log                    | Review duplicate import state               | Ingestion integrity required                |
| Manager looks at yesterday's data   | How recent is this figure?                       | Metric-specific `as_of` and latest ingestion state     | Sync source if stale                        | Never imply “live” without evidence         |

### 2.1 The important decision loop

**Question → trusted metric → comparison → drill-down → human decision.**

Dashboard Analytics should tell the user **what changed**, with a path to the underlying evidence. It should not make unsupported causal claims such as “sales fell because of a competitor” or automatically recommend a new price. Those belong to specialist features and require their own evidence and permissions.

---

## 3. Feature boundaries and ownership

### 3.1 In scope

- Tenant-scoped business KPI calculations for an explicit period.
- Historical period comparisons with consistent definitions.
- Trends and product-level breakdowns of existing facts.
- Simple descriptive stock availability where inventory data exists.
- Data-quality, last-updated, and missing-data indicators.
- Drill-down to authorized detail views with the same applied filters.
- Loading, empty, zero, partial, stale, and error states.
- Export/share only if separately implemented and authorized; not assumed part of the initial entitlement.

### 3.2 Out of scope as native Dashboard Analytics calculations

| Other feature              | What it owns                                                | What Dashboard Analytics may show                           |
| -------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------- |
| `market_intelligence`      | External market trends and competitor-based market insights | Entitlement-checked preview/link, not a free bypass         |
| `market_perception`        | Market perception scores                                    | Only when enabled and trustworthy                           |
| `demand_prediction`        | Future demand forecasts                                     | Entitlement-checked forecast preview                        |
| `inventory_intelligence`   | Reorder quantities and intelligent stock recommendations    | A link or licensed summary, not native AI advice            |
| `sentiment_analysis`       | Sentiment classification and aggregation                    | Licensed sentiment summary, where available                 |
| `business_recommendations` | Prescriptive business actions                               | Licensed recommendations panel                              |
| `ai_pricing`               | AI-assisted pricing recommendations                         | Licensed pricing insight or link                            |
| `report_generation`        | Generated downloadable business reports                     | Could consume dashboard metrics, but is separately entitled |
| `product_management`       | Product records, pricing, and inventory mutations           | Drill-down target; dashboard is read-oriented               |
| `data_integration`         | Connecting and importing data                               | Data freshness and source status only                       |

**Strict rule:** A dashboard entitlement does not automatically grant the other feature's data. Feature summaries must be authorized server-side, not simply hidden in the UI.

### 3.3 Separation of financial concepts

**Tenant business invoices and sales records** contribute to the customer's business KPIs. **CEOPRO subscription invoices from Stripe** describe what the customer pays CEOPRO and must **never** be mixed into that customer's sales revenue or paid-sales-invoice count. This distinction should be explicit in code, documentation, and tests.

---

## 4. What the dashboard should display

### 4.1 First screen — answer the most important questions

| Area               | Default content                                                                                   | User value                         |
| ------------------ | ------------------------------------------------------------------------------------------------- | ---------------------------------- |
| Header             | Business name, reporting period, reporting currency, last updated                                 | Understand context and reliability |
| KPI row            | Net revenue, completed orders/transactions, AOV, revenue growth                                   | Understand commercial performance  |
| Business scale row | Active products, paid business invoices (where supported), inventory availability + data coverage | Understand operations              |
| Revenue chart      | Daily/weekly/monthly time series depending on period                                              | Identify changes and seasonality   |
| Top products       | By net sales and optionally units                                                                 | Identify revenue concentration     |
| Data status        | Last successful import, processing jobs, unavailable metric explanations                          | Know what is missing or delayed    |

**Initial experience:** Prioritize the smallest set of **reliable** metrics. Do not add an attractive card unless its calculation, business definition, and source have been verified.

### 4.2 Optional later sections

- Sales by location, source/channel, category, or customer segment **only when those dimensions exist and are validated**.
- Discounts, returns, and gross margin (cost data and financial semantics required).
- Prior-period comparison charts and configurable saved views.
- Shortcuts to other entitled CEOPRO features.

### 4.3 Drill-down behavior

Every clickable KPI must preserve **tenant**, **period**, **currency**, and applicable **filters**. A click on revenue should show the records behind the displayed amount (or a reconciliation summary), not send the owner to a different unfiltered page. If the required record-detail view does not exist, label the card non-clickable instead of promising a broken interaction.

---

## 5. KPI catalog and calculation contracts

### 5.1 Non-negotiable conventions

1. **Tenant:** Aggregate only records authorized for the current tenant. Never accept an arbitrary tenant ID from the client as sufficient authorization.
2. **Period:** Use a half-open interval, `timestamp >= period_start AND timestamp < period_end`, resolved in the tenant's selected business timezone.
3. **Comparisons:** Use an equivalent preceding period (same duration and comparable completeness), not an arbitrary earlier month of different duration.
4. **Currency:** Report monetary KPIs in a specified reporting currency with a documented conversion method. If conversion cannot be performed reliably, mark the KPI unavailable/partial rather than summing mixed currencies.
5. **Duplicate protection:** Deduplicate by stable source/business identifiers or ingestion mapping rules. Do not count the same sale from both an invoice and its corresponding transaction.
6. **Status:** Define which source statuses represent genuinely completed/paid business activity; do not treat imported/pending records as finalized sales by default.
7. **Visibility:** Every KPI needs an explicit state: `ready`, `zero`, `no_data`, `partial`, `stale`, or `error` (names illustrative).
8. **Freshness:** Provide an `as_of` or last successful data update timestamp, which is not necessarily the time the dashboard request was made.
9. **Tax and shipping:** Explicitly define inclusion/exclusion before using the word “revenue.” Suggested default below: **net product sales excluding tax and shipping**.
10. **Unknowns:** Missing values must never be silently interpreted as zero.

### 5.2 Required KPI registry

| KPI / display label           | Business meaning                                                       | Proposed calculation and denominator                                                                                                                           | Minimum inputs                                    | Critical edge case                                          |
| ----------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------- |
| **Net Sales Revenue**         | Sales value retained from completed business sales                     | Sum line-level `(quantity × unit_price − line_discount − allocated_order_discount)` minus eligible refunds/returns; exclude tax/shipping under proposed policy | Sales lines, status, currency, discounts, refunds | Avoid invoice/transaction double count; multi-currency      |
| **Paid Business Invoices**    | Number of business invoices fully paid                                 | `COUNT(DISTINCT business_invoice_id)` with defined paid status in period                                                                                       | Business invoices, paid date/status               | Exclude CEOPRO Stripe billing, unpaid/voided invoices       |
| **Completed Orders**          | Number of finalized customer orders                                    | `COUNT(DISTINCT order_id)` after status/refund policy                                                                                                          | Order ID, completion timestamp, status            | A transaction row is not always an order                    |
| **Average Order Value (AOV)** | Average net sales per completed order                                  | `net_sales_revenue / completed_order_count`                                                                                                                    | Revenue and valid order count                     | Zero orders → `not_available`, not 0/0                      |
| **Revenue Growth**            | Increase/decrease vs previous comparable period                        | `(current_net_sales − previous_net_sales) / previous_net_sales × 100%`                                                                                         | Two comparable revenue periods                    | Previous period 0 → percent undefined                       |
| **Active Products**           | Current product catalog scale                                          | `COUNT(DISTINCT product_id)` meeting an agreed active/deleted status                                                                                           | Tenant products, lifecycle status                 | Duplicate product rows and soft deletion                    |
| **Product Sales Ranking**     | Which products contribute most sales                                   | Group eligible net sales by canonical product ID; rank descending                                                                                              | Mapped sale lines and product IDs                 | Unmapped or renamed products                                |
| **Inventory Availability %**  | Share of known-stock tracked products currently available              | `products_with_known_stock_and_available_qty > 0 / products_with_known_stock × 100%`                                                                           | Valid latest stock balances                       | Unknown stock excluded, not treated as out-of-stock         |
| **Inventory Coverage %**      | Whether stock data is complete enough to trust the availability figure | `products_with_known_stock / eligible_tracked_products × 100%`                                                                                                 | Product set and stock observations                | Very low coverage means availability is misleading          |
| **Data Freshness**            | How current each source/KPI actually is                                | Last successful accepted business-data import/sync for its relevant source                                                                                     | Ingestion history, source statuses, timestamps    | A recent failed attempt is **not** a recent successful sync |

**Notes:** Paid invoices can be shown only when the business ingestion model truly has a business invoice entity and trustworthy payment status. If CEOPRO instead reliably ingests only sales transactions, label the result **Completed Transactions** rather than calling it **Paid Invoices**. Inventory availability measures **count of products**, not units or inventory value; disclose this in the tooltip. Product tracking limits are plan entitlements, not part of a KPI formula.

### 5.3 Detailed revenue policy — explicit choice required

Recommended default for retail/product businesses:

```text
Net product sales = gross merchandise sales
                    − product/line discounts
                    − allocated order discounts
                    − eligible returns and refunds

Exclude: sales tax, shipping charges, tips, CEOPRO subscriptions,
         and uncollected/pending/cancelled business orders.
```

This is a **proposed reporting policy**, not accounting or tax advice. If CEOPRO supports service businesses, financial accounting, credit sales, mixed product/service invoices, or revenue recognition, define separate metric variants rather than forcing all records into a single ambiguous “Revenue” card.

**Refund recognition:** Choose and document either (A) refund-date adjustments, so the refund reduces the period it was issued, or (B) restating the original sale period. Do not mix both in the same trend without disclosure. Prefer explicit adjustment events and reconciliation; this decision is **open**.

**Invoice vs order source-of-truth:** Pick a canonical grain. If an order links to an invoice and a transaction, the system should compute each KPI from the proper relation, never union and sum them unconditionally.

### 5.4 Revenue growth and the zero-baseline rule

```text
Current 30-day net sales:   JOD 12,000
Previous comparable 30-day: JOD 10,000
Growth = (12,000 − 10,000) / 10,000 × 100 = +20%
```

If the prior period is **zero**, display `New sales (no comparable percentage)` rather than infinity or an invented 100% growth. If either period lacks enough trusted data, display `Insufficient comparable data`. For partial current periods (e.g. month-to-date), compare against the corresponding elapsed portion of the previous period and label it clearly, or compare only completed periods.

### 5.5 Stock availability vs stock coverage

```text
Product A: 8 units in stock
Product B: 0 units in stock
Product C: stock unknown

Known-stock products = 2
Products currently available = 1
Inventory Availability = 1 / 2 × 100 = 50%
Inventory Coverage = 2 / 3 × 100 ≈ 66.7%
```

Showing only **50% available** conceals the missing data. Show coverage too. Products with missing stock may not be categorized as out-of-stock; reservations, warehouse aggregation, negative stock, and product variants require explicit definitions before this KPI is trusted.

### 5.6 Product and invoice lifecycle rules

- Product catalog count should consistently handle active, archived, soft-deleted, and duplicate product records.
- Product sales rankings should preserve historical product identity when names/prices change.
- “Tracked Products” used for plan enforcement must not accidentally count untracked or archived products without a documented rule.
- Payment status must be sourced from **business invoice/collection** data, not billing events from CEOPRO.
- Revenue and paid invoice counts should use the appropriate business event date (sale/completion date vs payment date). The chosen event must be displayed in metric definitions.

---

## 6. Data requirements and relationships

> **Schema verification required.** The nouns below represent logical entities, not assertions about exact Prisma model names, table names, columns, or migrations in the active repository.

### 6.1 Logical data lineage

```text
Connected business system / uploaded business file
                 ↓
   Ingestion job + validation + duplicate detection
                 ↓
 Canonical tenant-scoped business records
   ├─ Product / product identifier
   ├─ Order or transaction + line items
   ├─ Business invoice + payment status (if ingested)
   ├─ Refund/return adjustments (if ingested)
   ├─ Inventory snapshot / stock balances (if ingested)
   └─ Currency, timestamps, source identifiers
                 ↓
  Deterministic, period-aware aggregations
                 ↓
  Authorized Dashboard Analytics API
                 ↓
  KPI cards, charts, drill-downs, data-state messages
```

### 6.2 KPI-to-source-and-join checklist

| KPI                    | Logical source and relationship to verify                                                                 | Verification task                                      |
| ---------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Active products        | Tenant → products; canonical ID; active/deleted semantics                                                 | Confirm actual Prisma model and status enum            |
| Net sales              | Tenant → completed orders/transactions → item lines → products; join discounts and refunds where recorded | Confirm grain, timestamp, status, currency, dedupe key |
| Completed orders       | Tenant → canonical order header; optional lines                                                           | Verify a real order ID; otherwise rename metric        |
| Paid invoices          | Tenant → **business** invoices → payment state / paid timestamp                                           | Verify records exist and are not Stripe subscriptions  |
| AOV                    | Same revenue and completed order datasets/filters                                                         | Verify numerator and denominator align                 |
| Revenue growth         | Same revenue aggregation over two exact periods                                                           | Verify timezone, completeness, FX and refund policy    |
| Top selling products   | Sales lines → stable product mapping                                                                      | Verify orphan lines and product deactivation behavior  |
| Inventory availability | Tenant → tracked products → most recent authoritative stock observation                                   | Verify per-warehouse/variant handling and staleness    |
| Inventory coverage     | Tracked/eligible products left joined to valid stock observations                                         | Count unmapped/missing stock separately                |
| Data freshness         | Data source → ingestion job/sync attempt → last successful committed import                               | Verify transaction commit time and per-source state    |

### 6.3 Key integration dependencies

- `data_integration`: receives files or connects sales/commerce/analytics providers.
- Data extraction/ingestion pipeline: validates input, normalizes schemas, associates records to the right tenant, records provenance, handles duplicates and failures.
- `product_management`: supplies canonical product identities, active status, and possibly latest inventory snapshots.
- Billing/entitlements: defines whether `dashboard_analytics` and relevant supporting features are granted. **Do not** confuse billing records with sales records.

### 6.4 Questions for actual code review

1. Which tables represent **business sales** rather than CEOPRO's own Stripe subscriptions?
2. Is each imported row a line item, an order, a product summary, or a transaction? What is its unique source identifier?
3. How does the import pipeline avoid inserting the same product or sale twice on repeat uploads?
4. Which timestamps are authoritative for sales and inventory, and are they stored in UTC?
5. Is stock available at product, variant, warehouse, or historical-snapshot grain?
6. Does the current schema record business invoices, refunds, tax, shipping, discounts, and exchange rates?
7. Is every relevant path (including raw SQL and background jobs) isolated by tenant and appropriate RLS policies?
8. How are invalid, partial, reprocessed, and succeeded imports represented?

If any answer is unknown, mark the dependent KPI **not verified** rather than assuming a formula works.

---

## 7. Source readiness, correctness, and freshness

### 7.1 State vocabulary

| State          | Business meaning                                      | Suggested UI wording                                             |
| -------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| `ready`        | Trusted data exists for metric/period                 | Show number and as-of date                                       |
| `zero`         | Trusted data exists; result is legitimately zero      | `JOD 0.000` or `0`                                               |
| `no_data`      | No sufficient accepted data                           | `No sales data yet`                                              |
| `partial`      | Some eligible data is missing/unmapped                | `Partial data — check sources`                                   |
| `stale`        | Last successful update beyond configured expectation  | `Last updated [timestamp]` with warning                          |
| `processing`   | Import is queued or processing                        | `Processing your data`                                           |
| `error`        | Metric couldn't be calculated or source import failed | `Data unavailable — retry/check source`                          |
| `not_entitled` | Specialist feature unavailable on plan                | Hide sensitive metric, show suitable upgrade path if appropriate |

A _database row count of zero_ is not enough to distinguish a genuine zero from a missing import. This requires data availability and source-state metadata.

### 7.2 Freshness contract

- Include a metric/source-specific `as_of` timestamp whenever possible.
- Track **last success** separately from **last attempted sync** and **last failed sync**.
- A recently uploaded file that remains `QUEUED` or `PROCESSING` does not make its data available.
- If one source is current and another is stale, avoid a blanket “everything is up to date.”
- Display timezone and reporting currency near period filters, particularly for multi-location operations.
- Define staleness expectations by source cadence and business needs; do not invent a universal SLA.

### 7.3 Data quality protections

- Preserve import provenance, canonical source IDs, and idempotent upsert rules.
- Detect conflicting currencies, missing product mappings, orphaned rows, invalid negative quantities, and duplicated external IDs.
- Exclude or quarantine invalid records according to a documented rule.
- Allow reconciliation of aggregate totals to the underlying records and ingest counts.
- Surface percentage coverage when an incomplete denominator could mislead an owner.

---

## 8. Plans, permissions, and cross-feature entitlements

### 8.1 Standard-plan contract

| Capability                              |                           Starter |   Growth | Enterprise |
| --------------------------------------- | --------------------------------: | -------: | ---------: |
| `dashboard_analytics`                   |                          Included | Included |   Included |
| Plan price / month                      |                               $55 |     $140 |       $350 |
| Maximum tracked products                |                               250 |    2,000 |     10,000 |
| Connected data sources                  |                                 1 |        5 |         20 |
| Native historical/current business KPIs | Yes, subject to data availability |      Yes |        Yes |

The tracked-product and connected-source figures are **separate entitlements**, not dashboard usage quotas. Dashboard Analytics does not have a separately configured price.

### 8.2 Entitlement design

```json
{
  "featureKey": "dashboard_analytics",
  "type": "boolean",
  "enabled": true
}
```

Use the actual CEOPRO entitlement schema/contracts when implementing; JSON above is **conceptual**. On every privileged backend request, verify authenticated principal, tenant membership, permission, and effective entitlement. Frontend hiding alone is insufficient. Handle suspended/expired/changed subscriptions through CEOPRO's central entitlement logic rather than per-page hardcoding.

### 8.3 What users are paying for

A customer on Starter should receive **accurate essential KPIs**, not a deliberately broken dashboard. Upgrades should add genuinely different capabilities (market intelligence, demand forecasting, more tracked products, more sources, etc.). Users without the specialist entitlement must not see that specialist metric merely because the dashboard embeds it.

### 8.4 Tenant isolation and privacy

- Use authenticated tenant context; do not trust a client-provided `tenantId` for authorization.
- Enforce isolation in repository queries and DB policy paths.
- Avoid leaking competitor, customer, or personnel data through shared caches or drill-down endpoints.
- Distinguish the platform owner/admin's CEOPRO billing/admin metrics from a tenant's business dashboard.
- If team-level metric permissions are added, use explicit permissions rather than assuming all tenant users can view revenue.

---

## 9. Recommended user experience

### 9.1 Landing layout

```text
Business Overview                           Period [Last 30 days ▼]
Reporting currency: JOD                     Data as of: 10 Oct, 15:00

[ Net sales ] [ Completed orders ] [ Avg. order value ] [ Growth ]

[ Revenue over time — current vs comparable previous period       ]

[ Top selling products          ] [ Inventory availability       ]
[ A / B / C with values        ] [ 50% availability             ]
[ Drill into product           ] [ 66.7% coverage; partial data ]

Data status
[ Last successful import ] [ In-progress jobs ] [ Missing inputs ]
```

The screen should be responsive, bilingual (English/Arabic), support RTL, display JOD/USD correctly, and use accessible contrast and unambiguous directionality for positive/negative indicators. Do not equate “revenue increased” with unequivocally positive business health without context (e.g. costs, refunds).

### 9.2 Helpful empty and exceptional states

**First-time owner, no files:** `Your dashboard is ready. Connect a business data source or upload sales data to see your performance.` Provide an actual working link to Data Connections.

**Only product catalog imported:** Show verified product count; for revenue, say `Sales data not connected` rather than `JOD 0`.

**Import in progress:** Show last known verified KPIs, clearly labeled with as-of time, and a processing indicator. Do not merge uncommitted records.

**Source failed:** Keep previously verified values if safe, label them stale, show last success and failure details or support path.

**Undefined comparison:** `Insufficient previous-period data` rather than `—` without explanation or `∞%`.

**Partial inventory:** Show the denominator coverage explicitly, not a lone green percentage.

### 9.3 Filters and formatting

- Default period: last 30 completed days or a clearly specified rolling 30 days; agree this choice.
- Period presets: Today, Last 7 Days, Last 30 Days, This Month, Custom (subject to performance and data coverage).
- Chart grouping adapts to range: daily for short ranges, weekly/monthly for longer ranges.
- Show source business timezone and selected currency; never imply UTC timestamps are local business days.
- Format JOD values consistently; do not use misleading precision or compare translated number strings.
- Consider screen-reader labels, semantic chart legends, and accessible color contrast.

---

## 10. Architecture and API responsibilities

This section suggests implementation responsibilities consistent with the CEOPRO feature-domain pattern. **It is not an assertion that the listed files/endpoints already exist.**

```text
UI Dashboard Page
  └─ Frontend analytics hook / API client
      └─ Route (authentication, tenant, entitlement, validation)
          └─ Controller (HTTP request/response mapping)
              └─ Service (business metric policies, periods, states)
                  └─ Repository (Prisma, safe SQL aggregations, tenant scope)
                      └─ PostgreSQL / canonical business data
```

### 10.1 Backend responsibilities

| Layer            | Must do                                                                    | Must not do                                               |
| ---------------- | -------------------------------------------------------------------------- | --------------------------------------------------------- |
| Route            | Authenticate, require tenant, enforce feature/permission, validate filters | Trust unsanitized tenant or date inputs                   |
| Controller       | Parse request, map result/error to stable API response                     | Implement KPI formulas ad hoc                             |
| Service          | Apply metric definitions, comparability, completeness and currency rules   | Return misleading `0` for missing data                    |
| Repository       | Tenant-scoped aggregate and detailed queries; match real schema            | Join an invoice to lines in a way that multiplies totals  |
| Ingestion worker | Commit valid normalized data, record provenance and successful completion  | Mark import complete before durable results exist         |
| Frontend         | Display values, metric definitions, states, currency, date context         | Recalculate finance-critical KPI differently than backend |

### 10.2 Illustrative response shape

```json
{
  "period": {
    "start": "2026-09-10",
    "endExclusive": "2026-10-10",
    "timezone": "Asia/Amman",
    "reportingCurrency": "JOD"
  },
  "metrics": {
    "netSalesRevenue": {
      "value": "180.000",
      "currency": "JOD",
      "state": "ready",
      "asOf": "2026-10-09T15:00:00Z",
      "definitionVersion": "proposed-v1"
    },
    "revenueGrowthPct": {
      "value": 20,
      "state": "ready",
      "comparison": "previous_equivalent_period"
    }
  },
  "dataHealth": {
    "lastSuccessfulSync": "2026-10-09T15:00:00Z",
    "inProgressImports": 0
  }
}
```

**Example only.** Exact route paths, envelope, error codes, decimals, and types must preserve CEOPRO's existing API contract unless a versioned change is approved. Monetary values as strings can help avoid floating-point precision loss; calculate decimal money in a suitable decimal/numeric representation.

### 10.3 Performance and operations

- Aggregate by date range and tenant with appropriate indexes; avoid loading all sale lines to the browser.
- Consider materialized daily rollups for large tenants, with explicit invalidation on backfills, corrections, or refunds.
- Key caches by tenant + permissions/entitlements + period + currency + filters + version; never leak shared cache data.
- Use structured logs for request failures, source failures, and latency; avoid logging private financial records.
- Make aggregations reproducible with definition/version metadata as policies evolve.
- Do not invoke an AI model for standard KPI arithmetic, rendering, or every refresh: reliable deterministic calculations are usually cheaper and more auditable.

---

## 11. End-to-end business test scenarios

### Scenario A — Small shop, complete trustworthy data

**Fixture** (single tenant, same reporting currency and eligible current period):

- Three eligible products: **A**, **B**, and **C**.
- Completed paid order/invoice **101**: product A, `2 × JOD 50 = JOD 100`.
- Completed paid order/invoice **102**: product B, `1 × JOD 100 = JOD 100`, with an eligible **JOD 20** refund/return adjustment applied to the **same reporting period** under the selected test policy.
- No other discounts, taxes, shipping charges or sales.
- Previous comparable period's verified net sales: **JOD 150**.
- Latest stock: A = 8, B = 0, C = unknown.

**Expected output:**

| KPI                       |              Expected | Reason                                 |
| ------------------------- | --------------------: | -------------------------------------- |
| Net sales revenue         |           JOD 180.000 | 100 + 100 − 20                         |
| Paid business invoices    |                     2 | Both completed and paid, counted once  |
| Completed orders          |                     2 | Two distinct order IDs                 |
| Average order value       |            JOD 90.000 | 180 ÷ 2                                |
| Revenue growth            |                  +20% | (180 − 150) ÷ 150 × 100                |
| Active products           |                     3 | A, B, C are active                     |
| Inventory availability    |                   50% | 1 in-stock of 2 known-stock products   |
| Inventory coverage        |       66.7% (approx.) | 2 known-stock of 3 eligible products   |
| Top products by net sales | A: JOD 100; B: JOD 80 | Refund allocation reflected in ranking |

**Verify:** Underlying drill-downs reconcile to the same figures without duplication.

### Scenario B — First login, no business imports

**Given:** Tenant has active plan and no accepted sales data.  
**Expected:** Dashboard accessible; revenue/order KPIs show `no_data`; onboarding CTA links to Data Connections. Do not show zero revenue as a verified result.

### Scenario C — Products exist; sales do not

**Given:** Tenant has 46 distinct catalog products but no accepted eligible sales records.  
**Expected:** Verified catalog count may be 46; revenue/order/AOV indicate unavailable sales data. Re-uploading three copies of the same product catalog must not triple the canonical product count unless these really are distinct product identities.

### Scenario D — Repeat import and backfill

**Given:** Same source file is processed twice, then a corrected file updates some existing sales.  
**Expected:** Duplicate sales are not counted twice; approved corrections update relevant historical periods; trend and cached aggregates reflect the correction.

### Scenario E — Different tenants, identical source IDs

**Given:** Tenant A and Tenant B both have an external invoice `101`.  
**Expected:** Each tenant sees only its own invoice and totals; cross-tenant cache and drill-down access fail closed.

### Scenario F — Currency and timezone boundary

**Given:** A sale close to midnight in UTC appears on the next/previous day in the tenant's timezone; some sales use USD and others JOD.  
**Expected:** Dates are assigned in the selected business timezone; conversions follow the documented rate source/policy or metrics are flagged incomplete. Never simply add `100 USD + 100 JOD = 200 JOD`.

### Scenario G — No previous comparable revenue

**Given:** Current verified net sales are positive; previous verified period's net sales are zero.  
**Expected:** `Revenue growth percentage unavailable — no prior sales base`, not infinity or 100%.

### Scenario H — Import is queued or fails

**Given:** Last successful import was two days ago, while a new file is queued or the latest attempt fails.  
**Expected:** Display values only from accepted/committed data; show last-success date plus current job status.

### Scenario I — Starter accesses a specialist panel

**Given:** Starter has `dashboard_analytics`, but not `demand_prediction`.  
**Expected:** Starter can see historical sales analytics, not forecast values or forecast API responses. Growth/Enterprise access must still depend on their effective entitlements and the data needed to calculate forecasts.

### Scenario J — Invoice vs transaction duplicate

**Given:** An invoice and transaction both describe the same JOD 100 business sale.  
**Expected:** Revenue remains JOD 100; paid invoices count 1; completed orders count 1 where a canonical order relationship exists.

---

## 12. Acceptance and integration checklists

> All checks start **unchecked**. They are not proof that CEOPRO already implements the behavior. Mark an item only after an actual code review, automated test, or end-to-end database check. For each verified metric, record the real files, tables, SQL/Prisma query, and test evidence.

### 12.1 Business contract

- [ ] Business owner can tell whether performance improved over a comparable period.
- [ ] Every KPI has a readable definition and an understandable business purpose.
- [ ] Sales revenue has an agreed tax/shipping/discount/refund policy.
- [ ] Business sales invoices are explicitly separated from CEOPRO subscription invoices.
- [ ] Historical figures reconcile to their underlying source records.
- [ ] Every trend uses the agreed timezone and comparable period methodology.
- [ ] Missing, true-zero, partial, stale, processing, and error conditions are distinguishable.
- [ ] Revenue decrease and inventory issues are displayed neutrally without fabricated AI explanations.

### 12.2 Per-metric implementation tracking

| Metric                                           | Actual source model/table | Join/filter and calculation verified | E2E verified | Notes / evidence |
| ------------------------------------------------ | ------------------------- | ------------------------------------ | ------------ | ---------------- |
| Net sales revenue                                | TBD                       | ☐                                    | ☐            |                  |
| Paid business invoices                           | TBD                       | ☐                                    | ☐            |                  |
| Completed orders or clearly labeled transactions | TBD                       | ☐                                    | ☐            |                  |
| Average order value                              | TBD                       | ☐                                    | ☐            |                  |
| Revenue growth                                   | TBD                       | ☐                                    | ☐            |                  |
| Active products                                  | TBD                       | ☐                                    | ☐            |                  |
| Product sales ranking                            | TBD                       | ☐                                    | ☐            |                  |
| Inventory availability                           | TBD                       | ☐                                    | ☐            |                  |
| Inventory coverage                               | TBD                       | ☐                                    | ☐            |                  |
| Data freshness/status                            | TBD                       | ☐                                    | ☐            |                  |

### 12.3 Systems responsible for feeding the dashboard

| Upstream system                     | What it supplies                                          | Connected and validated | Owner / files / evidence |
| ----------------------------------- | --------------------------------------------------------- | ----------------------- | ------------------------ |
| Product Management                  | Product identity, active status, tracking, possibly stock | ☐                       |                          |
| Data Connections                    | Source association, import status, normalization          | ☐                       |                          |
| Business sales ingestion            | Orders/transactions, sale-line values, timestamps         | ☐                       |                          |
| Business invoice/payment ingestion  | Valid business paid invoice statuses, if supported        | ☐                       |                          |
| Returns/refunds ingestion           | Adjustments and attribution                               | ☐                       |                          |
| Currency and reporting settings     | Reporting currency, conversion policy                     | ☐                       |                          |
| Tenant settings                     | Tenant timezone and display locale                        | ☐                       |                          |
| Subscription entitlements           | `dashboard_analytics` and specialist-feature access       | ☐                       |                          |
| Background workers / ingestion jobs | Durable completion and last successful commit state       | ☐                       |                          |

### 12.4 Security, performance, and operational tests

- [ ] Starter, Growth, and Enterprise grant the feature correctly.
- [ ] Requests without feature entitlement are rejected by backend authorization.
- [ ] Tenant-scoped queries do not leak another tenant's business figures.
- [ ] Raw SQL, Prisma queries, RLS, workers and cache paths are all reviewed for isolation.
- [ ] Paid invoice logic cannot include Stripe platform subscriptions.
- [ ] Repeat imports and transaction/invoice joins do not double count values.
- [ ] Monetary calculations use reliable decimal handling and defined currency conversion.
- [ ] Chart totals match card totals for matching period and filters.
- [ ] Source health and last-success timestamps reflect committed accepted data.
- [ ] UI presents meaningful loading, no-data, error, and stale states.
- [ ] English/Arabic translations and RTL layout are correct.
- [ ] Production-like tenant data volume meets an agreed API latency budget.
- [ ] Logs/observability can diagnose missing source data and failed calculations.
- [ ] Unit, integration, and representative E2E tests exist and pass.

### 12.5 Suggested evidence template

Copy one block per metric while validating the repository:

```text
Metric:
Business definition:
Actual frontend page/component:
Actual backend route/controller/service/repository:
Actual Prisma models/tables/relations:
Required input fields and business statuses:
Filters (tenant, period, timezone, currency, lifecycle):
Calculation SQL/Prisma logic:
No-data/zero/partial state logic:
Fixture and expected result:
Observed result:
Automated test reference:
Verified by / date:
Open issues:
```

---

## 13. Release plan and measurement of success

### Phase 1 — Trusted core (recommended MVP)

- Tenant-scoped active products, revenue, completed orders/transactions, AOV, growth, period filters.
- A stable revenue trend and product ranking when supported by validated sale lines.
- Clear data readiness and import freshness states.
- End-to-end reconciliation tests for source data and financial semantics.
- Starter/Growth/Enterprise entitlement checks and cross-tenant security tests.

**Release gate:** A business owner can reproduce every displayed finance-critical total from a known test dataset; unsupported metrics do not silently appear as zero.

### Phase 2 — Operational completeness

- Paid business invoices where backed by true business payment records.
- Inventory availability **with** coverage and stale-stock messaging.
- Drill-downs, source-level status, record correction/backfill behavior.
- Performance tuning and aggregation for larger tenants.

### Phase 3 — Deeper business exploration

- Validated channel/category/location comparisons and saved filters.
- Specialist-feature previews respecting their own entitlements.
- Optional gross margin, refund rate, advanced comparison and report handoffs after real source data supports them.

### Suggested measurable outcomes

- **Time to first verified KPI** after initial valid import.
- **Metric reconciliation accuracy** on golden fixtures and sampled tenant data.
- **Unexplained-zero incidents** (aim for zero).
- **Import-to-dashboard freshness lag** after successful durable commit.
- **Drill-down consistency** between high-level totals and underlying records.
- **Cross-tenant data exposure/security test failures** (must be zero).

---

## 14. Decisions to finalize before implementation

| Decision                               | Suggested default                                         | Why it matters                        | Status                    |
| -------------------------------------- | --------------------------------------------------------- | ------------------------------------- | ------------------------- |
| Definition of revenue                  | Net product sales excluding taxes/shipping                | Avoid ambiguous financial comparisons | **Open**                  |
| Canonical sales grain                  | Valid completed business order + line items               | Avoid multiple counts                 | **Open / inspect schema** |
| Completed orders vs transactions label | Show orders only if stable order IDs exist                | Prevent misleading counts             | **Open**                  |
| Business invoice support               | Show only if reliable payment state exists                | Preserve “Paid” meaning               | **Open / inspect schema** |
| Refund timing                          | Explicit refund-date adjustments or restated sales period | Historical correctness                | **Open**                  |
| Date semantics                         | Tenant timezone; documented sale/paid timestamps          | Daily and monthly accuracy            | **Open**                  |
| Default period                         | Last 30 **completed** days                                | Comparable and stable values          | **Open**                  |
| Reporting currency and FX              | Configured business currency + documented conversions     | Multi-currency accuracy               | **Open**                  |
| Inventory availability basis           | Product count, known-stock only, with coverage            | Avoid confusing units and stock value | **Open**                  |
| Tracked product scope                  | Define lifecycle and variant counting                     | Subscription-limit consistency        | **Open**                  |
| Freshness thresholds                   | Source-specific expected cadence                          | Avoid fake real-time promises         | **Open**                  |
| Data availability contract             | Per-metric readiness and state metadata                   | Zero vs missing correctness           | **Open**                  |
| Team metric permissions                | Explicit permission policy where supported                | Financial data privacy                | **Open**                  |

**Implementation note:** Before changing code, replace each “Open / inspect schema” with an observed model, relation, enum, and validated business rule. Preserve any established production API contract unless a migration/versioning plan is approved.

---

## 15. Terminology

- **KPI:** Key performance indicator—a quantity answering a specific business question.
- **Business revenue:** Money generated by the tenant's own business activity under an explicitly defined recognition policy; **not** the tenant's subscription payments to CEOPRO.
- **Canonical grain:** The entity counted/summed exactly once (for example, a distinct order versus each line item).
- **AOV:** Average order value—net eligible revenue per completed order.
- **Reporting period:** The exact date/time interval the metric covers.
- **Comparable period:** A previous time interval using matching definitions, duration, and data completeness.
- **Source coverage:** Share of eligible entities for which required input data exists.
- **Data freshness:** Time of the most recent successfully committed and accepted data relevant to the KPI.
- **Drill-down:** Navigation from an aggregate KPI to the underlying filtered evidence.
- **Entitlement:** A subscription-granted capability or limit enforced by the backend.
- **Descriptive analytics:** Describes what has occurred; distinct from forecasting and AI recommendations.

---

**Document scope:** `dashboard_analytics` only — feature 1 of the requested CEOPRO-AI feature series. Continue to `market_intelligence` only when the user says **Next**.
