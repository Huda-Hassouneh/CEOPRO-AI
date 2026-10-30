# Platform Billing: original UI and Python pricing parity

## Standard Plan Pricing Studio — 2026-10-31

Base: `d326f732910769c4636762617730bd9056a07aed`. Standard Plans currently
publish USD catalog/Stripe prices. The Studio preserves those contracts and
offers **JOD economic analysis**, using only an explicit, versioned USD/JOD
assumption. No commercial values, utilization ratios or allocations are seeded.

### Architecture and authorities

`BillingCatalogPage` adds Pricing Studio immediately after Plans and an
`Analyze Pricing` action with the plan preselected. `PricingStudio.jsx` renders
server results and versioned policy controls in English/Arabic. The owner-only
`/platform/billing/pricing-studio` API delegates to `billing/plan_studio.py`
(use cases), `plan_analysis.py` (pure model), and the restricted
`billing_plan_studio` SQL capability. The ordinary app login is used; no admin
socket or additional runtime table grants are introduced.

`pricing_math.py` contains the small shared Decimal operations for usage cost,
margin floors and monetary rounding. Custom Plan calculation uses these same
operations with unchanged policy, order and output. The Studio reuses its
feature/unit/monitoring cost normalization with zero Custom commercial fee and
margin; it does not inherit Custom automatic-review or checkout policy.

| Input | Authoritative source | Interpretation |
|---|---|---|
| Plan configuration | `usage_plans`, `usage_plan_limits`, `usage_plan_entitlements`, `usage_features` | Current Standard Plan contract, including explicit zero/unbounded and reset semantics |
| Published price/interval | `billing_plan_prices`, catalog metadata | Display/comparison only; original currency retained |
| AI/Data Credit value | `billing_cost_policy.credit_usd_value` | Provider-cost exposure per Credit, not revenue or measured spend |
| Additional external unit cost | `provider_cost_schedules` | Provider Accounting authority, verified source/date/ID/update evidence |
| Feature/unit conversion | Approved `billing_custom_cost_bindings` | Reused mapping and multipliers; **Custom quotation rate amounts are not used as actual provider costs** |
| Observed provider spend | `usage_ledger.plan_key` and final `actual_cost_usd` | Rolling 30-day aggregate, using historical plan attribution; pending estimates separate |
| Utilization, allocations, FX, commercial objectives | New immutable owner policy | Configured assumptions, never presented as observed data |

Credit-funded features must be explicitly classified as covered by AI/Data
Credits, preventing duplicate feature and Credit costs. Internal coverage is an
explicit owner assumption. Additional external features require bound, current,
verified Provider Accounting rates. A missing or stale quotation price cannot
silently substitute for a missing actual provider rate. Reconciled ledger costs
already contain the final amount; reconciliation adjustments are not added again.

### Policy, formulas and evidence

Migration `20261118000000_standard_plan_pricing_studio.sql` introduces only
`billing_plan_analysis_policies` and `billing_plan_analyses`, both FORCE RLS,
append-only, accessed through an owner-checked capability. Policies are immutable
versions with effective dates, actor and justification. Analyses freeze plan,
policy, provider evidence, Credit value, FX provenance, observed spend and results
with a SHA-256 source hash. The history API returns the frozen snapshot.

Owner-configured fields include target/minimum margins, risk buffer,
expected/stress utilization, monthly per-tenant infrastructure/support/operations,
payment ratio/fixed fee, annual discount and allowance cycles, whole-cent upward
rounding, FX rate/source/version, rate-age threshold, cost coverage, unbounded
usage estimates and optional tier-gap threshold. No draft or future policy is
silently selected: latest effective date/version wins, or an explicit effective
version can be selected. Existing approved binding versions are referenced.

For each scenario, Credit exposure is `allocation × credit USD value ×
utilization × USD/JOD`. Additional feature cost uses the shared calculator's
normalized units times actual provider unit price, operational multiplier,
variability reserve, FX and utilization. Micro-costs remain Decimal through
aggregation. Internal allocations are added once. Observed spend is shown
separately and never added to modeled exposure.

Let `E` and `S` be expected/stress costs, `b` risk buffer, `f` processing ratio,
`k` fixed fee per charge, `m` minimum margin and `t` target margin:

- Break-even: `(E + k) / (1 - f)`.
- Safe minimum: `((S × (1+b)) + k) / (1 - f - m)`.
- Target: `((E × (1+b)) + k) / (1 - f - t)`.
- Recommended: upward-round `max(safe minimum, target)` to the configured increment.
- Current contribution: `price × (1-f) - k - E`; margin is contribution / price.
- Stress margin substitutes `S` for `E`. Nonpositive revenue has no margin ratio.

Existing multi-month sum allowances are charged once per assigned billing
period in this analysis; recurring allocations scale with months. This follows
the current `usage.get_plan`/Credit budget period rather than assuming monthly
resets that the runtime does not implement. Annual pricing is **hypothetical**:
recurring cost scales by 12, allowance exposure by the explicitly configured
annual cycle count, with one fixed payment fee. The discounted annual candidate
is `recommended monthly × 12 × (1-annual discount)`, rounded upward. A candidate
below the annual safe floor is flagged, never silently published or corrected.

