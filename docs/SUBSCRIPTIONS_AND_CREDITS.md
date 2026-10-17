# KEEL subscriptions, Data Credits and AI Credits

How KEEL's plans, usage budgets and billing work, what is enforced where,
what still needs real prices before it can run, and how to deploy or roll
back. The backend is the source of truth for every limit: the screens only
display what `/billing/*` returns.


## 1. Plans

| | Standard | Plus | Pro | Custom |
|---|---:|---:|---:|---|
| Plan key (database, Stripe) | `starter` | `growth` | `enterprise` | `custom` |
| Monthly price | $55 | $140 | $350 | quoted |
| Free trial | 14 days | 14 days | 7 days | per contract (0-90 days) |
| Products | 100 | 250 | 750 | contract |
| Reports per month | 5 | 20 | 60 | contract (default 60) |
| Team seats | 5 | 20 | 60 | contract (default 60) |
| Competitors | no fixed count, limited by Data Credits | same | same | same |
| Data Credits per month (trial) | 436 (43) | 1,111 (111) | 2,780 (278) | contract (default 2,780 / 278) |
| AI Credits per month (trial) | 436 (43) | 1,111 (111) | 2,780 (278) | contract (default 2,780 / 278) |

- The plan keys stay `starter` / `growth` / `enterprise` because existing
  Stripe prices, subscriptions and webhooks already resolve to them. Only the
  names customers see changed. The 2026 `standard` ($49) and `pro` ($99)
  packages are retired: companies still on them keep working under "Legacy"
  names, with the nearest current plan's report, seat and credit terms.
- 3-month (10% off) and 6-month (20% off) billing periods are unchanged.
- Other allowances are unchanged (storage, connected data sources, reviews
  analysed, document processing, marketing images). The assistant's monthly
  token cap stays as an internal safety limit and is no longer shown.
- All values are in `usage_plans` / `usage_plan_limits` (migration
  `20261020000000_keel_subscriptions_and_credits.sql`), not in code.

## 2. Data Credits and AI Credits

Two separate monthly budgets. They are never interchangeable (no conversion
policy exists).

- **Credits are customer units; money stays in USD.** 1 credit = $0.01 of
  provider cost (`billing_cost_policy.credit_usd_value`). The ledger stores
  both the USD cost and the credits.
- **Every paid provider call** is reserved before it is sent, then settled
  to what the provider really billed (`src/ai/billing/credits.py`):
  1. **Reserve** (its own committed transaction, under a per-company lock):
     - the company's plan must grant access;
     - the provider must not be switched off or over its monthly cap;
     - the estimated cost (units × configured price × (1 + safety margin))
       must fit in what's left this period;
     - for AI: request size and in-flight limits.
     
     Anything else refuses the call, and the call is never sent.
  2. **Call** the provider.
  3. **Settle**: measured units × price. Then:
     - A call the provider billed but didn't report is charged at the
       estimate and marked `pending_reconciliation`.
     - A failure after the request left is charged when that provider bills
       failures (`charged_on_failure`).
     - A call that never left, or an error response the provider doesn't
       bill, is released.
- **AI** is measured from provider-reported tokens. Input, output, cache-read
  and cache-write tokens are priced separately, per model. Every attempt is
  its own ledger row, so a retry after an empty answer is billed (it wasn't
  counted before this change). Per-company limits:
  - at most 3 AI calls in flight;
  - 24,000 input tokens and 4,000 output tokens per call.

  There is no automatic fallback model (`ai_fallback_policy = 'none'`). If
  the provider is unavailable, the request fails; it never silently moves to
  a different, possibly more expensive, model.
- **Data** is metered where requests leave the server:
  - `market_discovery/http.request_json` (every discovery provider,
    geocoding, news);
  - `web_search._default_fetch`;
  - the direct Google Places, Google Custom Search, Apify and SerpAPI calls.

  `src/market_scraper/provider_billing.py` maps each host and path to a
  provider. Public open-data services are free and skip metering:
  OpenStreetMap/Overpass, Nominatim, Photon, Wikidata, GDELT, Overture, Open
  Food Facts, YouTube Data API (quota-limited, not billed), and self-hosted
  SearXNG. **An unknown host is treated as a paid provider with no price, so
  it is refused.**
- **Usage classes** (`simple_question`, `multi_competitor_analysis`,
  `long_form_content`, `image_generation`) label operations for estimates and
  the usage history. Billing always uses the measured cost.
