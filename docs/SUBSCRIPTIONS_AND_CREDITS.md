# KEEL subscriptions, Data Credits and AI Credits

## Combined local integration template (not published)

`standard-plans-lean-search-retired-v1` combines the reviewed lean capacities with numeric
web-search retirement. It is a new immutable template identity; historical catalog
versions, customer snapshots, published prices and Credit allocations are unchanged.
Its installation/publication is restricted to disposable tests in this preparation.

## Web search commercial retirement

`standard-plans-launch-v3` retires `web_searches` from new Standard templates
and Custom selections. Web search remains part of authorized parent features;
it is not a separate Boolean or numeric product. Historical feature rows,
catalog versions, assignments, trial snapshots, quotes and analyses remain
readable. Plan transition comparison ignores only this retired numeric key;
all other missing/changed rights keep their existing checks. A legacy Custom
revision may carry its original search quantity unchanged, but cannot increase
it or introduce it into a new selection. The old localized label remains for
historical quote rendering.
Original revision retries retain their idempotent result even after a later
revision removes the allowance; changed retry payloads still conflict.

Forward migration `20261129000000_retire_web_search_commercial_allowance.sql`
closes restricted SQL authoring bypasses. Setup installs the new immutable
catalog version without synchronizing existing commercial rows. Apply the
migration and run the existing catalog installer together before exposing new
authoring; restart API/workers to load the new source. No normal database is
migrated by tests. Existing published plan limits are retained as history and
ignored commercially, including on renewal; new template plans omit the key.

Pricing Studio retains legacy search coverage as Data-Credit-funded, with zero
additional provider exposure. Credit pools and their actual provider operations
must never be added a second time. Free public requests do not create monetary
Credit charges. Paid calls still reserve/settle against Provider Accounting;
the mixed-source workflow admission now requires subscription access rather
than a positive Data Credit balance before provider selection.

Outbound data-provider requests use `market_scraper/search_safety.py` for atomic
tenant and shared provider capacity limits, concurrent-request leases and
in-flight duplicate suppression. Redis failure refuses new outbound work.
This guard is local to outbound data work: failure of its Redis admission does
not add a global dependency to billing reads, Marketing generation, or AI Credit
settlement. A full Redis service outage can still affect their existing queue,
authentication, or cache dependencies independently of this search guard.
Cached discovery responses keep their existing TTL; cache hits make no external
call. The guard adds no new automatic retry. Web provider fallback is bounded
to four unique entries; reference-price transient retries are bounded to two
and accounted per attempt. Search/discovery transports cap configurable timeout
at 30 seconds. Leases expire after 300 seconds to cover existing 180-second
data-actor transports and recover dead workers.

These are operational limits, common to all plans, never commercial allowances.
Defaults: tenant 30/minute, 500/day, concurrency 3; provider 60/minute, 5000/day,
concurrency 8. They are conservative launch safeguards, not a representation of
any vendor's contractual quota. Operators must tune downward for actual vendor
limits. Provider budgets are shared across credentials and hosts mapped to the
same provider, so credential rotation cannot bypass them. Minute/day counters
use fixed windows beginning on first admission, not billing periods.

Redis `keel:search:safety:requests:<sha256(provider)>:<UTC-day-number>` hashes
record operation/free-or-priced/succeeded-or-failed counts for seven days.
Tenant window/inflight keys contain a tenant digest. Structured `search_request`
logs provide provider/operation/outcome only, without queries, URLs or keys.
Telemetry and capacity counters are not provider invoice or customer Credit
ledgers. Existing crawler-specific robots/network/throttle and scheduled-job
deduplication rules continue to apply independently.

How KEEL's plans, usage budgets and billing work, what is enforced where,
what still needs real prices before it can run, and how to deploy or roll
back. The backend is the source of truth for every limit: the screens only
display what `/billing/*` returns.


## 1. Plans

### Lean future-customer catalog (owner-approved design, not a normal-DB publication)

`backend/config/billing/standard_plan_catalog.json`, version
`standard-plans-lean-v1`, supplies these future-assignment/template terms:

| Capacity | Standard | Plus | Pro |
|---|---:|---:|---:|
| Document storage (GB) | 1 | 5 | 20 |
| Extraction (MB per billing period) | 50 | 200 | 750 |
| Sentiment records per billing period | 3,000 | 12,000 | 40,000 |
| Active connected sources | 1 | 3 | 8 |
| Tracked competitors | 5 | 15 | 40 |

Storage retains 1 GB = 1024 MB, 1 MB = 1,048,576 bytes. Extraction retains
1 MB = 1024 KB and charges ceil(input bytes / 1024) KB. Counts are not
multiplied by the purchased 1/3/6-month period: the metered allowance applies
once per provider billing period; storage, sources and competitors are live
capacity. New provider-confirmed trials inherit these capacities; their
existing separate trial Credit allowances and 14/14/7-day durations do not change.
Prices, other feature limits, AI/Data Credits, RAG tokens and economic policies
are unchanged. Fresh installations bootstrap the new definitions. Installing
the version on an initialized database only adds templates; it does not update
existing published plan definitions or assignments.

Existing assignments and trials keep their captured catalog snapshot on renewal
and same-plan period updates. Custom contracts/overrides, quote revisions and
saved Pricing Studio analyses are not rewritten. Explicit cross-plan changes
compare the actual snapshot with proposed rights. Mixed gains/losses require
support review before any provider write; pure losses retain the existing
end-of-period schedule. Unlimited historical competitors are a real right, not
equivalent to the new finite allowance. Over-limit data is never removed.

Generated images check their actual byte size under the tenant storage lock
before upload; display rounding is not used for enforcement. Manual and
automatic competitor registration take the same capacity lock before row
locks. Price-matching evidence commits before its separate capacity-checked
tracking phase; evidence alone does not start tracking. Image providers,
formats and retry policy are unchanged.

**Publication gate:** code/template installation is not authorization to publish
new selling terms. Before an approved rollout, back up and verify recovery,
inventory legacy snapshots and pending/accepted Checkout/Custom offers, and
drain or honor them. Checkout reservations freeze price/trial terms but do not
freeze the complete entitlement vector. Do not change live definitions while
an earlier accepted Checkout could activate against different allowances.
Use existing audited owner plan-feature authoring in one transaction only after
this gate and separate owner authorization. Do not run a bulk tenant update or
rewrite an applied migration. No new schema migration is needed here.

Pricing Studio must be recalibrated separately: analyze the new version with
documented expected/stress utilization and measured worker/DB/storage demand;
keep external-provider Credit costs separate from internal infrastructure,
support and operations. Lower caps are not measured savings. Preserve old
analyses and do not automatically change internal allocations or prices.

#### Final review evidence and integration dependencies

Review base: `870b6e9a9864ba27b53f292676b10c2cd08ce357`. The scope is
26 source/catalog/test/documentation files; there are no new migrations,
pricing-policy changes, provider-rate changes or Credit allocation changes.

- The earlier combined regression recorded 854 passes and one 10-second
  Chrome timeout waiting for Pricing Studio's initial "Billing setup" heading
  in `test_browser_pricing_studio[owner-en-legacy]`. The unchanged Studio and
  catalog browser rerun passed all 10 cases. An exact tracked-source export of
  the review base, using its original catalog in a fresh disposable database,
  also passed that Chrome case. The timeout's cause was not established; it
  must not be represented as a proven product defect or a proven base defect.
  No timeout or assertion was relaxed.
- `test_subscription_exposes_versioned_established_rights_without_changing_existing_fields`
  fails at `assert app_conn.closed and system_conn.closed` on both the exact
  base and the candidate. Its fixture already has an assigned active plan, so
  the handler does not acquire the privileged trial-eligibility connection.
  The fake `system_conn` therefore remains unused/unclosed. The subscription
  handler and this legacy test are unchanged; the known assertion is recorded,
  not suppressed or counted as a pass.