Missing policy, coverage, finite usage, important bound rates or verification
produces `INCOMPLETE_DATA`, labeled known subtotals and **no recommendation**.
Unsafe current margins/annual discounts produce warnings. Tier comparisons flag
non-increasing prices, configured weak gaps, cost growth exceeding price growth,
and lower-tier allowance/module dominance. They make no willingness-to-pay claim.
Provider schedule inventory separately labels missing/unverified/stale rows;
unreferenced providers do not masquerade as costs used in the model. A SAFE label
means only safe under the configured model, not a guarantee of realized profit.

### Safety and verification boundary

Analysis and simulation write only analysis evidence. Policy creation writes
policy/audit evidence. Neither calls Stripe, changes plan prices/allowances,
creates subscriptions, grants rights, settles Credits, or reprices subscribers.
Native tests fingerprint catalog, price, subscription, payment, assignment,
contract, balance and usage tables before/after simulation. Provider price-change
tests verify a new result changes while the earlier snapshot and Custom quotation
rate remain unchanged. Restricted app sockets, direct SQL denial and FORCE RLS
are verified. Browser acceptance uses the production Billing page/API/database
with an explicitly injected synthetic identity, not production login acceptance.

Normal application migrations, real provider operations and production economic
configuration are outside this implementation. Rollout requires the documented
verified backup procedure and deliberate owner policy/mapping configuration.
Future work may add provider-mix forecasts, per-plan/per-feature utilization,
market/value evidence and publication workflows. None is invented here; no PAYG
or automatic subscriber repricing is introduced.

Final verification:

- `dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_credits_integration_db.py src/ai/tests/test_usage_integration_db.py -q`: **425 passed, zero skips**, including Billing, Custom Plan self-service, Provider Accounting, Credits, allowances, owner/RLS and browser checks. Evidence: `.dev/evidence/tests/9b1ecb8ccf77/`.
- Final browser run with app stylesheet foundations: **4 passed** (English desktop, Arabic/RTL mobile, tenant denial, incomplete-cost warning). Evidence: `.dev/evidence/tests/334311bc267d/`; captures under `.dev/evidence/standard-pricing-studio/`.
- `dev.ps1 test --suite frontend`: **242 passed, zero skips**, ESLint and production build passed. Evidence: `.dev/evidence/standard-pricing-studio/frontend-final.log`.
- Migrations: **153**, repeat/idempotency check passed; restricted password login and **122 FORCE RLS tables** verified. Existing Starlette/httpx deprecation and font/dynamic-import build warnings remain.
- Original Node parity: **42/42 calculator** and **10/10 Custom validation/review/payment vectors** passed after extraction. Evidence under `standard-pricing-studio/calculator-parity/` and `custom-decision-parity/`.
- Read-only normal DB check confirms Studio function and both new tables are absent: `standard-pricing-studio/normal-schema-check.json`. No normal migration, real Stripe/provider action, customer record edit, service restart, push or merge occurred.

Changed files:

- Backend: `backend/src/ai/billing/{plan_analysis.py,plan_studio.py,pricing_math.py,custom_plan_pricing.py}` and `backend/src/ai/routers/platform.py`.
- Migration: `backend/src/infrastructure/database/migrations/20261118000000_standard_plan_pricing_studio.sql`.
- Backend tests: `backend/tests/billing/{test_plan_studio.py,test_plan_studio_browser.py}`.
- UI: `frontend/src/features/platform/{PricingStudio.jsx,pricingStudio.js,pricingStudio.css,platformBillingApi.js}` and `frontend/src/features/billing/pages/BillingCatalogPage.jsx`.
- Translations: `frontend/src/assets/locales/{en.json,ar.json}`.
- Frontend tests: `frontend/tests/pricingStudio.test.mjs` and `frontend/tests/browser/pricing-studio.{html,jsx,mjs}`.
- Documentation: this existing report. The two unrelated untracked documents are untouched.

## Customer self-service Custom plans — 2026-10-31

The customer currency decision now authorizes JOD commercial quotes with USD
Stripe settlement. This supersedes the earlier USD-commercial-only limitation
for new self-service quotes; existing USD offers retain their original terms.
Standard plan prices and actual provider/Credit accounting are unchanged.

### Source-to-source behavior map

Legacy source root: `D:\freeup space\New folder\Keel\root` (read-only).
`custom-plan-configurator.service.ts` supplies validation, the three review
rules, price-visible review responses and automatic checkout intent.
`custom-plan-policy.service.ts` supplies fallback/override precedence.
`custom-plan-payment-currency.service.ts` converts frozen quote currency to USD.
`BillingCustomPlanPage.jsx` supplies the 350 ms preview refresh and CTA behavior.

