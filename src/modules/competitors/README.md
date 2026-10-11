# Competitors Domain

This folder manages the competitors a tenant tracks and serves their stored competitor-product and price-history data. The AI team collects competitor information and inserts the resulting records into the database; this domain reads those persisted records and exposes them through the backend API.

## Start here

| If you need to…                   | Read…                                                                   |
| --------------------------------- | ----------------------------------------------------------------------- |
| Understand the request path       | [Request flow](#request-flow)                                           |
| See what each endpoint returns    | [API scenarios](#api-scenarios)                                         |
| Know where the values come from   | [Data and calculation rules](#data-and-calculation-rules)               |
| Confirm responsibility boundaries | [Ownership and downstream use](#ownership-and-downstream-use)           |
| Prepare a real AI-team test       | [End-to-end verification checklist](#end-to-end-verification-checklist) |

## Purpose and boundaries

The domain supports three tenant-scoped actions:

1. List tracked competitors.
2. Add a competitor to a tenant, reusing or creating its global competitor record.
3. View a tracked competitor's profile, including mapped products and price changes derived from saved price observations.

This folder does **not** call the AI service, scrape competitor websites, schedule collection, or calculate market-intelligence scores. The AI team's database writes are the upstream input to this API. Analysis fields that are empty here are not evidence of zero scores or a failed AI run; check the AI team's output contract and the owning consumer during the end-to-end flow.

## Request flow

```text
index.ts → route → controller → service → repo → Prisma
```

- `index.ts` exports the router.
- `route/competitors.route.ts` authenticates the request, requires a tenant, and declares the endpoints.
- `controller/competitors.controller.ts` reads the tenant and request parameters, calls the service, and returns JSON.
- `service/competitors.service.ts` applies basic required-field checks and delegates to the repository.
- `repo/competitors.repo.ts` reads or writes the competitor tables and shapes the API response.

The router's comments use `/companies/:companyId/competitors`; the route itself defines `/`, `/:competitorId`, and expects to be mounted by the parent router. Confirm the actual mount path in the application router when testing.

## API scenarios

All endpoints require an authenticated user with a tenant context.

### Scenario A: Tenant opens its tracked-competitors list

**Request:** `GET /competitors` (under the application's company/tenant route)

**Behavior:** The repository selects `tenant_competitors` for the current `tenant_id` where `is_tracked` is true, joins the global competitor record, and sorts by `added_at` newest first.

**Response data for each competitor:**

- `id`: global competitor ID
- `name`: tenant alias when present, otherwise the global competitor name
- `website`: global website URL, or an empty string when absent
- `industry`: global industry, or `Uncategorized` when absent
- `isTracked`: tracking flag
- `addedAt`: when the tenant link was added

### Scenario B: Tenant adds a competitor

**Request:** `POST /competitors`

**Body:** `{ "name": "…", "website": "…", "industry": "…" }`; only `name` is required by the current service.

**Behavior:** The repository looks for a global competitor by exact `competitor_name`. If none is found, it creates one, then upserts the tenant-to-competitor link as tracked. Repeating the request for a matching global competitor reuses that global record and reactivates the tenant link.

**Response:** competitor `id`, `name`, and `isTracked`.

### Scenario C: Tenant opens a competitor profile

**Request:** `GET /competitors/:competitorId`

**Behavior:** The repository first verifies that the competitor is linked to the current tenant. It then reads active product mappings and their available price observations, newest first.

**Profile data:**

- `mappedProducts`: one row per active mapping that has at least one available price observation. Includes the tenant's current product price, newest observed competitor price, currency, product URL/SKU when available, and observation timestamp.
- `activity`: a newest-first timeline row for each adjacent pair of stored observations whose numeric prices differ. Each row includes the previous and new price, currency, product name, and date.
- `metrics`, `strengths`, `weaknesses`: currently empty arrays.
- `presence`: currently `{ "current": [], "previous": [] }`.

If the competitor is not linked to the tenant, the service throws `Competitor not found or not tracked by this tenant`; the application's shared error middleware determines the final HTTP error response.

## Data and calculation rules

| API value                     | Source and current rule                                                                                                                                                                   |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tracked competitor list       | `tenant_competitors` joined to `global_competitors`; tracked links only; newest `added_at` first.                                                                                         |
| Competitor display name       | `custom_alias` if set, otherwise `global_competitors.competitor_name`.                                                                                                                    |
| Mapped product row            | Active `competitor_product_mappings` joined to `products`, with available `competitor_prices`. A row is returned only when at least one available price exists.                           |
| Our price                     | `products.current_price`, converted to a JavaScript number.                                                                                                                               |
| Competitor price              | Newest available `competitor_prices.scraped_price`, converted to a JavaScript number.                                                                                                     |
| Price-change activity         | For each mapping, compare each observation with the next older observation in descending `observed_at` order. Emit a row only when the numeric prices differ; sort all rows newest first. |
| Analysis metrics and presence | Not calculated or populated by this repository today; response placeholders are empty.                                                                                                    |

The activity timeline reflects persisted observations, not a separate AI-generated event stream. Its accuracy depends on the collector or ingestion process saving the correct product mapping, availability, price, currency, and observation time.

## Data ownership and downstream use

### Tables read or written here

- `tenant_competitors`: tenant-specific tracking link, alias, and added time.
- `global_competitors`: shared competitor identity and profile fields.
- `competitor_product_mappings`: tenant's mapping from its product to a competitor product.
- `competitor_prices`: saved competitor price observations.
- `products`: tenant product name and current price.

### Other systems

The AI team writes collected competitor data to the database. This domain then exposes the rows through its API; the files here do not directly publish events or call other systems. Market Intelligence, pricing recommendations, dashboards, or other consumers may use competitor data elsewhere in the application. Verify each consumer's actual source and calculation during integration testing rather than assuming a direct integration from this folder.

## End-to-end verification checklist

Use this during the real integration run with the AI team. Leave boxes unchecked until the result has been observed and recorded. Add evidence such as a request/response sample, database query, job ID, or UI screenshot beside each item.

### Competitor data produced by this domain

- [ ] Tracked competitor list matches the tenant's tracked links and excludes other tenants' links.
- [ ] Competitor profile shows the expected mapped products and omits mappings without available price observations.
- [ ] Each mapped product's current price, competitor price, currency, URL/SKU, and observation timestamp match persisted data.
- [ ] Price-change activity is produced only when adjacent stored prices differ and is ordered newest first.
- [ ] Untracked or unknown competitor IDs do not expose another tenant's profile.

### Metrics to verify end to end

- [ ] Metric name: ********\_\_\_\_******** Expected source/calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] Metric name: ********\_\_\_\_******** Expected source/calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********
- [ ] Metric name: ********\_\_\_\_******** Expected source/calculation: ********\_\_\_\_******** Observed result/evidence: ********\_\_\_\_********

### Other systems or outputs that may consume this data

- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********
- [ ] Consumer/system: ********\_\_\_\_******** Data consumed: ********\_\_\_\_******** Verified result/evidence: ********\_\_\_\_********

### AI-team database write and API handoff

- [ ] Confirm the AI team's output contract and the identifier used to connect a collected competitor to `global_competitors`.
- [ ] Confirm the AI team inserts or updates the correct tenant-to-competitor link in `tenant_competitors`.
- [ ] Confirm collected products map to the correct tenant product and `competitor_product_mappings` row.
- [ ] Confirm each observation is inserted into `competitor_prices` with the expected price, currency, availability, and `observed_at`.
- [ ] Confirm retries or repeated collection do not create misleading duplicate observations or duplicate price-change activity.
- [ ] Confirm the collected data appears through the profile endpoint and reaches each verified downstream consumer above.

## Folder map

```text
competitors/
├── index.ts
├── route/
│   └── competitors.route.ts
├── controller/
│   └── competitors.controller.ts
├── service/
│   └── competitors.service.ts
├── repo/
│   └── competitors.repo.ts
└── README.md
```

## Integration notes

- Tenant scope comes from `req.tenant_id`; repository reads and writes use that value.
- The global competitor pool is reused by exact competitor name. Check whether name normalization or URL-based identity is needed before relying on it for varied AI collector output.
- The profile's analysis arrays and presence periods are deliberately empty in this implementation. Do not interpret them as verified zero scores or zero presence.
- The public API mount remains application-defined; the route file itself does not include `/companies/:companyId`.