- **At the limit:**
  - New discretionary work is refused with 402. This covers discovery runs,
    enrichment, price lookups, AI questions and analysis.
  - Scheduled discovery refreshes skip the company.
  - Only system reconciliation and admin recovery operations may finish past
    the limit.
  - Credits renew with the next billing period.
  - Top-ups are disabled. The database constraint
    `CHECK (NOT top_ups_enabled)` holds until payment, pricing and refunds for
    them exist.
- **Warnings:** at 70%, 85% and 100% (`billing_cost_policy.warning_thresholds`):
  - an alert in the bell and in the optional email summary;
  - the state shown on the Billing page.
- **A crash never makes spending free:** a reservation whose process died
  keeps counting. `billing/maintenance.py` charges its estimate after 15
  minutes and marks it for reconciliation.
- **Reconciliation:** `scripts/billing_admin.py reconcile` records the
  provider's final cost. The difference becomes an append-only adjustment,
  idempotent per reference. Apify calls are always reconciled, because Apify
  bills a run after it ends.
- **Budgets are never raised automatically** when real costs exceed
  estimates. Only an operator adjustment (audited) changes a balance.

## 3. How the budgets were calculated

`src/ai/billing/cost_model.py` (also `python -m scripts.billing_admin budgets`).
`test_plan_budgets_match_the_cost_model` keeps the migration's numbers equal
to the model's output.

```
net monthly revenue  = (period charge - processing fee - refund allowance) / months
variable cost budget = net monthly revenue x (1 - 0.70 target contribution margin)
AI budget            = variable budget x 35%      Data budget = variable budget x 35%
held back            = variable budget x 30%      (storage and processing, reports and
                                                  exports, infrastructure allocation,
                                                  estimation error)
credits              = budget USD / $0.01, rounded down; trial = 10% of a month
```

Each plan is sized on its least profitable option: the 6-month period at
20% off, so the budget is safe whichever period a company picks.

| | Standard | Plus | Pro |
|---|---:|---:|---:|
| 6-month charge (20% off) | $264.00 | $672.00 | $1,680.00 |
| Processing fee (5.4% + $0.30) | $14.56 | $36.59 | $91.02 |
| Net revenue per month | $41.57 | $105.90 | $264.83 |
| Variable cost budget (30%) | $12.47 | $31.77 | $79.45 |
| AI budget / Data budget (35% each) | $4.37 / $4.37 | $11.12 / $11.12 | $27.81 / $27.81 |
| Held back (30%) | $3.74 | $9.53 | $23.83 |
| AI / Data Credits per month | 436 / 436 | 1,111 / 1,111 | 2,780 / 2,780 |
| Trial credits (each budget) | 43 | 111 | 278 |

Example from the specification: $100 of net revenue at a 70% margin target
leaves $30 of variable cost (`test_variable_cost_formula_follows_the_spec`).

**Assumptions to replace with real figures (these are planning numbers, not
proof of profitability):**

- **Processing fee 5.4% + $0.30.** A conservative stand-in: card rate plus
  international-card and currency-conversion surcharges. Use KEEL's own
  Stripe account rates.
- **Taxes.** Collected on top of the price (Stripe prices are tax-exclusive),
  so they are excluded from revenue.
- **Refunds.** 0%: KEEL doesn't refund a started period (cancellation takes
  effect at period end).
- **Infrastructure allocation.** Unknown until there is a real hosting
  invoice. It is covered by the 30% held back, and
  `subscription_pricing.py`'s floor price uses `SERVER_ALLOCATION_USD` once
  set.
- **The 35 / 35 / 30 split.** A starting point. Re-balance it from observed
  usage in `usage_ledger` after the first month.

**What a credit buys** depends on the provider prices once configured
(section 4). For example, if Groq's `openai/gpt-oss-20b` is confirmed at
the rates third-party trackers list ($0.075 input / $0.30 output per
million tokens), a typical 2,000-token assistant answer would cost about
$0.0003, which is 0.03 AI Credits. These figures are not confirmed and
are not configured.

## 4. Provider prices: what must be set before paid operations run

Prices are never invented. Seeded at $0:
- the free public services above;
- the local llama-server;
- the keyless Pollinations image endpoint.

Every paid provider below starts unpriced. **Its calls are refused
(`COST_NOT_CONFIGURED`) until an operator records the confirmed price:**