| Concern | Previous Python behavior | New Python/React behavior |
|---|---|---|
| Selection | Canonical feature quantities and three premium modules | Same enforceable rights; legacy aliases and baseline features classified below |
| Quantities | Nonnegative integer, step 1 | Versioned minimum/step and per-feature automatic maximum |
| Calculation | Owner-only USD preview | Existing Decimal calculator, JOD commercial calculation, frozen USD conversion |
| Review | Every request required review | Strict `>` quota/price thresholds; unverified rate warnings require review |
| Preview | No customer price | Price stays visible for calculable review cases; private economics omitted |
| Checkout | Owner approval then customer acceptance | Eligible frozen preview can be confirmed directly; existing durable Checkout machinery reused |
| Reviewed requests | Owner calculation/revision/approval/acceptance | Preserved, including rate evidence checks and immutable revisions |
| Existing subscription | Current/recoverable subscriptions block new Checkout | Preserved; legacy automatic replacement is deliberately not copied |
| Provider truth | Signed webhook reconciliation | Preserved; no redirect/session-only activation |

### Commercial policy and evidence

`billing_custom_pricing_policies.self_service_policy` is an additive versioned
JSON configuration. Stored commercial values override fallback values. Old
explicit USD fee/rounding amounts are converted to JOD when no new commercial
override is supplied; they are never relabeled JOD. The existing margin and
shared-infrastructure allocation remain policy inputs. No production policy or
provider rate is seeded or activated by the migration.

Supported commercial keys are `targetGrossMargin`, `fixedPlatformFee`,
`roundingIncrement`, `maxAutomaticMonthlyPrice`, `maxAutomaticQuotaPerFeature`,
`featureLimits`, `fxRate`, `fxSourceCurrency`, `fxTargetCurrency`, `fxSource`,
`fxVersion`, and `estimatedOtherCost`. Currency is JOD; the FX pair is USD/JOD.
A non-fallback FX rate requires explicit provenance/version. The approved legacy
fallback is margin .35, fee JOD25, increment JOD1, monthly automatic maximum
JOD2500, feature maximum 500000, USD/JOD .709. Production cost mappings still
fail closed when missing, including an explicit mapping for zero-cost features.

Each version-2 quote revision freezes configuration, policy identity, cost-rate
identity/provenance, calculation, ordered review reasons, commercial JOD total,
monthly JOD amount, period/discount, USD payment total, and FX provenance/version.
Only the restricted billing-setup capability can freeze/confirm an automatic
preview. It cannot write paid subscriptions, payments, entitlements or Credits.
The app role receives only public quantity constraints through a separate read
function. Public endpoints never return the private pricing snapshot.

Review conditions match the original function: quantity greater than the
resolved maximum (`QUOTA_ABOVE_AUTOMATIC_LIMIT:<code>`), monthly JOD price
greater than its maximum (`PRICE_ABOVE_AUTOMATIC_LIMIT`), or calculator warnings
(`UNVERIFIED_VENDOR_RATE`, including infrastructure warnings). Equality passes.
Minimum/step/dependency errors are validation failures, not approval rules.

The existing 14-day quote window is retained rather than copying Node's 30-day
automatic quote expiry. Confirmation never reprices a preview or extends its
window. Current rate-verification guards may require refresh/review when a
referenced rate ceases to be eligible. USD invoice verification uses the frozen
USD amount; the contract retains its JOD commercial price. Paid custom price
presentation reads the settled quote attempt, not the generic catalog template.

### Builder capability classification

| Legacy capability | Classification / current representation |
|---|---|
| market_intelligence, demand_prediction, competitor_management | ALREADY_SUPPORTED premium modules |
| sentiment_analysis, rag_assistant, document_extraction, marketing_image_generation | ALREADY_SUPPORTED quantity allowances |
| tracked_competitors, tracked_products, connected_data_sources, document_storage_mb | ALREADY_SUPPORTED capacity allowances |
| report_generation | RENAMED_CURRENT_EQUIVALENT: monthly_reports |
| team_members | RENAMED_CURRENT_EQUIVALENT: team_seats |
| market_perception | RENAMED_CURRENT_EQUIVALENT: bundled under market_intelligence; no new independent grant |
| dashboard_analytics, product_management, data_integration | NO_LONGER_VALID_IN_CURRENT_PRODUCT as independently purchasable toggles; baseline platform capabilities |
| inventory_intelligence, business_recommendations, system_alerts | LEGACY_BEHAVIOR_NOT_PORTABLE as independent billing rights; no established Python purchasable contract |
| ai_pricing recommendation quota | LEGACY_BEHAVIOR_NOT_PORTABLE; no equivalent independently enforced recommendation allowance |

No alias is silently promoted into a new entitlement. Python-only AI Credits,
Data Credits and web-search allowances remain selectable and separately enforced.
All five legacy monitoring cadences are represented; configured monthly runs
use the original 30/60/120/720/4 values. This is pricing/contract evidence, not a
claim of external monitoring acceptance.

### Verification and rollout boundary

