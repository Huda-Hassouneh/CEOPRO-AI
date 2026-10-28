# Platform Billing: original UI and Python pricing parity

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
English/Arabic values and the protected local configuration hashes. No protected
`.env.example`, AI models, customer financial records or original source files
were edited. Account-B identity isolation remains implemented at baseline f856317;
no subscription ownership repair or new authentication rewrite was performed.

Commit and local rollout evidence follows after actual completion. Until rollout,
the normal development API remains stopped on the baseline migration state.
