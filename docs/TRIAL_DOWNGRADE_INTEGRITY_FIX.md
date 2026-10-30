# Trial downgrade integrity incident and correction

Date: 2026-10-28. Branch: `integration/keel-full-migration`.
Investigated source/runtime baseline: `786c8b9d1f399ed67a270d87bebeefbad5fd225b`.
Implementation commit: `df4a6754096974d5cb7224afe4963f865ed5d4f1`.
The report is committed separately; no subsequent application changes are included.

## Verdict

**Confirmed backend entitlement-integrity vulnerability, not a display-only defect.**
A downgrade rewrote Stripe's current schedule phase without its `trial_end`.
Stripe ended the trial immediately, reset the billing anchor, and reported `active`
before collecting the new invoice. KEEL accepted that provider status and switched
its effective assignment from trial limits to paid-plan limits.

The affected customer's account, invoices, subscription, credits and running E:
application were not changed during this investigation. No new Stripe resource,
Checkout, payment, refund, credit or subscription was created.

## Preserved incident evidence

Read-only PostgreSQL queries and Stripe TEST GETs returned the following. Times are UTC;
identifiers are masked. Raw credentials and customer personal information are excluded.

| Evidence | Observed state |
|---|---|
| Runtime | E: development checkout and API both at the baseline above; Git clean |
| Tenant fingerprint / subscription | `327395dcc10a` / `sub_1UVH****HcED` |
| Original plan / term | `growth`, monthly; requested downgrade to `starter`, monthly |
| Signup trial | Oct 27 20:55:07.938777 through **Nov 10 20:55:07.938777** |
| Initial Stripe trial | Started Oct 27 20:55:44; original trial end Nov 10 20:55:07 (Stripe integer-second precision) |
| Schedule created | Oct 27 20:56:31: current phase contained the original trial end |
| Schedule updated | Oct 27 20:56:32: same current phase lost `trial_end`; next phase selected `starter` |
| Stripe subscription update | Previous `trialing` / original cutoff became `active` / Oct 27 20:56:32 cutoff; billing anchor reset |
| Incorrect provider and local term | Oct 27 20:56:32 through **Nov 27 20:56:32**; both reported `active` |
| Trial invoice | `in_1UVHP****SZi0`: paid, amount paid USD 0.00; legitimate trial evidence |
| Update invoice | `in_1UVHQ****aof8`: draft, amount due USD 140.00, amount paid 0; not payment confirmation |
| Subsequent action | Pending change released Oct 27 20:57:39; truncation/active state remained; no pending local schedule at snapshot |
| Local rights | `tenant_plan_assignments`: growth / active / Stripe, matching the incorrect provider term |
| Credit evidence | No `tenant_credit_balances` rows for this tenant at diagnosis; no demonstrated credit consumption/grant |
| Webhooks | Relevant Checkout, subscription, invoice and schedule-release receipts were processed without errors |

This incident is **not caused by the earlier malformed Stripe CLI event filter**:
the relevant state-changing deliveries were received and reconciled. Read-only
provider subscription/invoice/event lookups returned HTTP 200 and `livemode=false`.

Redacted snapshots remain in the development checkout's ignored directory:
`.dev/evidence/trial-transition-20261028/{before-redacted,schedules-redacted}.json`.

### Why no paid invoice appeared

KEEL stores payment outcomes from verified paid/succeeded/failed invoice events;
it does not treat `invoice.created` for an unpaid draft as a payment. The only
local succeeded invoice was the USD 0.00 trial invoice. There was no corresponding
nonzero paid invoice for the incorrectly activated term. The zero-dollar row does
exist locally; its absence from a particular cached UI view was not independently
established as another UI defect.

## Exact write and reconciliation chain

1. `routers/billing.py:change_plan` authenticates the tenant billing role and opens
   `ceopro_app` plus the restricted Checkout/setup capability.
2. `billing/service.py:change_plan` previously reconstructed the current phase with
   only `start_date`, `end_date` and `items`. `stripe_api.modify_schedule` sent it
   to Stripe, clearing the omitted trial setting.
3. `store.set_schedule` / execute-only `billing_setup_schedule` wrote only pending
   plan/term metadata. **The endpoint did not directly write local active status.**
4. Stripe ended the trial and reset its own billing anchor. The signed subscription
   event caused `webhooks.sync_subscription` to retrieve that current provider state.
5. `store.apply_subscription` upserted `billing_subscriptions`, then the Stripe
   `tenant_plan_assignments` record. Existing snapshot machinery captured plan terms.
