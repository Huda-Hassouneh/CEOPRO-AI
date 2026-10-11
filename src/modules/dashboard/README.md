# Dashboard Domain

The Dashboard domain gathers tenant data, calculates overview metrics, and returns one response for the owner-facing dashboard. It reads business and AI-produced data from the database; it does not call the AI service or write dashboard results.

## Start here

| If you need to…                   | Read…                                                                   |
| --------------------------------- | ----------------------------------------------------------------------- |
| Follow a dashboard request        | [Request flow](#request-flow)                                           |
| Understand a metric or chart      | [Metrics and calculations](#metrics-and-calculations)                   |
| See where AI data enters          | [Data ownership and integration](#data-ownership-and-integration)       |
| Prepare the real integration test | [End-to-end verification checklist](#end-to-end-verification-checklist) |

## Purpose and boundaries

This domain:

1. Authenticates a dashboard request and checks that the URL company belongs to the authenticated tenant.
2. Reads tenant-scoped company, invoice, product, inventory, competitor, review sentiment, forecast, and audit-log data.
3. Calculates and formats the dashboard response for the frontend.

AI-generated or AI-collected records are upstream database inputs. The dashboard reads forecast records, sentiment scores, and competitor price observations when they exist. There is no AI client, scraping job, webhook, or dashboard-specific persistence in this folder.

## Request flow

```text
index.ts → route → controller → service → repo → Prisma
```

- `index.ts` mounts the route at `/companies/:companyId/dashboard`.
- `route/dashboard.route.ts` declares `GET /` and applies authentication and tenant middleware.
- `controller/dashboard.controller.ts` validates the tenant/company match, reads `periodDays`, and accepts only `7`, `30`, or `90`.
- `service/dashboard.service.ts` calls the repository and handles an unexpected empty result.
- `repo/dashboard.repo.ts` sets tenant/user context for row-level security, reads the data, and assembles the response.
- `helper/dashboard.helpers.ts` handles date windows and pure formatting/calculation steps.

The response is wrapped as `{ status: "success", data }`. Errors are passed to the shared Express error middleware, except the controller's direct `401`, `403`, and `400` validation responses.

## API scenario

### Scenario: Tenant opens the dashboard

**Request:** `GET /companies/:companyId/dashboard?periodDays=30`

**Required context:** The authenticated request must include a tenant ID and user ID from the verified authentication middleware. The `companyId` path value must equal the authenticated tenant ID.

**Period options:** `7`, `30`, or `90` days. If omitted, the controller uses `30`.

**Result:** A single payload containing company currency/language, KPI cards, daily sales points, inventory details, demand forecast rows, competitor comparisons, and recent activity.

## Metrics and calculations

The date filters use UTC dates. For a selected period, the current period starts at UTC midnight `periodDays` days before tomorrow and ends before tomorrow's UTC midnight. The previous period is the same length immediately before the current period.

| Response field              | Source and current calculation                                                                                                                                                                                                                                                                                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `totalSales`                | Count of paid invoice rows for the tenant, in the company's currency, within the selected period. This counts invoices, not products sold.                                                                                                                                                                                                                |
| `revenues`                  | Sum of `total_amount` for those same paid invoices and period.                                                                                                                                                                                                                                                                                            |
| `growth`                    | `(current-period revenue - previous-period revenue) / previous-period revenue × 100`, rounded to one decimal in the response. It is `null` when previous-period revenue is zero.                                                                                                                                                                          |
| `salesOverview.points`      | One point per UTC date in the period, initialized to zero and then filled with the sum of matching paid invoice amounts for that date.                                                                                                                                                                                                                    |
| `totalProducts`             | Count of tenant products where `deleted_at` is null.                                                                                                                                                                                                                                                                                                      |
| `trackedCompetitors`        | Count of tenant competitor links where `is_tracked` is true.                                                                                                                                                                                                                                                                                              |
| `inventoryStatus.totals`    | Inventory rows are classified as out of stock when quantity is `0`, low stock when quantity is at or below `reorder_level`, and in stock otherwise.                                                                                                                                                                                                       |
| `inventoryStatus` KPI value | `inStock / totalItems × 100`, rounded to a whole percent. `totalItems` is the number of returned inventory rows. The value is unavailable when there are no rows.                                                                                                                                                                                         |
| `marketSentiment`           | Average `sentiment_score` for tenant reviews in the selected period that have `source_status = ALLOWED` and `safety_status = SAFE`. Scores above `0.1` are positive, below `-0.1` negative, and between those thresholds neutral. No score produces `null`.                                                                                               |
| `demandForecast.rows`       | If the tenant's plan has the `demand_prediction` feature, forecasts for active tenant products overlapping the seven-day window from today through six days later are grouped by product and summarized by `summarizeForecasts`. Rows without expected demand are omitted. At most four rows are returned.                                                |
| `competitorComparison.rows` | For each active tenant product with a matching currency, consider active mappings to tracked competitors and the newest available, exact, allowed price observation in the company's currency. Return the lowest competitor price, our price, the absolute price difference, its direction, and observation time. At most four product rows are returned. |
| `recentActivity.rows`       | Up to the 20 newest tenant audit-log rows. Optional JSON details are parsed defensively; malformed details do not fail the dashboard request.                                                                                                                                                                                                             |

`dataStatus` describes how the dashboard presents each section. For example, forecast values are marked estimated, while competitor comparisons are marked derived. These labels do not replace checking source freshness or data quality.

## Data ownership and integration

### Data read by this domain

- Company: primary currency and preferred language.
- Invoices: paid invoice totals and dates.
- Products and inventory: active product count, price, currency, localized name, stock, and reorder level.
- Tenant competitors, product mappings, and competitor prices: tracked competitors and their latest qualifying price observations.
- Reviews and sentiment results: allowed/safe review sentiment scores.
- Demand forecasts and feature access: plan-gated forecast summaries.
- Audit logs: recent tenant activity.

### AI-team handoff

The dashboard consumes AI-related results after they have been written to the database. Based on this repository, the relevant inputs are:

- Forecast rows in `demand_forecasts`, linked to tenant products and covering the requested forecast dates.
- Sentiment rows in `sentiment_results`, linked to reviews whose source and safety statuses qualify for display.
- Competitor price observations in `competitor_prices`, linked through active `competitor_product_mappings` to a tracked tenant competitor and tenant product.

The dashboard folder does not define how the AI team produces or inserts those records. Confirm the writer contract, tenant/product linkage, status fields, currency, and timestamps with the AI team during end-to-end testing.

### Consumer of this domain

The owner dashboard frontend consumes the endpoint response. This folder does not publish events or directly feed another backend service. If another consumer uses this endpoint or its calculations, record and verify it in the checklist below rather than assuming an integration.

## End-to-end verification checklist

Use this checklist during the real test with the AI team. Every item starts unchecked. Record a request/response sample, database query, job ID, or UI evidence beside the item after verification.

### Dashboard metrics and sections

- [ ] Metric/section: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed value/evidence: ********\_\_\_\_********
- [ ] Metric/section: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed value/evidence: ********\_\_\_\_********
- [ ] Metric/section: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed value/evidence: ********\_\_\_\_********
- [ ] Metric/section: ********\_\_\_\_******** Expected source and calculation: ********\_\_\_\_******** Observed value/evidence: ********\_\_\_\_********

### AI-produced data displayed by the dashboard

- [ ] AI output/table: ********\_\_\_\_******** Tenant/product linkage and required fields: ********\_\_\_\_******** Dashboard result/evidence: ********\_\_\_\_********
- [ ] AI output/table: ********\_\_\_\_******** Tenant/product linkage and required fields: ********\_\_\_\_******** Dashboard result/evidence: ********\_\_\_\_********
- [ ] AI output/table: ********\_\_\_\_******** Tenant/product linkage and required fields: ********\_\_\_\_******** Dashboard result/evidence: ********\_\_\_\_********

### Other systems or consumers

- [ ] Consumer/system: ********\_\_\_\_******** Data or response consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data or response consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data or response consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********

## Folder map

```text
dashboard/
├── index.ts
├── route/
│   └── dashboard.route.ts
├── controller/
│   └── dashboard.controller.ts
├── service/
│   └── dashboard.service.ts
├── repo/
│   └── dashboard.repo.ts
├── helper/
│   └── dashboard.helpers.ts
└── README.md
```

## Implementation notes

- Tenant and user IDs are used to set transaction-local database context; repository queries also include tenant filters.
- Competitor observations are selected by qualification and newest timestamp, but this repository does not apply a maximum-age rule. Check freshness requirements before treating an old observation as current.
- The dashboard keeps absent forecast or sentiment values unavailable rather than inventing production data.
- `periodDays` is validated in the controller; direct repository callers should pass only `7`, `30`, or `90`.
