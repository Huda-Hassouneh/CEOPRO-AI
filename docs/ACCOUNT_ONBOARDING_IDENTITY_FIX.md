# Account onboarding and authentication isolation

Date: 2026-10-28. Baseline: `ebe0c18720e3f8e34edbafba08354d032624e4fe`.
Scope: browser identity changes, onboarding routing, and the provenance of the
prepared account's Stripe trial. No production billing/accounting behavior changed.

## Findings

**Confirmed client defect:** logout removed credentials but left the shared
QueryClient and onboarding Zustand store populated. SetupGate cached company
completion for five minutes under `['settings-company','gate']`, without an
identity. Email verification navigated to `/dashboard`; the guard could combine
A's completed-company result with B's own valid trial and allow the dashboard.
A read failure also previously rendered protected children. An in-memory run of
the original stores reproduced zero B company reads while A's cache was fresh.
This is a client-side confidentiality/routing defect even without an RLS bypass.

**Subscription ownership:** the prepared identity `28d20?176e`, tenant
`abd3a?001b`, has its own completed Stripe TEST Checkout. There is no evidence of
another tenant's subscription being attached to it. Account A could not be
identified by the owner, so a specific A/B historical comparison remains
UNDETERMINED; comparison against every other local tenant found no shared B
customer or subscription identifier. We cannot identify the human who operated
Checkout from these records.

### Ownership evidence (masked)

| Relationship | Account A | Prepared Account B | Result |
|---|---|---|---|
| User / tenant | Not identified | `28d20?176e` / `abd3a?001b` | A comparison UNDETERMINED; B has one independent membership |
| Company creation | Unknown | Same transaction/time as B verification and owner membership | PASS; independent company provisioning |
| Onboarding | Unknown | Earlier API: step 1 / zero completed; current DB: profile revision 5 and completed | State changed after earlier observation; no repair applied |
| Stripe Customer | Unknown | `cus_V?zpUP` | PASS; only B tenant maps to it |
| Checkout | Unknown | `cs_te?MX3b` expired Standard; `cs_te?bGHN` completed Growth | PASS; both client-reference/customer/session/subscription metadata point to B |
| Stripe Subscription | Unknown | `sub_1?bhkR`, trialing | PASS; customer and metadata match B; not shared with any other local tenant |
| Local Subscription | Unknown | `5d0a8?7c16` | PASS; B tenant FK and provider IDs agree |
| Entitlement assignment | Unknown | B, Growth / trialing / source Stripe | PASS; tenant-owned assignment |
| Credit budget / ledger | Unknown | No materialized budget or usage rows at inspection | No inherited persisted balances found; budgets are lazy |

Local timeline (UTC, 2026-10-27):

- 23:00:39: B user verified, new company and owner membership created; existing
  signup authority issues a local Growth trial through 2026-11-10 23:00:39 UTC.
- 23:05:53: B-specific Stripe Customer mapping and Standard Checkout reservation.
- 23:06:12: first reservation expired; provider also reports `expired`.
- 23:06:23: second reservation requests Growth monthly, bound to B's customer.
- 23:06:33: processed `invoice.paid` receipt (`evt_1?U8j0`) creates local
  subscription; subsequent subscription-created and Checkout-completed receipts
  agree on B. Completed session receipt: `evt_1?wkGf`.
- 23:26:34: company onboarding completion recorded, after the earlier browser read.

Authenticated provider GETs returned HTTP 200 and `livemode=false` for customer,
subscription, both Checkout sessions, matching events and invoice. Growth session
is `complete`; its subscription-create invoice is paid **USD 0**, not a paid month.
The older provider `created` timestamps are simulated Test Clock time, not evidence
of pre-signup customer reuse. The clock was not advanced during this investigation.

The local fixed-plan attempt retains reservation state `open`; this schema only
has preparing/open/expired states. It is not the payment authority. The actual
provider completion and reconciled subscription are the acceptance evidence.

The webhook HTTP entry point verifies raw-body signatures before opening the
restricted reconciliation connection. Relevant receipts have processed timestamps
and no errors and match real provider events. Historical signature headers are not
retained, so they cannot be independently revalidated retrospectively. No event
was replayed or fabricated. Signup issues a **local** trial only; it does not call
Stripe Customer/Checkout/Subscription creation.

### Tenant boundaries

Read-only SQL under `ceopro_app` with B's verified user/tenant context exposed zero
foreign rows across companies, memberships, products, inventory, customer mappings,
subscriptions, Checkout attempts, assignments, credit balances, usage ledger and
knowledge-base metadata. All eleven checked tables had RLS and FORCE RLS enabled.
No cross-tenant subscription inheritance or backend data-access violation was
observed. This is scoped evidence, not certification of every application endpoint.

## Correction