The existing pure calculator comparison passed 42/42 original Node vectors.
`tools/dev/verify_custom_self_service.py` additionally executes the original Node
decision and payment-conversion functions in memory: 10/10 vectors passed for
validation, money, strict boundaries, overrides, ordered reasons and eligibility.
No legacy files, dependencies, caches, databases or services are modified.

The new native tests exercise automatic confirmation, no session-only rights,
signed paid activation, mismatched payment rejection, separate zero Credit
allowances, restricted capabilities and durable Checkout conflicts. Browser
acceptance uses the production builder and real disposable API/database with
an explicitly injected synthetic identity; it is not a real payment acceptance.

The final retry check exposed an uncommitted quote-specific attempt alongside a
durable shared reservation. The Custom checkout use case now commits that
identity before provider work. A native restricted-socket test injects an
uncertain provider response and verifies the same shared/quote attempt IDs,
frozen parameters and provider idempotency key on retry. The builder retains its
request key for the same preview. Its quantity field no longer re-emits an
unchanged value on blur, which previously cleared the preview during a click.

Human approval and customer acceptance preserve the complete version-2 pricing
snapshot, JOD commercial amount, USD payment amount and FX evidence byte-for-byte
as JSON values. Tests explicitly check that creation, approval, acceptance and
Checkout completion without verified payment create no paid plan assignment.
Only a verified, correctly correlated USD invoice activates the selected rights.

Browser checks cover automatic eligibility in English and Arabic/RTL, quota
review, price review, unverified-rate review, and existing-subscription blocking.
Both automatic cases also verify the three-month JOD97.20/USD137.09 totals and
retry blocker presentation with an unchanged confirmation payload. Browser
Checkout refusals are labeled transport doubles; actual durable retry behavior
is tested separately through the production API and restricted database roles.

Migration added: `20261115000000_custom_plan_self_service.sql`. A read-only
normal-database check confirms both its new capability and policy column are
absent (`.dev/evidence/custom-self-service/normal-schema-check.json`). No normal
database rollout, customer financial record edit, real Stripe request, purchase,
service restart, push or merge was performed by this task.

Final backend command:
`dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_credits_integration_db.py src/ai/tests/test_usage_integration_db.py -q`
passed **396 tests, zero skips**, with the existing Starlette/httpx deprecation
warning. Evidence: `.dev/evidence/tests/d470a88fda17/backend.log` and `run.json`.
The runner verified 152 migrations, restricted password login and 120 FORCE RLS
tables. The focused retry/review/browser run passed 26 tests; evidence:
`.dev/evidence/tests/d22f8259767a/backend.log`. All six browser cases are also
included in the final 396-test run.

Frontend command `dev.ps1 test --suite frontend` passed **237 tests, zero skips**,
ESLint and the production Vite build. Evidence:
`.dev/evidence/custom-self-service/frontend-final.log`. Existing font-resolution
and mixed static/dynamic import build warnings remain. Calculator and decision
parity evidence is under `.dev/evidence/custom-self-service/calculator-parity/`
and `decision-parity/` respectively. `git diff --check` passed.

### Changed-file inventory

- Backend pricing/checkout: `backend/src/ai/billing/{self_service.py,custom_offers.py,custom_plan_pricing_service.py,service.py,store.py,webhooks.py}`.
- HTTP boundaries: `backend/src/ai/routers/{billing.py,platform.py}`.
- Forward migration: `backend/src/infrastructure/database/migrations/20261115000000_custom_plan_self_service.sql`.
- Backend tests: `backend/tests/billing/{test_custom_self_service.py,test_custom_self_service_browser.py,test_custom_checkout_contract.py,test_custom_offers.py}`.
- Customer UI: `frontend/src/features/billing/{api/customOffersApi.js,components/CustomPlanQuantityField.jsx,pages/CustomPlanBuilderPage.jsx,pages/CustomPlanQuotePage.jsx}`.
- Owner presentation: `frontend/src/features/platform/{billingLegacyContracts.js,PlatformBillingAdminPython.jsx}`.
- Translations: `frontend/src/assets/locales/{en.json,ar.json}`.
- Frontend tests: `frontend/tests/{billingLegacyContracts.test.mjs,customOffersApi.test.mjs,browser/custom-self-service.html,browser/custom-self-service.jsx,browser/custom-self-service.mjs}`.
- Read-only legacy comparison tools: `tools/dev/{verify_custom_self_service.py,legacy_custom_self_service_reference.mjs}`.
- Documentation: this existing report.

Run `dev.ps1 test --suite backend --pytest-args tests/billing -q` and
`dev.ps1 test --suite frontend`. The browser acceptance file requires Chrome.
Normal/customer databases are not migrated by these tests. Applying the new
forward migration to a populated runtime requires the normal verified backup
and rollout procedure; no such rollout or Stripe purchase is part of this work.

## Delivery boundary

Date: 2026-10-28. Implementation checkout: `E:\KEEL START\CEOPRO-AI`.
Branch: `integration/keel-full-migration`; recovered baseline:
`f856317d3d9e84e0eab451b77e264c6f5a99a3ae`.

