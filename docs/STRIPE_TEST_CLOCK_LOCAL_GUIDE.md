# Stripe Test Clocks: local KEEL only

Use this optional mode for **fresh synthetic tenants in an authorized Stripe TEST
sandbox**. It creates no clock, customer, subscription, payment or entitlement at
startup. The default is disabled. Normal production billing does not need it.

## Prerequisites

- KEEL's existing `dev.ps1` environment, PostgreSQL/Redis and all required workers healthy.
- Stripe CLI authenticated to the same TEST sandbox as `.dev/integrations.env`.
- Valid `STRIPE_SECRET_KEY` and the signing secret for the actual CLI listener.
- A clock preferably starting at current UTC, and a **new KEEL tenant**. Do not reuse the
  previously corrupted subscription or any existing ordinary customer.

```powershell
Set-Location 'E:\KEEL START\CEOPRO-AI' # or your own clone
.\dev.ps1 status
stripe --version
$balance = stripe get /v1/balance | ConvertFrom-Json
$balance.livemode # must be False; stop if True
```

Keep the existing listener running, or start exactly one in another terminal:

```powershell
stripe listen --all-snapshot --forward-to http://127.0.0.1:8000/billing/webhook
```

Use the API port printed by your checkout. Never use `--live`. Never paste keys
into source, issues or chat. The listener's `whsec_...` stays in private config.

## Create or identify a clock

These commands intentionally create a TEST resource when **you** execute them:

```powershell
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$created = stripe test_helpers test_clocks create --frozen-time $now --name 'KEEL-local-lifecycle' | ConvertFrom-Json
$clock = $created.id
$clock # copy this clock_... identifier
stripe test_helpers test_clocks retrieve $clock
```

For an existing clock use `stripe test_helpers test_clocks list`, then retrieve its
ID. A new signup cannot use a clock already advanced into the future relative to
actual UTC; create a new current clock for that new scenario. Existing clock
customers can continue after advancement. A past frozen origin is allowed, but
Stripe's simulated interval until the trial cutoff is longer than the real elapsed
signup interval. KEEL retains the original absolute UTC trial expiry; it does not
reissue or extend the trial. Prefer a current clock for comparable timing.

## Enable

Edit only these entries in **private `.dev/integrations.env`**, preserving all
existing keys and other settings:

```dotenv
STRIPE_TEST_CLOCK_ENABLED=true
STRIPE_TEST_CLOCK_ID=clock_replace_with_your_clock_id
```

Then:

```powershell
.\dev.ps1 restart --mode full
.\dev.ps1 status
```

`up`/`restart` validates TEST credentials, the actual clock's TEST mode and ready
status before starting the API. Output includes `OK Stripe TEST clock is ready`
and `Stripe Test Clock: ENABLED`. No secret is printed. Missing/bad IDs, unavailable
clocks, advancing clocks and LIVE responses fail clearly without creating an
ordinary customer as a fallback.

The bridge also checks checkout-owned local launcher markers, development environment,
loopback database and presence of the local adapter. Hosted/production environments
are refused. Do not set internal `KEEL_LOCAL_TEST_CLOCKS` manually: the launcher owns it.

## Run a customer journey

1. Open an incognito window at the frontend URL, normally `http://127.0.0.1:5173/signup`.
2. Register a new synthetic customer, verify email in Mailpit (normally port 58025),
   and complete the original onboarding. Choose Plus (`growth`), monthly, for a
   downgrade test to Standard (`starter`). The original signup trial is preserved.
3. Complete hosted Stripe TEST Checkout yourself. KEEL creates the Stripe Customer
   with `test_clock`; it does not modify or reassign an existing customer.
4. Get the new `cus_...` and `sub_...` IDs from Stripe's sandbox dashboard/CLI and verify:

```powershell
$customerId = 'cus_your_new_customer'
$subscriptionId = 'sub_your_new_subscription'
$customer = stripe customers retrieve $customerId | ConvertFrom-Json
$sub = stripe subscriptions retrieve $subscriptionId | ConvertFrom-Json
$customer.test_clock # must equal $clock
$sub.status         # trialing
$originalTrialEnd = [long]$sub.trial_end
[DateTimeOffset]::FromUnixTimeSeconds($originalTrialEnd).UtcDateTime
```

