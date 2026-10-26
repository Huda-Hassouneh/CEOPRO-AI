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

## Authorized follow-up in progress

The remaining two failures exposed an existing invoice persistence mismatch introduced before this task. Existing banner contrast also failed axe in English desktop/dark; Arabic light mobile passed. Owner approval explicitly expanded this task to those narrow compatibility/accessibility corrections, including a separate approval for effective paid unit-price normalization when required by the existing bound.

Invoice paid totals, tax, currency, payment state and the database equality/bound must remain unchanged. A forward-only precision migration is necessary because a product of two scale-4 values requires scale 8; historical migrations stay immutable. Final retest and commit evidence will be recorded here before handoff.

## Evidence and preservation

Private local evidence: `%TEMP%\KEEL\CiRepair-20261027`. Logs, JUnit, browser reports and runtime secrets are not committed. The isolated API/frontend use ports 8030/5210 and database `keel_ci_repair_20261027`, on verified disposable infrastructure. No real merchant or Stripe calls were needed.

Protected `backend/.env.example` SHA256: `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28`. It is excluded from every commit. No original Node/React source, protected runtime, remote branch, main branch or production resource is modified.