This restores the original owner presentation and fixes its Python adapters and
restricted persistence boundaries. It does **not** authorize production prices,
provider costs, contract exceptions or unverified Stripe promotions. Full legacy
parity is not claimed while the policy-gated controls below remain unavailable.

The interrupted large command had not applied either intended test edit. Existing
changes were preserved. The missing tests were added as separate, reviewable edits.
No source, dependency, cache or database writes were made in the legacy repository.
Private screenshots, logs, backups and synthetic IDs remain under ignored `.dev/`.

## Source and component map

Original frontend: `D:\freeup space\New folder\Keel\root\frontend`.
Original backend: `D:\freeup space\New folder\Keel\root\backend`.
The enclosing reference Git HEAD is `76c687763e11980ce7ab531daf5595889ca9ef3a`;
its pre-existing working changes mean the actual hashed source files, rather than
that commit alone, are the visual/behavior reference.

Paths below are relative to `frontend/src/` in both repositories unless noted.

| Original source | Route / purpose | Integrated component / action |
|---|---|---|
| `features/platform-admin/routes.jsx`, `layout/PlatformAdminLayout.jsx`, `styles/PlatformAdmin.css` | `/admin/billing`, owner shell and navigation | Original shell retained; `/platform/billing` redirects here with query preserved |
| `features/platform-admin/pages/BillingManagementPage.jsx` | Owner billing entry | Retained wrapper around original `BillingCatalogPage` |
| `features/billing/pages/BillingCatalogPage.jsx` | Seven tabs, plans, promotion/feature forms, link modals, subscriptions and contracts | Same original component; Python adapters, specific policy guards, scoped theme |
| `features/billing/components/CustomPlanQuoteManager.jsx` | Policy form, four-step quote builder, approval, vendor rates | Original workflow restored; draft/activation separation, frozen economics, approval reference and in-place evidence |
| `features/billing/components/InfrastructureRateCards.jsx` | Infrastructure schedules | Original component retained; versioned Python binding and valid multiplier step |
| `features/billing/components/BillingOptionsEditor.jsx` | Billing-term fields | Retained; unsupported Custom terms remain visible/read-only under USD/monthly contract |
| `features/billing/styles/Billing.css`, `PlansSubscription.css` | Original spacing, tables and responsive layout | Existing `BillingCatalogOriginal.css`, `BillingCatalogPlansOriginal.css` retained |
| `styles/globals.css`, `shared/components/ui/Badge.jsx` | Original primitives/tokens/badges | Owner-only `BillingLegacyTheme.css` and `OriginalBillingBadge.jsx`; customer/global theme unchanged |
| `features/billing/api/billingApi.js` | Node contracts | Existing Python adapter plus `features/platform/billingLegacyContracts.js`; no Node runtime |

The original billing page has no separate KPI/chart dashboard. Its actual seven-tab
catalog is preserved rather than adding invented dashboard panels. The original
subscription table is read-only. Existing shared Modal keyboard/focus handling and
its mobile scrolling fix are retained.

## Complete tab/control inventory and Python mapping

All owner endpoints below use the existing Platform Owner dependency. A Tenant
Owner is not a Platform Owner. No tenant or platform membership is granted by UI
visibility. API paths are relative to `/platform/billing` unless stated.