- Final candidate regression: 855 passed, including all 16 Chrome cases; the
  only failure was that same independently reproduced base assertion. The
  complete frontend suite passed 297 tests. Fresh disposable migration/repeat
  execution and restricted-role checks verified 166 migrations and 130 FORCE
  RLS tables. No normal database or published catalog was changed.
- Historical snapshot/trial renewal, selected-plan provider-confirmed trials
  across 1/3/6-month periods, existing-trial Checkout cutoff preservation,
  pending Checkout idempotency, Custom offers and saved analyses are covered
  by the native billing regression. Pending Checkout publication safety still
  requires the separate drain/honor gate above; reservations do not freeze
  the complete entitlement vector.

The branch is stacked on the billing/RAG prerequisites through the review base,
not independently ready to target `main` with its whole ancestry. Integrate
those prerequisites, coordinate with `fix/deprecate-web-search-entitlement`,
then reconcile this lean catalog without reintroducing numeric `web_searches`.
Preserve the deprecation branch's migration
`20261129000000_retire_web_search_commercial_allowance.sql` and its narrowly
scoped legacy-rights comparison exception. Recheck the combined catalog and
regressions before any separately approved publication. Private review exports,
credentials, screenshots and test evidence stay under ignored `.dev/` paths.

### Historical reference

The table and earlier rollout notes below describe historical terms, not the
new template or current published pricing authority. Read live prices from
`billing_plan_prices` and existing customer rights from assignment snapshots.

| | Standard | Plus | Pro | Custom |
|---|---:|---:|---:|---|
| Plan key (database, Stripe) | `starter` | `growth` | `enterprise` | `custom` |
| Monthly price | $55 | $140 | $350 | quoted |
| Free trial | 14 days | 14 days | 7 days | no new cardless trial |
| Products | 100 | 250 | 500 | contract |
| Reports per month | 5 | 20 | 60 | contract (default 60) |
| Team seats | 5 | 20 | 50 | contract (default 60) |
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

### Configured trial length versus remaining trial time

`usage_plans.trial_days` is the backend source for new trial duration and plan
cards. `POST /billing/trial` reserves the selected plan's canonical duration
and opens provider Checkout; it grants no local access. Verified provider
reconciliation records UTC `billing_trials.started_at` and `ends_at` together
with the subscription, assignment and entitlement snapshot. The restricted
`billing_setup_trial(..., true)` command refuses cardless activation.
Signup/email verification and new-workspace
creation grant no commercial plan. During onboarding, the customer explicitly
selects a plan and starts its eligible trial through `POST /billing/trial`.
Selecting a different paid plan later does not issue another trial or change an
existing cutoff.

Fresh Checkout sends `CheckoutIntent.trial_duration_days` and requires a reusable
recurring payment method. Stripe translates this to subscription-mode Checkout,
`payment_method_collection=always`, `subscription_data.trial_period_days` and
missing-payment-method cancellation. KEEL verifies normalized method readiness,
authorized tenant/customer, frozen plan/term/price, duration and subscription
identity before activation. Other providers must supply equivalent evidence.
No frontend field controls these terms.

For already-issued trials, Checkout sends the existing cutoff through the provider-neutral
`CheckoutIntent.trial_end`; the Stripe adapter translates it to
`subscription_data.trial_end`, never a new duration. An issued
14-day trial opened in Checkout a minute after trial activation has slightly less than 14
days remaining. Stripe controls its hosted wording. Changing to 14 days from
Checkout or rounding the cutoff up would extend the issued trial and is not the
approved policy. Zero-day plans issue no new trial; a previously granted trial
remains governed by its original cutoff. Checkout's existing minimum remaining
window is separate from plan duration.

For customers with an issued trial, onboarding plan selection and the KEEL
review put the existing UTC expiry first. The review hides the selected plan's
default trial duration, and plan cards do not offer a new trial. Customers
without an issued trial can still see the catalog's default duration. Choosing
Pro does not replace a previously issued Plus trial with Pro's shorter default.
No rounded countdown replaces configured days. Already frozen Checkout
requests, subscriptions, credits and billing boundaries are unchanged.