| Budget | Provider (operation) | Unit | Where the real price comes from |
|---|---|---|---|
| AI | `groq` (model id, e.g. `openai/gpt-oss-20b`) | input/output (and cached) tokens | Groq pricing page / invoice |
| AI | `huggingface` (`image_generation`) and any HF chat model | image / tokens | Hugging Face Inference bill |
| AI | `cloudflare` (`image_generation`) | image | Cloudflare Workers AI bill |
| AI | `paid` (`PAID_LLM_*` provider) | tokens | that vendor |
| Data | `google_places` (`text_search`, also legacy Places endpoints) | request | Google Maps Platform bill |
| Data | `google_geocoding` (`geocode`) | request | Google Maps Platform bill |
| Data | `google_cse` (`search`) | request | Google Programmable Search |
| Data | `brave_search`, `tavily`, `serpapi` (`search`) | request | provider plan |
| Data | `apify` (`actor_run`) | record (reconciled) | Apify actor pricing / run cost |

```bash
cd backend   # DATABASE_URL = the schema-owning role
python -m scripts.billing_admin set-price --budget ai --provider groq --operation openai/gpt-oss-20b \
  --unit input_token --usd-per-million <confirmed> --source "Groq invoice 2026-10" --verified-on 2026-10-20 \
  --by "<name>" --reason "Confirmed price"
python -m scripts.billing_admin set-price --budget ai --provider groq --operation openai/gpt-oss-20b \
  --unit output_token --usd-per-million <confirmed> --source "..." --verified-on 2026-10-20 --by "<name>" --reason "..."
python -m scripts.billing_admin set-price --budget data --provider google_places --operation text_search \
  --unit request --usd <confirmed> --source "..." --verified-on 2026-10-20 --by "<name>" --reason "..."
```

The marketing image chain skips an unpriced provider and tries the next
one (Pollinations is free). Discovery providers that are refused are
reported as failed sources. The run continues with the free ones.

## 5. Spending controls

- **Per company:** the two credit budgets above.
- **Per provider or model:**

  ```bash
  python -m scripts.billing_admin set-control --provider groq --monthly-cap-usd 300 --by ... --reason ...
  python -m scripts.billing_admin set-control --provider groq:openai/gpt-oss-20b --monthly-cap-usd 100 ...
  ```

  The cap is checked against this month's ledger under a lock.
- **Kill switch:** `set-control --provider '*' --kill-switch on` stops every
  paid provider at once; a provider name stops just that one. Refused calls
  answer 503 `PROVIDER_DISABLED`.
- **Fail closed:** any of the following refuses the paid call:
  - no company context;
  - no configured price;
  - the accounting database unreachable;
  - an unknown host.
- **Configuration file:** `billing_cost_policy` holds the credit value, 70%
  margin target, 15% default safety margin, warning thresholds, AI
  concurrency and size limits, reservation timeout, top-ups (off) and
  fallback policy (none).

## 6. Counting rules

- **Products:** each product that isn't deleted (`deleted_at IS NULL`).
  - Deleted products free their place.
  - There is no separate "archived" state.
  - Duplicates: the import merges rows by normalised name and barcode into
    one product, and each product row counts once.
  - Creating a product and importing products check the limit under a
    per-company lock, in the same transaction as the insert, so concurrent
    requests can't pass it.
- **Reports:** one successful export (CSV, JSON or PDF) of the sales report.
  - Viewing report pages doesn't count.
  - The company data export (Settings, then Export data) doesn't count: it
    is a data-portability right.
  - The count resets each billing period.
  - A retry with the same `Idempotency-Key` header, or the same person
    repeating the same export within 10 minutes, counts once.
  - A failed export is given back.
  - Counting runs on the billing service's connection; companies can read
    but not write it.
- **Team seats:** members who haven't been removed, plus invitations still
  open.
  - Re-inviting an address doesn't take a second seat.
  - Inviting needs a free seat (402 otherwise).
  - Accepting checks the seat again inside `auth_join_tenant()` under a
    per-company lock, so two acceptances can't take the last seat.
  - Removing a member frees the seat.
  - After a downgrade, nobody is removed: no one new can join until the
    company is under its new limit.
- **Competitors:** no count. Discovery, enrichment and monitoring stop when
  Data Credits run out. The retired packages keep their old competitor caps.

## 7. Trials

- Start and end are exact UTC timestamps (`billing_trials.started_at`,
  `ends_at`). Access ends at `ends_at` to the second, not at the end of a
  day. Changing a device's clock or restarting the app changes nothing.