| Original action | Python mapping / persistence | Status and evidence |
|---|---|---|
| Open Plans / inspect prices, billing periods and trial days | `GET /admin-views/plans`; `amount` mapped to original price fields | VERIFIED WORKING: real browser reads + frontend contract tests |
| Enable/disable plan for future purchases | `PATCH /plans/{key}/status`; guarded catalog command + audit | VERIFIED WORKING: restricted HTTP/database regression; browser mutation unrun |
| Create/edit plan commercial terms | Existing price-version infrastructure; no approved cohort/values/transition command for original arbitrary form | POLICY BLOCKED: form retained, Save disabled with CATALOG-001 explanation |
| Inspect Custom contracts / features | `GET /admin-views/contracts` | VERIFIED WORKING: browser tab; populated live contracts not created in this run |
| Toggle a Custom contract independently of billing | No safe arbitrary status override | POLICY BLOCKED: control retained/disabled; precedence/replacement rules required |
| Load/search original Custom quote table | `GET /custom-quotes` plus restricted detail for frozen evidence | VERIFIED WORKING: browser and role regression; queue currently bounded to first 100 |
| Four-step quote create / edit / submit | Existing quote/revision/submit endpoints; stable creation/submit identity | VERIFIED WORKING: browser create; revision/idempotency backend tests; no payment |
| Estimate usage / edit economic inputs | Server allowance/pricing evidence; client does not set monetary authority | VERIFIED WORKING: estimated usage and economics read-only; adapter drops client economics |
| Calculate quote | `POST /custom-quotes/{id}/calculate`; existing Decimal engine and frozen snapshot | VERIFIED WORKING: real browser/database + 42 Node vectors; missing pricing is an error, not fake success |
| Approve frozen quote | `POST /custom-quotes/{id}/approve`; revision + reference required | VERIFIED WORKING: browser/database/audit; editable price override prohibited |
| Reject quote | Existing reject endpoint and guarded lifecycle | VERIFIED WORKING: backend lifecycle regressions; browser reject unrun |
| Review quote evidence/history | `GET /custom-quotes/{id}`; guarded detail capability | VERIFIED WORKING: browser snapshot/revisions/audit; restricted tenant denial |
| Original Send action | Approval already publishes in customer portal; read verifies approved state | DELIBERATE DIFFERENCE: truthful in-app availability label; no invented email delivery |
| Quote acceptance / Checkout / activation | Existing customer quote acceptance, Checkout and signed webhook authority | Backend regressions PASS; fresh real Stripe payment UNRUN in this task |
| Save pricing policy | `POST /custom-plan-pricing/policies`; new immutable draft version | VERIFIED WORKING: original Save + confirm dialog + persistence audit |
| Activate policy | Separate `/policies/{id}/activate`, explicit evidence and draft bindings | VERIFIED WORKING: real browser and database; Save alone never activates |
| Original automatic-approval limits / arbitrary FX / extra-cost overrides | No approved automatic thresholds/production rates | POLICY BLOCKED: visible read-only fields and precise explanation; no fabricated defaults |
| Vendor Rate create/edit/history | Versioned `/custom-plan-pricing/vendor-rates`, cost rates and bindings | VERIFIED WORKING: browser create/refresh + service/database tests; edits supersede, not rewrite history |
| Infrastructure create/edit/history | `/custom-plan-pricing/infrastructure-rates` and versioned bindings | Backend/API regressions PASS; tab rendered; browser mutation UNRUN |
| Promotion list/create/edit draft/refresh | `/promotions` GET/POST/PATCH; owner-validated SQL command + audit | VERIFIED WORKING: restricted database and real browser draft workflow |
| Link promotion to plan | PATCH draft eligibility; active terms immutable | VERIFIED WORKING: adapter/backend contracts; browser link mutation UNRUN |
| Activate/deactivate promotion | Existing TEST-only provider verification, then setup-role finalization | VERIFIED WORKING offline: matching economics, mismatch refusal, draft retained, one activation audit, retry idempotency; real provider UNRUN |
| Inspect redemption usage | Existing promotion/customer redemption authority | Backend promotion regressions PASS; no paid redemption created in browser |
| Inspect/edit canonical feature labels | Existing feature catalog GET/PATCH | Existing contracts retained; browser reads; metadata mutation and refresh verified in the real browser |
| Create/delete feature or change unit/type/reset/aggregation | Requires executable enforcement contract | POLICY BLOCKED under ENT-001; original controls visible, unsafe controls disabled |
| Link/unlink supported feature / change plan quota | `PATCH /plans/{key}/features`; guarded command, catalog/version triggers, audit | VERIFIED WORKING: restricted HTTP/DB tests; original control save/reload plus database/audit verified in the browser |
| View global subscriptions and scheduled changes | `GET /admin-views/subscriptions`; snake-case adapter | VERIFIED WORKING: browser tab and explicit trial/date mapping tests; no inferred paid status/period |
| Tab navigation, form cancel/confirm, locale and responsive states | Original components and translations | Browser English/Arabic, desktop/mobile checks; matched reference screenshots |

## Pricing and approved compatibility differences

The actual original `src/modules/subscription/service/custom-plan-pricing.service.ts`
executes in memory using its original Prisma Decimal implementation. The reference
calculator SHA256 is recorded in `pricing-final/node.json`; the runner never starts
the legacy backend or writes to its source tree.

**42/42 differential vectors PASS.** Coverage includes all supported canonical
features/modules, provider/infrastructure cost multiplication, competitor cadence,
shared-cost allocation, margin limits, ratio floors, fee/rounding boundaries,
missing rates and unsupported FX. Monetary fields match exactly; raw nonmonetary
numbers are compared at Prisma Decimal's 20 significant digits. Null/undefined
omission is normalized, not monetary differences.

One additive evidence difference is explicit: Python includes
`infrastructureBreakdown.featureCode`, copied from the canonical input; Node omits
it. The runner checks the identity. This is an internal representation extension,
not a separately approved commercial policy or a financial tolerance.

Other deliberate differences preserve approved newer Python authorities:

- CUSTOM-002: USD/monthly, verified versioned rates, server-derived quantities,
  frozen snapshots and explicit review. No copied Node production cost defaults,
  arbitrary client margin override or unspecified instant-approval thresholds.
- CATALOG-001/ENT-001: future catalog changes do not silently reprice or regrant
  existing paid contracts; arbitrary canonical semantics require enforcement work.
- PROMO-001: saving is draft-only. Provider coupon/code economics must match before
  publication; initial-subscription, once-only scope remains authoritative.
- CUSTOM-001: accepting a quote does not grant paid rights; signed provider evidence
  remains necessary. Exceptional contract overlap/replacement remains gated.
- The original UI label for the subscriptions tab is itself untranslated in the
  reference. This inherited difference is not presented as completed localization.

## Restricted persistence and migration review