6. `core/usage.get_plan` selected paid rather than trial allowances because status
   was now active. Credits remain lazy, tenant-scoped accounting balances; the
   schedule request itself never directly inserts a credit grant.

The original read-only Node `stripe.client.ts` schedule-update method contained the
same omission. Intended trial preservation is retained; the inherited defect is not.
Stripe explicitly requires resending trial settings when updating phases:
[subscription schedules](https://docs.stripe.com/billing/subscriptions/subscription-schedules).
Update-time proration is separately controlled:
[update API](https://docs.stripe.com/api/subscription_schedules/update).

## Correction

| File | Correction |
|---|---|
| `backend/src/ai/billing/service.py` | Preserve current phase trial cutoff, tax/discount/payment settings, item quantities and metadata. Schedule trial reductions at the existing trial cutoff. Set update-time proration to `none`. Serialize change/cancel commands with the existing advisory-lock helper. Refuse provider mutations while local/provider identity, status or dates disagree, or the trial has expired. Additional one-time invoice items require review rather than being repeated/dropped. |
| `backend/src/ai/billing/store.py` | Reject changed known trial cutoffs and active periods starting before the approved cutoff. Require verified first post-trial invoice evidence before trial/failure recovery can become active. Reject inside the webhook transaction, preserving the last valid assignment and a retryable error receipt. |
| `backend/src/ai/billing/webhooks.py` | Retrieve the provider's latest invoice for the same subscription/customer when converting an existing trial to active. Require paid status and a line covering the new period. A paid USD 0 trial invoice covering the old trial cannot authorize the next term. A genuinely paid zero-total invoice covering the new term is valid; no invented nonzero-payment rule. |
| `backend/src/ai/core/usage.py` | Stripe trial access expires at its exact recorded UTC cutoff even with a missing/delayed webhook. Effective expired status refuses feature/credit spending without mutating financial history. |

No migration, grant, RLS policy, database identity, financial rate, pricing algorithm,
frontend production component, translation, layout or subscription price was changed.
Normal paid-plan upgrade payment confirmation and legitimate trial upgrades remain intact.

## Verification

All provider writes in tests are **offline doubles**. Native PostgreSQL, password
logins, FastAPI endpoints, signature validation, application SQL and React are real.
The provider double explicitly reproduces the observed lossy-phase failure.

### Mandatory scenario coverage

Tests: `backend/tests/billing/test_trial_plan_transitions.py`, alongside existing
billing, entitlement, accounting and restricted-role regressions.

| Scenario | Assertion |
|---|---|
| Trial downgrade | Pending schedule; unchanged trial status, cutoff, period, snapshot and balances |
| Trial upgrade | Same trial cutoff; no paid activation; rights update only after signed reconciliation |
| Cancel pending downgrade | Releases schedule and clears metadata; original trial remains |
| Repeat / multiple transitions | Repeat rejected idempotently; no new clock, paid period or grants |
| Expiry without webhook | Exact boundary returns expired/no access; both credit kinds refused |
| Failed first payment / recovery | Past due denies spending; verified paid covering invoice activates once |
| Paid downgrade | Existing paid period and assignment preserved |
| Failed renewal | Existing denial/recovery policy enforced |
| Missing webhook | Mismatching remote/local state returns 409 before provider mutation |
| Delayed/replayed events | Fresh provider lookup, event deduplication, no rollback or duplicated effects |
| Cross tenant | Owner of another tenant denied; no provider schedule created |
| Concurrent requests | Four requests produce one schedule/update and three already-scheduled refusals |
| Zero trial invoice | Remains trialing; separate paid invoice retained as separate history |
| Data / AI Credits | Existing spend/budget period unchanged by scheduling/cancel; duplicate reservation refused |
| Unpaid active provider label | Draft/open/missing/old-trial/unrelated invoice cannot activate; fresh paid evidence allows safe receipt retry |
| Phase commercial settings | Current financial fields preserved; unsupported additional invoice items held for review |

| Check | Final result | Evidence |
|---|---|---|
| Affected backend/native suites | **356 passed, 0 failures/errors/skips**, including 25 new trial-integrity cases | `.dev/evidence/tests/bdc4fb257b55/backend.xml` and `backend.log` |
| Launcher/tooling guards | **47 passed** | Executed by each repository backend test command |
| Frontend regressions | **205 passed, 0 failures/skips** | `npm test`, existing concurrency bound of two |
| Frontend lint | PASS | `npm run lint` |
| Production build | PASS | `.dev/evidence/tests/fe47da7e03ed/build.log` |
| Committed-revision browser | **EN desktop and AR mobile/RTL PASS**: actual password login, schedule, reload, cancel, reload, exact metadata/dates, no page exceptions | `.dev/evidence/tests/fe47da7e03ed/{run,browser-results,database-result}.json`, `browser.log`, four screenshots; revision `df4a675` |
| Database | **144 existing migrations fresh + no-op repeat PASS; 120 FORCE RLS tables verified**; restricted password login verified | Both final runs' `migrations.log` and database preflight |
| Official Stripe SDK request schema | PASS: all preserved phase/item request keys supported | Local read-only SDK annotation check; no provider request |

The final browser run independently verified that stored trial status, exact period
bounds and trial cutoff were unchanged and that no credit balance rows were issued.
Change-plan, cancel and subscription-read API requests returned HTTP 200; native
stale-state and repeated-change cases return 409 and unauthorized tenant cases deny
access. Signed valid/invalid/replayed receipt cases exercise the existing restricted
webhook and accounting sockets, never a runtime administrator DSN.

No schema changed; an additional upgrade-migration campaign was unnecessary. The
backend emitted one existing Starlette TestClient deprecation warning; no failed
assertions or skipped checks were counted as passed.

### Reproduce

From the integration checkout (requires its documented development setup):

```powershell
.\dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_credits_integration_db.py src/ai/tests/test_usage_integration_db.py src/ai/tests/test_billing_effective_rights.py src/ai/tests/test_billing_consistency.py src/ai/tests/test_rls_integration_db.py src/ai/tests/test_billing_integration_db.py -q
```

Browser harness reuses `tools/dev/testing.py` isolation and normal readiness checks:

```powershell
$cfg = Get-Content .dev/config.json -Raw | ConvertFrom-Json
$py = if ($cfg.runtime_python) { $cfg.runtime_python } else { '.\.dev\venv\Scripts\python.exe' }
& $py backend/scripts/verify_trial_transition_browser.py
```

The guarded fixture refuses a non-test database or an API identity other than
`ceopro_app`, imports no external Stripe credentials, and forbids provider network
calls. It signs in a synthetic fixture through actual password authentication,
opens the original Billing/change-plan screens, schedules/cancels via real APIs,
reloads, verifies exact pending metadata and dates, and compares database state.
English desktop and Arabic mobile/RTL screenshots and request statuses are saved.
Owned test processes/services stop afterward; protected development resources remain.

## Existing affected records and controlled reconciliation

**The running E: application is still at the investigated baseline; it has not been
silently updated or restarted. The existing affected subscription is not repaired
merely by committing this prevention fix.** Do not use it for further plan changes
until the correction is installed and the incident is reconciled.

Proposed procedure, requiring separate approval for the affected-account mutations:

1. Preserve the redacted evidence and original provider event identities. Identify
   additional trial subscriptions with early truncation/anchor resets using read-only
   comparison with their original trial records and provider invoice evidence.
2. Review the unintended draft invoice. Do not automatically collect, forgive,
   delete, void or fabricate financial history. Agree its provider-side resolution.
3. Confirm restoration of **the original approved cutoff**, not a new/free extended
   trial, against the original trial and subscription events. Confirm any actual
   intervening payment before deciding the resulting entitlement state.
4. Use an audited, idempotent, narrowly scoped reconciliation operation with fresh
   provider evidence and the existing restricted billing authority. Repair provider
   terms first as approved, then reconcile local assignment/snapshot and any actual
   balance deltas once. No administrator API DSN or ad-hoc SQL active/grant update.
5. The new guard intentionally quarantines conflicting historical cutoffs. Routine
   webhook replay alone is not an approved repair for already corrupted records;
   the explicit reconciliation path must validate the original evidence and record
   its approval. Verify final provider/local term, effective rights and audit receipt.

## Limits

- Real Stripe TEST evidence establishes the **original incident**. The fix is verified
  using offline provider behavior, real native databases and the real browser.
- A separate real-provider Test Clock trial/schedule/payment retest remains **UNRUN**.
  The existing Stripe listener serves the customer development database; no new
  provider-event scenario was sent into that environment. No new external resources
  or financial actions were performed. This is not paid
  Checkout or production certification.
- No customer financial records were automatically corrected. E: rollout and the
  approved audited reconciliation remain operational follow-up work.
- Protected `.env.example` hash and unrelated documentation remain unchanged;
  original Node/React repositories remain read-only. No push or deployment.