5. Schedule the downgrade through KEEL. Retrieve the subscription again: status
   remains `trialing`; `trial_end` remains exactly `$originalTrialEnd`. Canceling,
   repeating or changing the pending plan must not grant a paid term or credits.
6. Advance to just past the original trial end:

```powershell
$target = $originalTrialEnd + 1
stripe test_helpers test_clocks advance $clock --frozen-time $target
$state = stripe test_helpers test_clocks retrieve $clock | ConvertFrom-Json
$state.status
```

Repeat retrieve until `ready`; `internal_failure` is a failure, not success. While
`advancing`, KEEL may temporarily refuse clock-dependent feature/budget reads.
Do not change settings, submit another Checkout or fabricate events while waiting.

7. Observe actual snapshot events in the listener. At first the new invoice may be
   draft. If appropriate for the scenario, advance one simulated hour further and
   wait for `ready` again:

```powershell
$target += 3601
stripe test_helpers test_clocks advance $clock --frozen-time $target
stripe test_helpers test_clocks retrieve $clock
stripe subscriptions retrieve $subscriptionId
stripe invoices list --subscription $subscriptionId
```

A paid **$0 trial invoice covering the old trial is not payment for the new term**.
KEEL's verified invoice/period checks remain enforced; first paid activation waits
for a paid invoice covering the new period. A legitimately zero-total paid invoice
covering that new period is distinct from the old trial invoice.

8. Compare KEEL Billing, provider subscription/invoices, signed receipt outcomes,
   effective rights and Data/AI Credit period keys. At renewal repeat advancement
   to the next provider term; inspect invoice collection and wait for reconciliation.
   Consumption rows are created lazily by authorized usage, not fabricated at startup.
9. Use separate synthetic scenarios for successful first collection, failed payment
   and recovery, upgrade, cancellation and period-end denial. Use Stripe's documented
   test payment methods/settings; do not use real cards or change commercial policy.
   Use Stripe's event resend facilities for replay/delay tests; do not edit signed
   payloads. Customer creation/clock management has no public KEEL endpoint.

Do not claim a scenario passed merely because the clock became ready. Inspect the
actual invoice/payment outcome, webhook receipt, local state and credit ledger.

## Stripe time versus Windows/FastAPI time

Clock advancement does **not** change Windows, Python, PostgreSQL or JWT time.
The optional adapter uses the verified clock's `frozen_time` only for:

- Billing trial-expiry checks and schedule phase selection for that clock customer.
- `usage.get_plan`'s current entitlement term and allowance/credit period selection
  for that tenant, through its restricted subscription-to-customer mapping.

This prevents future simulated periods from falling back to the server's current
calendar month. Unrelated tenants without that clock retain real UTC. Explicit
`now`/`today` arguments in deterministic tests retain their existing meaning.

OTP/JWT expiry, Stripe signature timestamp tolerance, request idempotency age,
reservation timeouts, provider-cost effective dates/caps, operational worker schedules
and audit receipt timestamps still use real time. No global clock patch exists.
Test clocks do not certify those elapsed-time or provider-cost scenarios; wait real
time/use their isolated deterministic tests. No production entitlement semantics change.

## Disable

```dotenv
STRIPE_TEST_CLOCK_ENABLED=false
STRIPE_TEST_CLOCK_ID=
```

```powershell
.\dev.ps1 restart --mode full
```

Expect `Stripe Test Clock: DISABLED`. An ID left present is ignored. There are no
additional clock/customer-verification API calls; ordinary Customer creation has
exactly its previous request parameters and stable tenant idempotency key.

Previously clock-associated customers **remain associated** in Stripe. Do not reuse
those tenants for ordinary wall-time tests, and do not change clocks on a pending
Checkout. Use a fresh tenant for ordinary testing or a different clock. No customer,
subscription, history or balance is deleted by disabling this flag.

## Troubleshooting