Pending Checkout retries reuse the original frozen request and provider session
under the tenant's Checkout lock. Continue may also resume an already authorized
trial Checkout for the same plan, term and promotion; Start trial cannot silently
resume a paid Checkout. A reservation with no session and no frozen request has
never submitted Checkout and can safely release its trial claim when changing
selection or after a setup failure. Verified expired/missing sessions can retry;
completed sessions wait for reconciliation. Unknown provider outcomes retain
their reservation and original idempotency key. Incompatible submitted terms
require an explicit close action, with provider closure verified before release.

### Provider customer identity and CREATE recovery

Customer creation has its own durable `billing_customer_operations` record,
separate from Checkout attempts and commercial eligibility. One operation owns
one stable provider key and an immutable adapter-encoded payload, namespace and
safe replay window. Contact/name changes never rebuild that CREATE request.
Mapped customers are verified and reused; replacing a tenant's mapping is refused.
Any future contact update must be a separate operation, not another CREATE.

Unknown outcomes first try positive provider recovery, then may replay the same
frozen request within the provider's guaranteed window. An expired replay window
or an unmapped legacy attempt without its original payload requires reconciliation;
a negative search is not proof that CREATE failed. Only definitive rejection
allows another logical operation. Customer coordination grants no trial, plan,
entitlements or Credits. Verified payment reconciliation remains the authority.

Migration `20261128000000_customer_creation_operations.sql` adds the FORCE RLS
ledger with scoped setup-role permissions. It preserves existing mappings and
commercial records and quarantines unmapped historical attempts instead of
inventing their original request parameters. Apply through a verified backup and
the normal migration procedure after isolated upgrade/restricted-role checks.

## 2. Data Credits and AI Credits

Platform Owners manage accounting schedules at
`/admin/billing?tab=provider-accounting`. The owner-only
`GET` / `PUT /platform/billing/provider-accounting` API delegates saves to
`billing.admin.set_price`, the same authority as `scripts.billing_admin set-price`.
Migration `20261117000000_owner_provider_accounting.sql` supplies its narrow,
owner-checked database persistence; runtime roles receive no table-write grant.
Apply it only through the documented backed-up migration procedure before rollout.

These schedules are `provider_cost_schedules`, separate from Custom Plan
`billing_custom_cost_rates`. Missing prices remain unavailable; intentional zero
prices stay visible. The form preserves decimal strings, requires provenance,
verification date and justification, and confirms changes before saving. A blank
safety margin retains the existing default-policy behavior. Updates retain the
existing mutable current-schedule semantics with full before/after audit records;
they do not rewrite historical usage, balances or Custom Plan rate versions.

Focused verification:
`dev.ps1 test --suite backend --pytest-args tests/billing/test_provider_accounting_db.py -q`.
For disposable browser plus synthetic Data-accounting acceptance, run
`.dev/venv/Scripts/python.exe tools/dev/provider_accounting_browser.py`.
This reuses the isolated runner, preserves application services, excludes paid
provider credentials, and retains test databases/evidence under `.dev/evidence/tests/`.

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

**What a credit buys** depends on the provider prices configured
(section 4). Groq lists `openai/gpt-oss-20b` at $0.075 input / $0.30
output per million tokens (its Supported Models page, checked
2026-10-17), so a typical 2,000-token assistant answer costs about
$0.0003, which is 0.03 AI Credits. Re-check the price against Groq's
invoice; a new price is recorded the same way (section 4).

## 4. Provider prices: what must be set before paid operations run

Prices are never invented. Seeded at $0:
- the free public services above;
- the local llama-server;
- the keyless Pollinations image endpoint.