| File (under frontend/src) | Responsibility / minimal change |
|---|---|
| `features/auth/store/identityBoundary.js` | Synchronous QueryClient cleanup, onboarding reset, pending-registration and transient setup-marker cleanup before publishing another identity |
| `features/auth/store/authStore.js` | Apply boundary on initialization, session replacement, logout, expiry, cross-tab adoption and changed user/tenant; preserve caches for same-identity renewal |
| `app/router/SetupGate.jsx` | User/tenant company key; pending/error/missing company cannot open dashboard; localized retry uses existing translations |
| `features/onboarding/components/OnboardingGate.jsx` | User and tenant scoped progress reads; existing durable current-step redirect retained |
| `features/onboarding/store/onboardingStore.js` | Reset generation; late save results cannot hydrate a new identity or submit its plan from an old read |
| `app/providers/AuthProvider.jsx`, `features/auth/pages/VerifyEmailPage.jsx` | Refreshed token applies only if initiating session is still current |
| `shared/lib/httpClient.js` | Bind bearer token synchronously at request creation; verification refusals carry initiating authorization for stale-response protection |

No React redesign, translation replacement, backend business change, database
migration/grant, subscription repair, or financial-policy change is included.
Existing invited membership, signup trial eligibility, paid activation, downgrade
trial cutoff, accounting, and optional Test Clock authority remain server-owned.
Theme and language preferences are preserved. This is not a force-onboarding-on-login
workaround: existing completed companies still pass the real server-backed guard.

## Verification and reproduction

Private evidence lives under `.dev/evidence/`; do not upload logs, credentials or
browser storage. Test databases are separate from the E: customer database.

- `a860e885a9b9`: 365 billing/onboarding/credit/entitlement/RLS tests passed,
  including existing trial downgrade and Test Clock enabled/disabled regressions.
- `3b050502e9b5`: 47 authentication/signup/invitation/onboarding tests passed,
  including the initial new independent-account native regression.
- `23a000f769df`: final strengthened native onboarding/isolation follow-up, 2
  passed; includes an A-only product/stock record, B product 404, foreign workspace
  and signed non-member token 403, ordinary company/dashboard/invoice/document
  reads, and native RLS checks.
- Final frontend suite: 214 passed, zero failures/skips; ESLint and production
  build passed (`account-isolation-frontend.log`, `account-isolation-build.log`).
- `frontend/tests/accountIdentityIsolation.test.mjs`: logout, identity/workspace and
  cross-tab transitions, late query/save/plan-response/refresh protection.
- `frontend/tests/httpClientUnauthorized.test.mjs`: stale unauthorized and email
  verification responses stay bound to the initiating session.
- `backend/src/ai/tests/test_ci_smoke_onboarding_integration_db.py`: independent
  provisioning, RLS and real HTTP denial of foreign resources/workspace scopes.
- `frontend/tests/browser/account-isolation.mjs`: real signup, Mailpit OTP, six-step
  local-trial onboarding, actual logout menu, same SPA B signup, fresh browser,
  existing A login, localized fail-closed outage; English and Arabic/mobile RTL.
  Only the outage check intercepts a response; successful lifecycle requests use
  the real API and PostgreSQL. No Stripe credentials are supplied to this harness.
- `cb9498e0d847`: 12 real-browser checks passed (English desktop and Arabic
  mobile RTL), including the actual profile-menu logout; zero provider records
  in the disposable database. Screenshots wait for the regional form to render.
- Fresh/repeat migration checks: 144 migrations; 120 FORCE RLS tables; restricted
  password logins. No new migration required.

Run from the repository root with the configured existing Python runtime:

```powershell
.\dev.ps1 test --suite backend --pytest-args src/ai/tests/test_ci_smoke_onboarding_integration_db.py -q
$runtime = (Get-Content .dev/config.json -Raw | ConvertFrom-Json).runtime_python
& $runtime tools/dev/verify_account_isolation.py
Set-Location frontend
npm test
npm run lint
npm run build
```

The harness uses existing repository-owned isolated infrastructure, persists
results/screenshots and verifies zero Stripe customers, Checkout reservations or
subscriptions in its disposable DB. It never operates on the prepared account.
Failed preliminary harness runs remain recorded; final evidence is reported at
delivery rather than treating those failures as passes.

## Rollout and manual acceptance

A private, ACL-protected database/roles/configuration backup was created before
rollout and restored into an inactive verification database: all 139 public table
fingerprints matched. Backup location and rollout checks are recorded only in
`.dev/evidence/account-isolation-rollout/`, outside tracked files. Preserve the
existing customer accounts and private `.dev/integrations.env`.

1. Open the printed frontend URL; sign in as an already completed synthetic A.
2. Use the account menu to log out, then follow the Signup link in the same tab.
3. Register a different synthetic email and verify its OTP in Mailpit.
4. Expect Regional Preferences (or that identity's actual durable pending step),
   never A's company/dashboard. Inspect B's own user/tenant identity.
5. Complete the six steps and deliberately choose the current local trial or an
   authorized plan. Signup trial alone is not a Stripe subscription.
6. Repeat with a fresh/incognito context; existing completed A must still reach
   its own dashboard after login.

No new external Stripe Checkout/payment acceptance is claimed. B's existing
provider records were retrieved read-only, not reset, canceled or rewritten.
No remote push, protected-main merge or production deployment is authorized.