| Symptom | Action |
|---|---|
| Missing/invalid/unavailable clock | Check `clock_...`, configured sandbox and readiness; do not create a normal customer as fallback. |
| Wrong sandbox / LIVE key or response | Stop. Align CLI and backend TEST account; never add `--live` or bypass mode checks. |
| Clock advancing | Wait for `ready`; investigate `internal_failure`. Clock-dependent reads fail closed temporarily. |
| Customer has no/different clock | Use a new tenant. KEEL deliberately offers no reattachment operation. |
| New customer refused for future clock | Create a new current clock before signup/Checkout. Existing signup trial is not rewritten. |
| No webhook / pending subscription | Check listener origin/port, signing secret and `.\dev.ps1 logs --service api`; inspect provider invoice and pending receipt. |
| Paid $0 invoice but no active month | Check whether it covers the old trial or the new term; do not manually mark paid. |
| Invoice not listed | Filter Stripe list requests by customer, subscription or clock; unfiltered lists may omit clock objects. |
| Advancement rejected | Stripe limits advancement to two intervals of the shortest subscription (two years without subscriptions). Advance in permitted steps. |
| Repeated update rate limits | Advance a few simulated minutes, wait ready, then retry once; keep KEEL idempotency protection. |
| Feature lacks verified economic rates | Test clocks do not invent provider rates, margins, prices or credits. |
| Production accidentally enabled | Startup/provider operations fail closed. Remove the flag; do not copy the local adapter into a production image. |

Do not delete a clock to disable KEEL: Stripe clock deletion also deletes its linked
customers/subscriptions. Preserve evidence and obtain explicit cleanup authorization.

## Implementation and verification

- `backend/src/ai/billing/test_clock.py`: disabled no-op and production/configuration guard.
- `tools/dev/stripe_test_clock.py`: local-only validation and tenant-scoped provider time;
  outside every existing backend Docker build context and absent from production images.
- `stripe_api.py` / `service.py`: Customer creation/reuse and existing hosted Checkout.
- `core/usage.py`: isolated per-tenant billing-time hook; no financial SQL writes.
- `main.py`: startup guard; `tools/dev/dev.py`: explicit opt-in, preflight and status.
- `backend/tests/billing/test_local_test_clock.py`: provider doubles plus real restricted
  PostgreSQL/HTTP/signature/accounting boundaries; trial-security regression suite retained.

Verification on Windows / Stripe SDK 15.6.1:

| Check | Result |
|---|---|
| Affected billing/entitlement/accounting/RLS suite | 386 passed, zero failures/skips (`.dev/evidence/tests/f5628cea8737/backend.xml`) |
| Clock, worker orchestration and restricted-role follow-up | 57 passed, zero failures/skips (`8c22b5e9a0d0/backend.xml`) |
| Final clock + trial-integrity + billing contract follow-up | 80 passed, zero failures/skips (`48ec3c06fa30/backend.xml`) |
| Local tooling | 49 passed, including opt-in, inherited-env exclusion and default-off behavior |
| Frontend | 205 passed; lint and production build passed; no frontend source change |
| Schema and permissions | 144 fresh/repeat migrations and 120 FORCE RLS tables verified; no new migrations |
| Installed SDK | Customer `test_clock` request parameter and TestClock retrieval verified |

The fixtures double provider HTTP only. They exercise actual FastAPI authorization,
real Stripe signature verification, restricted password connections, tenant RLS and
native credit persistence. They are not real Stripe-generated lifecycle acceptance.
A build-context/static guard check was used; a new production ML image was not built.

No migration, permission, RLS, invoice/payment evidence or production example changed.
The loader never reads `.dev/integrations.env` in a production process. The current
Docker build contexts contain only `backend/`, so the optional adapter is physically
absent. An accidentally true flag is rejected both at startup and at provider access.

Real Stripe clock-generated lifecycle acceptance remains a **manual test**, not a
claim inferred from automated doubles. The feature defaults to disabled; an existing explicit private opt-in is preserved during local rollout.

References: [Stripe clock API guide](https://docs.stripe.com/billing/testing/test-clocks/api-advanced-usage),
[Customer creation](https://docs.stripe.com/api/customers/create),
[advancement limits](https://docs.stripe.com/api/test_clocks/advance).