Installation migrations now include the approved `ai-provider-pricing-v1`
catalog: Groq `openai/gpt-oss-20b`, USD 0.075/million input tokens and
USD 0.30/million output tokens (approved 2026-10-28). Fresh databases receive
these rates automatically; existing configured rates remain unchanged.
See [catalog installation, preservation and future approvals](DATABASE.md#approved-ai-provider-pricing-catalog).
Customer Credits, credit conversion policy and subscription prices are separate.

Other paid providers/models below remain unpriced until approved costs are
configured. **Missing costs refuse calls with `COST_NOT_CONFIGURED`; they are
never assumed to be zero:**

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

No Platform Owner credentials or manual `set-price` command are required on
normal startup for the approved default model. Credentials, entitlements,
spending controls and credit accounting must still be configured independently.
Cached input tokens are charged at the input price unless a `cache_read_token`
price is recorded too.

Intentional operator changes use the existing authenticated owner command
below, with an active Platform Owner UUID and `--owner-token-stdin`. Supply
the real owner token securely on stdin, never as a command argument or in Git.
These are administrative changes, not startup steps; substitute independently
approved values rather than running placeholders:

```bash
cd backend   # DATABASE_URL = the schema-owning role
python -m scripts.billing_admin set-price --budget data --provider google_places --operation text_search \
  --unit request --usd <confirmed> --source "<approved source>" --verified-on <approval-date> \
  --by "<PLATFORM_OWNER_USER_UUID>" --owner-token-stdin --reason "<approved reason>"
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
- Trial length per plan: Standard 14 days, Plus 14, Pro 7. New cardless Custom
  trial activation is refused; historical Custom trials remain unchanged.
  Paid manually negotiated Custom contracts remain supported.
- Eligibility, checked on the server (`store.trial_eligibility`):
  - one trial per company, ever;
  - one per person across all their companies;
  - not on top of a plan or subscription;
  - only on a self-serve plan with a trial.
- **A company with no plan has no access** (`UNASSIGNED_PLAN_ACCESS=none`;
  "default" exists only for single-company installs). That applies, for
  example, when a person's second company was refused a trial.
- Verified signup creates the identity, company and owner membership, with no
  trial or plan assignment. New workspaces follow the same policy. An eligible
  company explicitly opens its selected plan's trial Checkout using `POST /billing/trial`:
  Standard (`starter`) 14 days, Plus (`growth`) 14 days, Pro (`enterprise`) 7 days
  in the current catalog. Zero-day plans offer Checkout without a new trial.
- Pending reservations consume no trial eligibility and grant no entitlements.
  Person/workspace locks and unique pending indexes serialize competing attempts.
  Cancelled/verified-expired Checkout releases the reservation; unknown provider
  outcomes remain blocked for reconciliation rather than risking a second trial.
  Only verified provider-backed activation consumes eligibility, atomically with
  subscription/assignment/snapshot reconciliation. Duplicate and out-of-order
  events re-read current provider state and preserve the original activation.
- `/billing/subscription.trialEligiblePlanIds` reports eligible catalog plans;
  `trialAvailable` is their aggregate flag. Neither depends on `TRIAL_PLAN_KEY`.
  Unassigned companies return no current plan identity. Onboarding saves the
  selected plan and completion requires matching, access-granting rights.
- Dashboard routes enforce durable onboarding completion and an assigned
  `active`/`trialing` plan on the API as well as in the React navigation gate.
  Existing tenant-role and feature/module checks still apply.
- Existing issued trials retain their exact plan, cutoff and entitlement snapshot.
  "Continue with current trial" acknowledges those existing rights; it does not
  activate a new trial or bypass identity/tenant or onboarding-completion checks.
- **Trial budgets are bounded:** a trial gets a tenth of a month's Data and
  AI Credits (`usage_plan_limits.trial_limit_value`), never a full paid
  month. Other allowances are the plan's.
- **At expiry** the status becomes `expired`:
  - every plan-gated endpoint answers 402;
  - no paid call can run;
  - the Billing page shows how to choose a plan.
- **Before expiry:** a "trial ends in N days" alert from 3 days before, in
  the app and in the optional email summary.
- **Provider-confirmed billing:**
  - Fresh trials require completed provider Checkout and reusable-payment-method
    confirmation. At the cutoff, recurring billing follows the terms accepted
    in Checkout; paid access requires verified invoice settlement.
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
  --limit monthly_reports=200 --limit team_seats=75 [--period-months 12]
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
