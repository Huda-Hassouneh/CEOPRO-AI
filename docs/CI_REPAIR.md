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

## Verification scope

Verification uses the existing Windows/Python 3.12 environment with an isolated dependency overlay, disposable PostgreSQL 17 databases, dedicated Redis and verified local MinIO. No real Stripe or merchant operation is needed. Frontend verification uses the existing independently installed lockfile dependencies (Vite 8.3.5) in the path-with-spaces fresh checkout, with the exact four authorized stylesheet changes and new contrast test copied from this integration source.

Initial focused regressions passed 17 tests. The final CI/security/worker/native billing/RLS selection passed 719 tests with zero failures/skips. These selections overlap the full suite and must not be added together as unique coverage. Earlier stopped diagnostic runs exposed the stale fixtures and configuration mismatches documented below; their logs are retained, not counted as successful full runs.

## CI configuration and remaining stale fixture corrections

The broader suite exposed CI setup defects previously masked by the dependency audit:

- Disposable-only provider-promotion tests correctly rejected `keel_ci`/`localhost`. The backend job now creates `keel_billing_test_ci`, connects through explicit `127.0.0.1`, and gives workers `ceopro_app` credentials. Migration/test administration retains its existing separate admin role. No production guard was weakened and no global automatic-promotion opt-in was enabled.
- Billing and notification composition require an explicit public frontend origin. Both CI API environments now declare `FRONTEND_BASE_URL=http://localhost:5173`, matching the browser job. No Stripe credentials or payment bypass is introduced.
- The Shopify OAuth fixture set its own `FRONTEND_URL` but inherited CI's different `FRONTEND_BASE_URL`. The existing shared origin validator correctly rejected disagreement. The fixture now clears inherited aliases before setting its test origin; all six OAuth tests pass, preserving HMAC, tenant binding and single-use state assertions. No OAuth implementation or URL safety check changed.
- The unexpected-error regression used product ID `p1` after the API adopted UUID validation, so it received 422 before the deliberately failing model pipeline. Its fixture is now a valid UUID; exact generic 500, rollback and no-information-leak assertions remain.
- Local browser CORS (`127.0.0.1:5210`) initially leaked into the backend test harness and failed two default-origin tests. The backend harness now uses the same default CORS and public origin as CI. Browser and backend jobs use separate databases and Redis state. Native consumer tests flush Redis database 0, so the final backend run uses a separately labelled, ephemeral Redis with no volume; shared browser/DX state is not its target.

**147 tests passed, zero failed/skipped** for workflow invariants, native billing, main startup/error/CORS and disposable owner-only provider-promotion behavior. Knowledge Registry validation passed all 12 entries. The final full workflow run uses a fresh database and the corrected configuration; earlier diagnostic failures are retained in private evidence and are not described as passing runs.

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

The original `#73758b` small description text on `#f1efff` failed axe color contrast in English desktop and dark mobile. Only the description color in `Billing.css` and `BillingCatalogOriginal.css` changes to the existing banner violet `#5553a9`. Wording, typography, layout, background, responsiveness and navigation remain unchanged. Two numerical WCAG AA regression checks were added. A separately approved correction also changes only the empty-state text color in `PlansSubscription.css` and `BillingCatalogPlansOriginal.css` to the existing `#565c6b`, keeping their white backgrounds and all geometry unchanged. Two more contrast regressions cover these original selectors.

Final frontend checks: **205 passed, zero failed/skipped**, lint passed, Vite 8.3.5 production build passed. Real browser smoke passed all three original configurations: 27/27 screens each in English desktop, Arabic mobile and English dark mobile. Axe passed with **zero findings** in those three configurations and an additional Arabic dark mobile run. Each configuration also audited six existing price-comparison dialogs. Browser calls used the real Python API and reserved synthetic tenant; no new financial operation or real provider call was performed. The separate workflow assistant-evidence presentation checks also passed in English and Arabic; their answer fixtures are explicitly synthetic and do not certify real model execution.