Two forward-only migrations; no applied migration was rewritten:

1. `20261114000000_owner_quote_review_evidence.sql`: extends the existing owner-only
   read function with current revision, frozen calculation, history and attempts.
2. `20261114000100_owner_promotion_persistence.sql`: narrow promotion and catalog
   commands, owner/actor/workspace checks and transaction-coupled audit.

All SECURITY DEFINER functions have a fixed `pg_catalog,public,pg_temp` search path,
PUBLIC execution revoked and explicit role grants. Mutating owner commands share
the existing authority advisory lock before checking membership. Draft/read and
catalog operations use `ceopro_app`; provider publication/deactivation finalization
requires `ceopro_billing_setup`. No runtime table grants, administrator DSN, paid
activation or credit-writing authority was added. Existing webhook/accounting
identities and FORCE RLS remain unchanged.

## Reproducible verification and evidence

Private evidence root: `.dev/evidence/platform-billing-parity/`.

| Check | Result / evidence |
|---|---|
| Broader billing, entitlement, credits, usage and RLS | PASS: 369 tests, zero skips; `.dev/evidence/tests/f17641b5dcb4/backend.log` |
| Final owner command/detail/admin contracts | PASS: 29 tests; `.dev/evidence/tests/6a2ab749ca53/owner-regressions.log` |
| Frontend suite | PASS: 229 tests, zero skips; `frontend-final/tests.log` |
| Lint / production build | PASS; `frontend-final/lint.log`, `build.log`; 229 tests rerun after final component/CSS corrections |
| Native developer tooling | PASS: 49 tests run by `dev.ps1 test` |
| Fresh/repeat migrations | PASS: 146 fresh; repeat no-op; restricted password login; 120 FORCE RLS tables |
| Development-data upgrade rehearsal | PASS: private backup restored, 139 table fingerprints match; 144 to 146; repeat no-op; application records unchanged |
| Original Node pricing | PASS: 42/42; `pricing-final/differential.json` |
| Real browser, synthetic owner/customer | PASS: 14 workflow groups; `.dev/evidence/tests/6a2ab749ca53/owner-browser.json` and `persistence.json`; no Stripe key loaded |
| Visual comparison | Matched original-source fixtures, Chrome, same locale/theme/viewport/data; final results below |
| Stripe external payment/provider promotion | UNRUN deliberately; offline doubles are not payment acceptance |

Commands from the E: root:

```powershell
.\dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_billing_effective_rights.py src/ai/tests/test_credits_integration_db.py src/ai/tests/test_usage_integration_db.py src/ai/tests/test_rls_integration_db.py -q
.\.dev\venv\Scripts\python.exe tools/dev/verify_owner_billing.py
.\.dev\venv\Scripts\python.exe tools/dev/verify_legacy_billing.py --legacy-backend 'D:\freeup space\New folder\Keel\root\backend' --output .dev/evidence/platform-billing-parity/pricing-final
```

`verify_owner_billing.py` creates a disposable database, no-provider runtime and
synthetic owner/customer through real authentication. Its bootstrap is guarded by
the test database namespace. It never promotes a normal-development user.
Visual reference commands are in `frontend/tests/browser/owner-billing-parity.mjs`;
set `KEEL_ORIGINAL_FRONTEND`, `E2E_OUTPUT` and `CHROMIUM_PATH` explicitly. Temporary
reference copies are made only in E: and removed in `finally`.

## Resume/acceptance checkpoint

The interrupted promotion regressions are complete. Successful and rejected
provider verification use offline doubles; the real restricted setup identity
persists publication only after verification, and repeat activation creates one
audit entry. A synthetic activation fixture teardown conflict and an obsolete
unit-service signature were corrected without relaxing assertions.

Real browser evidence: 14 groups, 28 tab/locale/viewport captures plus quote review;
policy draft, vendor rate, explicit activation, four-step quote, frozen approval,
in-place evidence, promotion draft create/edit/reload, label edit, quota save and
Tenant Owner denial all passed. Independent SQL verifies promotion stays draft at
11%, has no provider IDs, quota persists at five, and audit records exist. There
are zero Stripe customer mappings, Checkout attempts or subscriptions in this run.

Visual evidence: `visual-delivery/` contains 88 original/current pairs (176 PNGs).
There are 27 byte-identical pairs. This is **not pixel-perfect parity**. Original
fonts, page widths, baseline table composition and restored toolbar heights match.
For English desktop light tab states, Plans, Promotions and Features differ by
approximately 0.011%, 0.014% and 0.012% of pixels respectively; Plan Features,
Custom Plans and Subscriptions match exactly. Remaining minor shadow/rasterization
differences are noncritical and retained in evidence. The quote-policy section is
longer because explicit approval evidence and version history are now required.
Plan/feature guard notes, inactive promotion default, supported-unit/binding fields
and read-only Custom economics are deliberate, documented contract differences.