- Trial length per plan: Standard 14 days, Plus 14, Pro 7. A Custom
  contract sets its own (0-90 days).
- Eligibility, checked on the server (`store.trial_eligibility`):
  - one trial per company, ever;
  - one per person across all their companies;
  - not on top of a plan or subscription;
  - only on a self-serve plan with a trial.
- **A company with no plan has no access** (`UNASSIGNED_PLAN_ACCESS=none`;
  "default" exists only for single-company installs). That applies, for
  example, when a person's second company was refused a trial.
- Sign-up starts the Plus trial (`TRIAL_PLAN_KEY`). A company that never had
  a trial can start one on the plan it picks: `POST /billing/trial`, or the
  Billing page's "Start free trial".
- **Trial budgets are bounded:** a trial gets a tenth of a month's Data and
  AI Credits (`usage_plan_limits.trial_limit_value`), never a full paid
  month. Other allowances are the plan's.
- **At expiry** the status becomes `expired`:
  - every plan-gated endpoint answers 402;
  - no paid call can run;
  - the Billing page shows how to choose a plan.
- **Before expiry:** a "trial ends in N days" alert from 3 days before, in
  the app and in the optional email summary.
- **No silent conversion:**
  - A trial never turns into a paid plan on its own; paying needs a Stripe
    Checkout the customer completes.
  - A company that subscribes during its trial keeps the remaining days, and
    Stripe cancels the subscription at the trial's end if no payment method
    was collected (`missing_payment_method: cancel`).
  - Only Stripe's verified webhook activates a paid plan; a redirect back
    from Checkout doesn't.

## 8. Custom plans

```bash
python -m scripts.billing_admin set-contract --tenant <id> --contract-ref C-2026-001 \
  --by "<approver>" --reason "Signed order form" --monthly-price 900 --refresh daily --support priority \
  --data-source pos --limit tracked_products=2000 --limit data_credits=9000 --limit ai_credits=9000 \
  --limit monthly_reports=200 --limit team_seats=75 [--trial-days 14] [--period-months 12]
```

- The command writes the following and puts the company on `custom`:
  - `tenant_custom_contracts`: price, trial, data sources, refresh
    frequency, support level;
  - `tenant_entitlement_overrides`: the company's own limits, replacing the
    plan's;
  - one `entitlement_audit_log` row per change, recording approver,
    contract reference, reason, old and new values, and time.
- A limit not listed in the contract stays at Custom's finite default
  (Pro-level budgets), never unlimited.
- The audit log is append-only; a trigger refuses UPDATE and DELETE.
- **Customers can't do any of this.** There is no API for prices, overrides,
  contracts or controls. The application's database role can read its own
  contract and overrides and can't write them. `/billing/checkout` and
  `/billing/trial` refuse `custom`.

## 9. The ledger and database

New tables, all with row-level security: each company reads only its own
rows, and every write goes through the billing service's trusted connection.

| Table | What it holds |
|---|---|
| `usage_ledger` | one row per billable call |
| `usage_ledger_adjustments` | append-only corrections |
| `tenant_credit_balances` | reserved, consumed and cost per company, budget and period |
| `metered_request_keys` | idempotent report counting |
| `provider_cost_schedules` | prices |
| `provider_spend_controls` | caps and kill switches |
| `billing_cost_policy` | one row of policy settings |
| `tenant_custom_contracts` | Custom contract terms |
| `tenant_entitlement_overrides` | per-company limits from contracts |
| `entitlement_audit_log` | who approved each change, and why |

Each `usage_ledger` row records:
- company, subscription, plan and its status, budget, period;
- operation id and type, usage class;
- provider and operation, idempotency key (unique per company);
- status, estimated and measured units;
- estimated and actual USD, reserved and consumed credits;
- provider request id, error code, actor, timestamps.

Rules on the ledger:
- A trigger lets a row move forward only: reserved, then settled once; only
  a pending row can then be reconciled.
- Money columns never change after settlement.
- Rows are deleted only when their company is deleted.
- **No secrets:** URLs, query strings, headers and provider responses are
  never stored. The provider is a fixed name from the host map.

## 10. API

| Endpoint | |
|---|---|
| `GET /billing/plans` | catalog with prices, limits, trial limits, entitlements |
| `GET /billing/subscription` | plan, status, period, limits, usage, both credit budgets (limit, consumed, reserved, remaining, %, warning, reset date), whether a trial is available |
| `GET /billing/usage-history` | recent metered operations: credits and status only |
| `POST /billing/trial` | start the one trial (billing roles only) |
| checkout, portal, change plan, cancel, resume, webhook | unchanged |