Only color declarations changed in the four original stylesheets. A source comparison proved every other byte of their normalized content is unchanged, including all typography, spacing, dimensions, backgrounds and responsive rules. English/Arabic wording/components are unchanged.

## Final acceptance evidence

**READY TO PUSH FOR GITHUB CI VERIFICATION.** No known CI-remediation defect remains locally. GitHub-hosted status is still unverified.

| Check | Actual result | Private evidence |
|---|---|---|
| Full existing `python -m pytest src/ -q` suite | **4,286 passed, 0 failed, 0 errors, 22 skipped**, 4,308 collected, 420.57 seconds | `backend-final.xml`, `backend-final.log` |
| Invoice/import/accounting selection | 115 passed, 0 failed/skipped; overlaps full suite | `invoices-verified.xml` |
| CI/security/worker/native billing/RLS selection | 719 passed, 0 failed/skipped; overlaps full suite | `ci-final.xml` |
| Workflow/config/main/provider selection | 147 passed, 0 failed/skipped; overlaps full suite | `ci-config-verified.xml` |
| Frontend, bounded concurrency | 205 passed, 0 failed/skipped | `frontend-accepted.log` |
| Frontend lint and production build | Passed; existing nonfatal chunk/dynamic-import warnings retained | `frontend-lint-accepted.log`, `frontend-build-accepted.log` |
| Actual browser screen smoke | 27/27 each, English desktop / Arabic mobile / English dark mobile | `smoke-final.log` |
| Axe WCAG AA | 0 findings across four configurations, including Arabic dark mobile; six comparison dialogs each | `a11y-accepted.json`, corresponding logs |
| Assistant presentation checks | English and Arabic passed; answer response explicitly served by test | `assistant-final.json`, corresponding logs |
| Dependency audit and consistency | 171 available local packages, 0 advisories, no exceptions; `pip check` passed | `audit-patched-local.json`, `pip-check.log` |
| Migrations | 138 fresh; 137-to-138 upgrade; repeat applied 0 | `migration-fresh.log`, `migration-upgrade-initial.log`, `migration-repeat.log` |
| Final role/RLS/constraint recheck | 138 migrations, 120 FORCE RLS tables; `ceopro_app` not superuser/BYPASSRLS; strict invoice constraint unchanged | `database-final-check.json` |
| Application Knowledge Registry | All 12 entries verified | Validator output |

The 22 skips are **not passes**: 17 existing opt-in model-download tests, one live Groq test, one live Stripe test and three real OCR tests lacking local Tesseract/font prerequisites. No test gate was added or relaxed. CI already installs OCR prerequisites and must confirm those three checks on Ubuntu. No unrelated expensive model/provider acceptance was enabled for this CI repair.

The final backend run used disposable database `keel_billing_test_ci_final_20261027`, restricted worker credentials and task-owned ephemeral Redis on 56410, independently of the browser account/database. Earlier runs with missing origin/custom CORS or inherited OAuth aliases are diagnostic evidence, not passing final suites. Existing deprecation and deliberately short synthetic-JWT fixture warnings remain visible; no warning filter was added.

All executable changes were present for their relevant passing checks. The final checkpoint only records evidence and removes a test-file trailing blank line in addition to the verified OAuth fixture correction.

## Changed files and purpose