Dialogs, loading, empty and error states were rendered from both source variants.
The original has no distinct dark palette: owner billing retains its original
palette under both themes; the rest of KEEL keeps its existing theme. Arabic font
families and RTL direction match. Reference fixtures are presentation simulations,
not real Node-provider E2E. The main real-browser harness uses the real Python API.

The comparison found and corrected inherited glass styling (rounded pills,
shadows, dialog blur, toolbar padding), the vendor multiplier HTML step and a new
quote-editor uncontrolled-input warning. The focused `visual-quote-regression/`
rerun covers four English/Arabic desktop/mobile pairs and reports no current-UI
console errors. The reference harness's missing favicon is harmless and recorded.

Preservation: `preservation.json` verifies all 84 reference file hashes, all prior
English/Arabic values and the protected local configuration hashes before the separately approved inbox-port change below. No protected
`.env.example`, AI models, customer financial records or original source files
were edited. Account-B identity isolation remains implemented at baseline f856317;
no subscription ownership repair or new authentication rewrite was performed.

## Local commit and completed E: rollout

Implementation commit: `dd9bd4d37062ae3284e530456e64a5b58be5ae49`.
The final report-only follow-up commit is discoverable with
`git log -1 --format=%H -- docs/PLATFORM_BILLING_LEGACY_PARITY_REPORT.md`.
Application processes were started from the implementation commit; the follow-up
changes this report only and requires no application restart.

- PASS: recoverable private database/roles/configuration backup; restored copy
  tested before applying the two forward permissions migrations.
- PASS: actual development database upgraded 144 to 146; repeat no-op. All existing
  application-table fingerprints matched before and after migration, including
  customer subscriptions, financial evidence and credits. No account was repaired.
- PASS: normal restricted password identities, pgvector and 120 FORCE RLS tables.
- PASS: FastAPI readiness, exact CORS, frontend-to-API proxy and all eight worker
  initialization/heartbeat checks: forecast, images, connectors, prices, analysis,
  discovery, enrichment and maintenance. PostgreSQL, Redis, MinIO and Mailpit healthy.
- PASS: existing local-only TEST Clock preflight reports ready; read-only provider
  validation only. No Checkout, payment, subscription or coupon was created.
- PASS: normal-runtime fresh anonymous browser reaches login from the owner route;
  API/proxy readiness 200, protected owner APIs 401, no browser exceptions.
- Authenticated owner mutations against normal customer data: UNRUN intentionally.
  They passed in the disposable real-API browser environment instead. An existing
  normal Platform Owner is present; no normal-development account was promoted.

Startup initially failed because Windows reserved TCP 57943-58042 after reboot,
including the old Mailpit inbox port 58025. The owner explicitly approved changing
**only** private `.dev/config.json` `ports.inbox` to **58043**. The owned ephemeral
Mailpit container was recreated. SMTP remains 51025; all other configuration values,
secrets and application ports are preserved; the original config is backed up.
No Windows port reservation or system setting was changed. Evidence:
`approved-port-change.json`, `development-migration.json`, `development-rollout.log`,
`development-status.log` and `development-browser.json` under the evidence root.

The equivalent inactive promotion-dialog rerun is in
`visual-promotion-equivalent/`: four English/Arabic desktop/mobile pairs, identical
status/dates, original form geometry retained, no current console errors. Its
screenshots are not byte-identical; minor shadow differences remain. This is
additional evidence rather than a claim that every visual state is identical.

## Owner acceptance and remaining boundaries

**Ready for owner acceptance of the restored, approved workflows. Full legacy
parity is not declared.** Policy-gated original actions remain visibly unavailable
as listed above. No known critical integration defect remains in the tested scope.

1. Open `http://127.0.0.1:5173/platform/billing` (redirects to `/admin/billing`).
2. Sign in using the existing Platform Owner; select **KEEL Platform** if workspace
   selection is offered. A tenant's Owner role alone cannot access this page.
3. Inspect all seven original tabs; begin with Custom Quotas for policy versions,
   vendor/infrastructure rates, quotes and in-place review. Inspect existing data
   read-only first. Synthetic test inputs are not approved production pricing.
4. Review the documented blocked controls and explicit approval/payment boundaries.
   No real-provider promotion publication or new payment is part of this acceptance.

Useful local commands from `E:\KEEL START\CEOPRO-AI`:

```powershell
.\dev.ps1 up --mode full
.\dev.ps1 status
.\dev.ps1 restart
```

Frontend: `http://127.0.0.1:5173`; API: `http://127.0.0.1:8000`;
Mailpit: `http://127.0.0.1:58043`.

Remaining limits: exact pixel parity is unproven; small shadow differences remain;
commercial catalog transitions, canonical semantic changes, arbitrary contract
status overrides and automatic approval thresholds need the stated decisions.
Infrastructure edit/supersession, plan availability, quote rejection and promotion
linking have API/native coverage but not new browser-mutation coverage here.
Populated real-customer contracts/subscriptions and live provider promotion/payment
journeys were not exercised in this run. This is not production certification.

All changes are local on `integration/keel-full-migration`. No push, main merge,
history rewrite, production deployment or original-repository modification occurred.