Customer errors carry a reason code and a plain message, never provider names,
prices or costs:
- **402:** `BUDGET_EXHAUSTED`, `SUBSCRIPTION_INACTIVE`, `QUOTA_EXHAUSTED`,
  `CAPACITY_REACHED`
- **409:** `DUPLICATE_REQUEST`
- **429:** `CONCURRENCY_LIMIT`
- **413:** `REQUEST_TOO_LARGE`
- **503:** `COST_NOT_CONFIGURED`, `PROVIDER_DISABLED`, `PROVIDER_CAP_REACHED`,
  `ACCOUNTING_UNAVAILABLE`

## 11. Payments

- **Stripe integration** (existing): hosted Checkout and portal,
  signature-verified webhooks with a 5-minute replay window, events stored
  once by id, subscriptions re-read from Stripe, idempotent checkout.
- **Plan changes:**
  - upgrades apply at once and invoice the difference;
  - downgrades apply at period end;
  - cancelling keeps access to period end.
- **Not implemented:** refunds (no partial-period refunds; cancellation takes
  effect at period end) and paid top-ups.
- **Production billing stays off** until `STRIPE_SECRET_KEY` and
  `STRIPE_WEBHOOK_SECRET` are set and `scripts/stripe_sync_catalog.py` has
  created the prices. Without them, payment actions answer 503
  `payments_not_configured`.
- **Tests make no live charges:** Stripe is faked in every test.

## 12. Deployment

1. Deploy the backend. The migration runs with the other migrations
   (`scripts/apply_migrations.py`, as the schema-owning role).
2. Set `UNASSIGNED_PLAN_ACCESS=none` (already in `render.yaml`).
3. Check that every company has a plan: companies with no
   `tenant_plan_assignments` row lose access.

   ```sql
   SELECT c.tenant_id, c.business_name FROM companies c
   LEFT JOIN tenant_plan_assignments a USING (tenant_id) WHERE a.tenant_id IS NULL;
   ```

   Assign them with `scripts/assign_plan.py`.
4. Record confirmed prices for every paid provider in use (section 4). Until
   then those features answer "not set up".
5. Optionally set provider caps (section 5).
6. Run `scripts/stripe_sync_catalog.py` to sync the renamed plans to Stripe.
   Product names change; existing prices keep resolving.
7. Deploy the frontend.

## 13. Rollback

1. Deploy the previous application version first. The new code needs the
   new tables, and the old code calls the old 3-argument
   `auth_join_tenant()`.
2. Run `backend/src/infrastructure/database/rollback/20261020000000_keel_subscriptions_and_credits.down.sql`
   as the schema-owning role. It restores the previous plan names, limits,
   trial lengths and `auth_join_tenant()`, and removes the new limits.
3. The ledger, balances, adjustments and audit log are **kept**: they are
   the record of real spending. Export them before dropping them by hand
   if that record is no longer needed.

## 14. Remaining risks and open items

- **No paid provider has a confirmed price yet,** so Groq, Google, Apify,
  Hugging Face, Cloudflare and the search APIs are refused until section 4 is
  done. This is deliberate.
- **The planning figures are assumptions** until replaced with real data:
  processing fee, split, trial fraction and infrastructure allocation.
- **The `UNASSIGNED_PLAN_ACCESS=none` default can lock out existing
  companies** that have no plan row. Run the query in step 3 of section 12
  before deploying.
- **Who changed what in operator commands is self-declared** (`--by`), and
  the person needs database credentials. There's no approval workflow with
  separate identities yet.
- **Price-monitoring scrapes** run by the Scrapy workers (`ScrapeCreators`,
  Digi-Key) are not yet credit-metered; they keep the existing per-product
  cost gate (`cost_ledger.py`). Bringing them under Data Credits is a
  follow-up.
- **Not yet built:**
  - **Claude provider:** the AI ledger already prices cache-read and
    cache-write tokens per model, but connecting Claude (through the
    official Anthropic SDK) is a separate change.
  - **Fallback model policy:** only "none" exists.
- **Credit-threshold alerts and the usage history** are computed when
  viewed; there is no push notification beyond the existing email summary.
- `auth_tokens` (invitation and reset token hashes) has no row-level
  security. This predates this change.