| Area | Files | Purpose |
|---|---|---|
| CI and dependencies | `.github/workflows/pr-checks.yml`, both `backend/src/{ai,market_scraper}/requirements.txt` | Exact patched Twisted pin, unsuppressed audit, dependency consistency, readiness and correct disposable job configuration. |
| Onboarding fixture | `backend/scripts/ci_smoke_account.py`, `test_ci_smoke_account.py`, `test_ci_smoke_onboarding_integration_db.py` | Save durable onboarding through public APIs; prove one trial, no paid subscription, no duplicate completion/audit. |
| Existing test contracts | `test_api_security_contract.py`, `test_main.py`, `test_shopify_oauth.py` | Preserve HMAC/JWT security distinctions, valid UUID error-path input and isolated OAuth origin settings. |
| CI/dependency regressions | `test_pr_ci_contract.py`, `test_twisted_runtime.py` | Guard workflow configuration and exercise real Scrapy/reactor plus vulnerable parser boundaries. |
| Approved invoice persistence | `extraction/promotion.py`, `extraction/structured_business.py`, `sales/quick_sale.py`, migration `20261111000000` | Store exact paid-total residuals, conditionally normalize the approved effective unit-price representation, preserve existing constraints and historical serialization. |
| Invoice regressions | `test_invoice_rounding_integration_db.py`, `test_extraction_promotion_integration_db.py` | Verify exact money, source evidence, tax/currency/payment state, batch/fallback, rollback, duplicate replay and constraint enforcement. |
| Approved contrast | Four original billing stylesheets, `frontend/tests/trialBannerContrast.test.mjs` | Six color substitutions only, with four WCAG AA regressions and real axe verification. |
| Developer checkpoint | `docs/CI_REPAIR.md`, `docs/README.md` | Record evidence, security tradeoff and remaining hosted verification. |

Test basenames above are under their existing `backend/src/ai/tests` or `backend/src/market_scraper/tests` directory. No source/test file is excluded from the existing CI suite. No audit finding, assertion or required job is disabled.

## Local commits

- `2e4fb20ea05c7637a48b39f16a7c7d04a2eccecd`: dependency, onboarding fixture and route-security test contract corrections.
- `fb58d37af1d93c222c96efb1c02f91d5860c125a`: approved exact invoice persistence, migration and accounting regressions.
- `95267e8e66b682c70e2315009e25ac066da0d07b`: guarded CI database/worker credentials, explicit frontend origin and workflow assertions.
- `53351fda0a3fbd14b567a4acc56751e3782260ec`: owner-authorized color-only contrast corrections and frontend/browser evidence.
- The final checkpoint commit adds the isolated OAuth fixture correction and completed evidence to this same branch.

## Evidence and preservation

Private local evidence: `%TEMP%\KEEL\CiRepair-20261027`. Logs, JUnit, browser reports and runtime secrets are not committed. The isolated API/frontend use ports 8030/5210 and database `keel_ci_repair_20261027`, on verified disposable infrastructure. No real merchant or Stripe calls were needed.

Protected `backend/.env.example` SHA256: `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28`. It is excluded from every commit. No original Node/React source, protected runtime, remote branch, main branch or production resource is modified.

## Hosted verification and follow-up

GitHub Actions has not been rerun by this task. After pushing this branch to its existing PR, confirm all three hosted jobs pass, including Ubuntu/Python 3.11 dependency resolution, the unsuppressed audit, MinIO source build, migrations, complete backend suite, Node 20 frontend checks, browser smoke and axe. Local success does not establish hosted CI status.

The Twisted security pin is a tested release candidate, not a stable production release. Replace it with the maintainer's stable security release when published and rerun the same checks. No other production dependency is changed through the temporary local overlay.

Optional model-download and external-provider acceptance tests retain their existing opt-in gates. No skips count as passes. The local host lacks Tesseract/Unicode font prerequisites for three real OCR checks; the workflow already installs English/Arabic Tesseract and DejaVu, so those checks require hosted confirmation. Deployments must apply the new forward-only invoice precision migration through normal review; no protected database was migrated here.

To trigger the existing PR's checks (run manually, not executed by this task):

```powershell
git -C 'C:\Users\Mohamamd-P\Desktop\Mahmoud\Orange Summer Challenge\KEEL\CEOPRO-AI-full-migration' push origin integration/keel-full-migration
```

The workflow runs on every pull request. A branch push without an open PR does not trigger its push filter, which is limited to `main` and `KEEL_Test`.
