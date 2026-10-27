# PR CI remediation checkpoint

Baseline: `158d61102f8a3fa702c2142734c8f44231b94795`, branch `integration/keel-full-migration`.

## Original failures and fixes

### Python dependency audit

Twisted is a required transitive dependency of Scrapy, used by the market collectors and workers. Removing it would break the existing runtime. Both application manifests now explicitly pin **Twisted 26.10.0rc1**. This opts in to that one security release; it does not enable prereleases globally or replace the production dependency set with a test overlay.

PyPI still reports 26.4.0 as the latest stable release on 2026-10-27. The maintainer's published candidate is the first patched version. Replace the pin in both manifests with the stable release after the same audit and compatibility checks.

Primary references:

- [PyPI release and Python/platform compatibility](https://pypi.org/project/Twisted/26.10.0rc1/)
- [Maintainer release notes](https://github.com/twisted/twisted/releases/tag/twisted-26.10.0rc1)
- [Telnet buffer advisory: CVE-2026-115778](https://github.com/twisted/twisted/security/advisories/GHSA-cwm5-jh59-mwxr)
- [IMAP SEARCH advisory: CVE-2026-115774](https://github.com/twisted/twisted/security/advisories/GHSA-2qrf-pqgx-qh9v)
- [XML stream advisory: CVE-2026-115775](https://github.com/twisted/twisted/security/advisories/GHSA-3476-c5c2-fr73)
- [IRC buffer advisory: CVE-2026-115776](https://github.com/twisted/twisted/security/advisories/GHSA-53xc-49m8-p798)
- [HTTP header advisory: CVE-2026-115877](https://github.com/twisted/twisted/security/advisories/GHSA-q7qq-6mhp-9rc4)
- [Previously ignored IMAP wildcard advisory: CVE-2026-106454](https://github.com/twisted/twisted/security/advisories/GHSA-8pqf-f4m5-798g)

The unsuppressed audit reproduced six advisories on 26.4.0 and none on 26.10.0rc1. The workflow's obsolete Twisted and Pillow exceptions are removed; all audit findings fail CI. Pillow 13 was already required by both manifests before this task. `pip check` now checks the installed dependency graph in both backend jobs.

Local compatibility used an isolated temporary overlay, leaving existing virtual environments unchanged: Scrapy 2.19.0, Twisted 26.10.0rc1, Pillow 13.0.0, Brotli 1.2.1 and setuptools 84.2.1. The last three updated older *local test* packages, not repository policy. Audit of all 171 available local packages found zero advisories; `pip check` passed. This Windows/Python 3.12 environment is not the Ubuntu/Python 3.11 GitHub runner. Hosted installation, resolution and audit must still execute.

### Browser fixture onboarding 409

The original fixture configured company settings/catalog data, then called completion without saving the durable onboarding choices. The API correctly returned `409` with `Complete your profile and choose a plan first.`

The fixture now reads saved progress and actual subscription rights, saves each missing `/onboarding/state` step with its current revision, acknowledges the existing signup trial/active plan, then completes onboarding through `/settings/company/onboarding/complete`. It never creates Checkout, resets a trial, grants a paid plan or bypasses verification. Expired/unassigned rights fail with an actionable error. Repeat runs retain completed state, products, competitor prices and the original trial. API startup waits for database/Redis readiness rather than liveness alone.

### Route security test contract

The broad suite exposed a stale assumption that every non-public route uses a customer JWT. Shopify delivery intake authenticates the exact body with provider HMAC. Its UUID path placeholder previously produced 422 before handler execution. The test now explicitly distinguishes that route and asserts missing/invalid signatures are 401 before any database lookup, even with a forged JWT; absent server configuration is 503. No application authorization changed. Native signed-provider, tenant isolation and RLS tests remain enabled.

## Verification checkpoint

- Initial new regressions: 17 passed, no failures/skips; includes real Scrapy local-HTTP crawling through the asyncio reactor.
- Final CI/security/worker/native billing/RLS selection: 719 passed, no failures/skips.
- Initial browser smoke: 27/27 screens each in English desktop, Arabic mobile and English dark mobile; actual login, tenant data/API reads and Platform Owner denial. The existing smoke harness separately stubs recommendation-dialog responses for two presentation assertions; these are not AI inference acceptance.
- Frontend serial retry: 201 passed, no failures/skips. Earlier parallel run had two native allocation failures, not assertion failures. Lint and Vite 8.3.5 production build passed.
- Fresh database: 137 baseline migrations passed; restricted `ceopro_app` is neither superuser nor BYPASSRLS; 120 tables have FORCE RLS.
- Broader diagnostic run: 1,258 passed and five failed before its diagnostic stop. Three stale security-contract failures were corrected and passed in the 719-test run.

## Authorized invoice compatibility fix

Root cause: migration `20261110000100_provider_order_post_receipts.sql` introduced explicit `rounding_adjustment` and exact equality, but existing import, structured-invoice and quick-sale writers still omitted that field. Its `numeric(12,4)` type also truncated valid residuals: `877.1350 - 912.3500 * 0.9614 = 0.00171000`, stored as `0.0017`, fails the equality.

The owner explicitly authorized the narrow persistence fix and a necessary forward-only precision migration. New migration `20261111000000_invoice_rounding_adjustment_precision.sql` removes only the numeric typmod. Unconstrained exact NUMERIC retains historical Decimal scales (and therefore source ownership hashes), unlike forcing every old value to scale 8. The unchanged equality and quantity-relative bound still constrain all values. No constraint, grant, RLS policy, default or NOT NULL restriction was removed.

The three existing canonical writers now store the exact residual. Paid totals, tax, currency, payment status, document validation, stock semantics, idempotency and transaction boundaries retain their existing calculations/authorities.

An additional incompatibility needed a separate owner decision: `0.4 * 12.3456` rounds to paid total `4.9382`; residual `-0.00004` exceeds the existing `0.4 * 0.00005` bound. The owner expressly approved deriving the stored effective paid unit price (`12.3455`) only where the original representation exceeds that bound. Original source price remains in staging/product evidence; paid total does not change. The exact regression expectation was updated to this approved representation, with strict assertions for original product price, paid total, residual and database rejection of invalid adjustments.

Verification:

- **115 passed, zero failed/skipped:** new invoice residual/rollback/replay tests plus existing extraction promotion, quick-sale, structured imports, provider-order and Credit accounting regressions.
- Both batch and forced row fallback preserve exactly one invoice/item/sale on retry.
- PAID and UNPAID structured invoices preserve tax, currency and payment status; only PAID produces a sale; replay preserves one posting/audit event.
- Existing constraint still rejects an excessive residual or a residual inconsistent with the paid total.
- **138 fresh migrations**, **137-to-138 upgrade**, **no-op repeat** passed on dedicated disposable databases. The upgrade preserved the JSON serialization of 202 existing invoice items, exact constraint text, RLS and grants.
- No previously applied migration was edited. No Stripe, subscription, entitlement or Credit business implementation changed.

## Accessibility follow-up

The original `#73758b` small description text on `#f1efff` failed axe color contrast in English desktop and dark mobile. Only the description color in `Billing.css` and `BillingCatalogOriginal.css` changes to the existing banner violet `#5553a9`. Wording, typography, layout, background, responsiveness and navigation remain unchanged. Two numerical WCAG AA regression checks were added.

Final frontend checks: **203 passed, zero failed/skipped**, lint passed, Vite 8.3.5 production build passed. Updated real-browser/axe results and final backend diagnostic results are being recorded before final handoff.

## Local commits

- `2e4fb20ea05c7637a48b39f16a7c7d04a2eccecd`: dependency, onboarding fixture and route-security test contract corrections.
- Invoice and accessibility changes are recorded in subsequent commits on the same integration branch.

## Evidence and preservation

Private local evidence: `%TEMP%\KEEL\CiRepair-20261027`. Logs, JUnit, browser reports and runtime secrets are not committed. The isolated API/frontend use ports 8030/5210 and database `keel_ci_repair_20261027`, on verified disposable infrastructure. No real merchant or Stripe calls were needed.

Protected `backend/.env.example` SHA256: `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28`. It is excluded from every commit. No original Node/React source, protected runtime, remote branch, main branch or production resource is modified.
