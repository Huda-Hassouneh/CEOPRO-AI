# Phase 1.3D-A1 — dormant recurring-consent foundation

Implementation date: 2026-11-08 (Asia/Amman). No commit, deployment, provider call,
shared database migration, consent UI or legal-policy publication.

## Repository and scope

Target: `E:\KEEL START\CEOPRO-AI\.dev\worktrees\main-consolidation`, branch
`integration/main-consolidation`, unchanged HEAD
`2453f76b3a8e274927fb08752ad50df78fe626ed`. The worktree was clean before editing.
The task-supplied Phase 1.3D-A assessment findings were traced against current
source. No separate cutover-assessment document was found in this checkout.

This is a reviewable dormant foundation, not a billing cutover or provider
readiness implementation. Existing signup/email verification, workspace creation,
standalone local trials, standard/custom Checkout, Customer operations, webhook
reconciliation, B2–B4, entitlement projection, Credits and onboarding code remain
unchanged. The current website/Checkout still does not capture this agreement.

## Exact file manifest and diff

| File | Change |
| --- | --- |
| `backend/src/infrastructure/database/migrations/20261205000000_recurring_consent_foundation.sql` | New forward-only migration 171; name was available; no historical migration edits. |
| `backend/src/ai/billing/recurring_consent.py` | New dormant provider-neutral typed presentation identity and restricted repository; canonical immutable `CustomerPayload` reused. |
| `backend/tests/billing/test_recurring_consent.py` | New offline identity, digest, import and side-effect boundaries. |
| `backend/tests/billing/test_recurring_consent_db.py` | New native synthetic-policy/consent, authorization, concurrency, rollback, RLS and password-role regressions. |
| `backend/scripts/verify_recurring_consent.py` | New guarded disposable PG17/Redis verifier based on the existing B4 verification convention. |
| `backend/tests/billing/test_verification_observations.py` | Expected forward migration count 170 → 171; all B3 assertions retained. |
| `backend/tests/billing/test_payment_webhook_decoder.py` | Add only the dormant consent module to the canonical-contract import allowlist. |
| `docs/RECURRING_CONSENT_FOUNDATION.md` | This implementation, evidence, limitation and dependency report. |

All changes remain uncommitted. No tracked production file was modified; the
migration and dormant module are additions. No frontend, active route, existing
worker, billing command, provider adapter, migration runner or configuration changed.

## Existing identities reused

* B2 `billing_trial_checkouts`: `attempt_id`, tenant, initiating user, original
  `binding_id`, immutable `approved_terms` and approved commercial values.
  `billing_checkout_attempts.attempt_id` is the SAME reservation identity.
* Original `billing_gateway_bindings`: provider, environment, merchant and binding
  remain immutable; changing the currently selected binding cannot rebind consent.
* B3's canonical digest is PostgreSQL JSONB text → UTF8 → SHA256 over the ENTIRE
  reservation document, including its nested binding and entitlement snapshot.
  This is distinct from `catalog_revision_id`; Python never re-encodes this digest.
* B3 operation + Customer reference + succeeded durable Customer operation provide
  post-Checkout lineage. No client metadata is an association authority.
* B4 `billing_trial_consents` remains the downstream consent source of truth.
  A1 bridges to that table; it creates no alternate attestation/confirmation path.
* Existing tenant billing roles are owner/admin/accountant. Platform Owner is not
  substituted for a tenant's initiating actor. Existing `keel_active_principal`
  remains authoritative for company, user, membership and platform-workspace state.

Signup's displayed Terms/Privacy links and onboarding's connector consents are
not recurring billing consent. No reusable recurring agreement/version registry
or pre-Checkout acceptance writer existed in the reviewed path.

## New schema and flow

All five new tables have ENABLE/FORCE RLS and immutable UPDATE/DELETE guards.

1. `billing_consent_policy_versions`: installation-only immutable revision and
   language registry. `pending` and `unsupported` are explicit. An `approved` row
   requires agreement identity/revision/content digest, cancellation and renewal
   disclosure references, approved trial-start and retention references, environment,
   eligible billing intervals, presentation lifetime and approval provenance.
   **The migration seeds zero rows, supplies no approval writer and invents no policy.**
2. `billing_consent_presentations`: exact reservation/tenant/binding/actor composite
   FK, full frozen terms and digest, policy revision, DB creation/expiry timestamps
   and explicit initial status. Charged amount/currency/interval/trial duration
   come from the frozen commercial snapshot, never company analysis currency.
   Quantity one is the existing B2 fixed-plan/B3 convention; other quantities are
   unsupported. No pricing calculation or today's catalog substitution is added.
3. `billing_consent_acceptances`: immutable authenticated-actor evidence referencing
   exactly one presentation. A unique presentation key consumes its challenge once.
   Acceptance time comes from the database clock. No user ID, price, timestamp,
   agreement text or verification result is accepted as a command argument.
4. `billing_consent_invalidations`: append-only withdrawal/supersession evidence.
   Acceptance and terms survive invalidation. Expiry is an acceptance-window check;
   it does not rewrite historic acceptance. A different policy/terms selection
   requires a new presentation and challenge, with explicit invalidation as needed.
5. `billing_consent_associations`: immutable bridge to the exact Checkout attempt,
   original binding, scoped Customer, succeeded Customer operation, B3 operation,
   Checkout identity and full terms digest. Compound FKs protect lineage. The command
   derives identities from canonical rows; callers supply only acceptance/operation
   IDs. Acceptance must predate Checkout submission. It atomically inserts B4's
   consent (same UUID as the acceptance) and the bridge. Exact repeats return the
   existing bridge while the reservation is pending; conflicts cannot rebind it.

The four callable commands are `billing_consent_present`, `billing_consent_accept`,
`billing_consent_invalidate` and `billing_consent_associate`. Unknown revisions fail;
pending/unsupported policies produce no usable challenge or invented expiry.
Presented challenges contain two server-generated random UUIDs (244 random bits);
only their SHA256 commitment is stored. Plain challenges are returned once and
must not be logged. An identical acceptance retry is deliberately rejected; an
aborted transaction leaves the challenge unused.

## Authorization, lock order and authority

`ceopro_consent_owner` owns the new functions. `ceopro_consent_service` receives only
the four new command EXECUTEs. Both install as restricted NOLOGIN/NOINHERIT
roles, with no role memberships. No credential or environment wiring exists.
Existing runtime identities receive no new grants, memberships or SET ROLE paths.
The service has no direct INSERT on A1 or B4 consent tables. The owner has narrowly
scoped reads/inserts and column UPDATE privileges needed for row locks, with no
exposed mutation command. It cannot publish policy revisions or call B4 confirmation.
Functions revoke PUBLIC EXECUTE and use `pg_catalog,public,pg_temp` search paths.

The dedicated future collection boundary must authenticate the user before setting
server-owned tenant/user context. A DTO or a spoofed GUC on an existing runtime
socket cannot pass the function ACL, exact `session_user` check and repository check.
A1 itself supplies no HTTP/authentication endpoint or secret resolver for that boundary.

Commands lock reservation → existing presentation before decisive authorization.
READ COMMITTED is mandatory. The authorizer takes the same TRY platform-authority
advisory edge as B4, then company → user → membership `FOR SHARE NOWAIT`, and
rechecks active-principal/billing role after blocking reservation/presentation locks.
SHARE protects non-key status/role updates as well as removal through COMMIT;
KEY SHARE alone would be insufficient. Busy/revoked authorization fails closed.

B4's legacy person/tenant/Customer/subscription/billing-tenant/reservation/observation
order is unchanged. A1 acquires none of those upstream blocking locks or an
observation lock. Its authorization edges fail without waiting, so they do not
introduce a reverse blocking cycle. Native tests coordinate actual lock waits by
backend PID and `pg_blocking_pids`, including demotion during a reservation wait.

**Withdrawal/supersession after association is explicitly unsupported.** B4 does
not yet consume revocation evidence. A1 rejects that portion rather than recording
a withdrawal while leaving its B4 consent usable. Exact repeat association after
B4 has confirmed/released the reservation is also outside the pending-reservation
command contract. These are coordinated cutover dependencies, not enabled features.

## Verification evidence

Command, from `backend` using the checkout's existing interpreter:

```powershell
..\.dev\venv\Scripts\python.exe -B -m scripts.verify_recurring_consent --isolated-local
```

Final evidence: `.dev/evidence/phase1-3d-a1/e76bb592d6f6/` (`result.json`,
`pytest.log`, `junit.xml`). Source hashes and exact selected modules are recorded.

| Gate | Result and scope |
| --- | --- |
| Fresh migration chain | PASS: 171 files, full runner under disposable installation superuser; repeat runner applies zero files; all new evidence/policy tables empty. |
| Populated upgrade | PASS: full 170 baseline plus A1 → 171 under real password-authenticated non-superuser/non-BYPASSRLS fixture installer. Historical paid/trial/Checkout/financial fingerprints preserved. |
| Installer boundary | PASS for A1 SQL-file executor and ledger transaction only. Fixture owns public schema/tables, has CREATEROLE, temporary A1-owner membership and explicit active-principal grant option. The fixture membership is removed afterward. This is not full production least-privilege installation. |
| Effective existing authority | PASS: existing runtime role attributes, existing public function EXECUTE and table-operation privileges identical before/after upgrade. |
| Migration rollback | PASS: injected division-by-zero rolls back A1 tables/DDL and leaves the 170 ledger unchanged. |
| Native security | PASS: FORCE RLS, cross-tenant filtering, real password role identities, actual direct-write/command/SET ROLE denials, no PUBLIC command access, no new role memberships or confirmation authority. |
| Consent outcomes | PASS: full terms/digest, USD commercial vs JOD analysis currency, exact revision/language, unknown/incomplete policy, actor/tenant/challenge/digest mismatch, expiry, membership removal/suspension, company suspension, user disablement and billing-role demotion. |
| Concurrency/atomicity | PASS: coordinated duplicate acceptance, supersession versus acceptance, authorization held through COMMIT, uncommitted demotion fails NOWAIT, demotion during reservation wait is rechecked, acceptance rollback and injected bridge-insert failure rolls back B4 consent. |
| Association | PASS: original-binding retention after selection changes, wrong tenant/binding/Checkout/terms/initiator/Customer-operation lineage, a different Customer blocked by composite FKs, Checkout preparation closing the acceptance window, invalidated acceptance, exact repeat, conflicting repeat, immutable acceptance/bridge/B4 facts and zero provider-observation/access writes. |
| Selected regressions | PASS: 1,077 tests, zero failures/errors/skips; includes B1–B4, Customer operations, restricted reconciliation roles, standard/custom Checkout/webhooks, trial/downgrade/paid-evidence accounting and native signup/email/workspace/local-trial compatibility. |
| Dormancy | PASS: AST import boundaries; no active source imports the module. No provider/config resolution, new API/UI, entitlement/Credit/subscription/observation mutations or confirmation EXECUTE grants. |
| Git | PASS: unchanged branch/HEAD, no historical SQL edits or active production source edits; `git diff --check` passes. All eight manifest files remain uncommitted. |

Earlier runs are retained honestly: the first fresh migration passed before a
fixture membership cleanup assertion failed; the next run had 1,069 passes and
two outdated migration-count/import-allowlist failures. Those assertions were
updated narrowly. The expanded pre-final run `fd1eaee4836a` passed 1,075 tests.
No synthetic acceptance is evidence of real customer consent or Stripe acceptance.

The verifier independently checks a local Docker endpoint, new unique labelled
containers, loopback-only random ports, tmpfs storage/no volumes, PostgreSQL major
17, a pristine cluster and empty newly created test databases before migrations.
It clears inherited application/provider secrets, forbids non-test libpq DSNs and
external sockets/DNS, doubles provider traffic, and stops its PG/Redis containers.
It never silently reuses a container or accesses the normal application database.

Runtime status from the documented `dev.ps1 status`: the target checkout's existing
PostgreSQL container was stopped, API unavailable, and other listed test dependencies
stopped. No normal services were started, restarted or migrated. Fresh browser/UI
execution was not performed; no UI changed. Test containers are stopped after proof.
Warnings from the selected suite are retained in `pytest.log`; they did not produce
test failures and are not treated as external-provider acceptance.

## Remaining owner decisions and A2/integration gates

* Approve agreement identity/revision/content, cancellation and renewal disclosure,
  trial-start rule, retention, English/Arabic copy and language versions, eligible
  launch billing periods and explicit TEST/LIVE scope. No final copy or policy was
  invented. Approved revisions must be installed through separately approved work.
* Build and review the authenticated pre-Checkout collection boundary: trusted actor
  derivation, CSRF/session protections, challenge delivery/no logging, presentation
  rendering and genuine explicit user action. Publish no UI merely from these DTOs.
* Coordinate B2 supported-capability and recurring-readiness evidence, pre-Checkout
  acceptance sequencing, durable Customer/Checkout identities and B3 trusted reads.
* Review downstream withdrawal/supersession, retry/read lifecycle and B4 consumption,
  including already-associated or confirmed consent. Do not activate the new service,
  attestor or confirmer identities until that coordinated cutover is approved.
* Separately cut over signup/workspace/standalone local trial issuance and legacy
  webhook activation paths. A1 deliberately leaves those existing authorities intact.
* Run the full production restricted installer including post-install catalog/RLS
  gates, hosted CI, authenticated browser/RTL flows, genuine provider TEST acceptance
  and complete end-to-end cutover tests. These remain NOT EXECUTED/unverified gates.

A1 is ready for a **fresh security review of this dormant foundation** after the
recorded local checks. It does not solve provider readiness, establish production
readiness, authorize a TEST/LIVE launch, or enable trial/subscription/access grants.

## Final Git status and complete change summary

```text
 M backend/tests/billing/test_payment_webhook_decoder.py
 M backend/tests/billing/test_verification_observations.py
?? backend/scripts/verify_recurring_consent.py
?? backend/src/ai/billing/recurring_consent.py
?? backend/src/infrastructure/database/migrations/20261205000000_recurring_consent_foundation.sql
?? backend/tests/billing/test_recurring_consent.py
?? backend/tests/billing/test_recurring_consent_db.py
?? docs/RECURRING_CONSENT_FOUNDATION.md
```

Six new files and two existing test-file updates; 1559 insertions and one deletion
including untracked file contents. Changes add five protected tables, seven consent
functions (four callable commands plus authorization/locking/immutability helpers),
one reservation composite key, scoped policies/ACLs, the dormant repository, test
coverage, isolated verifier and this report. Existing test edits are exactly the
migration count and one dormant import-allowlist entry. No staged changes. No
historical migration, existing production implementation, provider configuration
or application database changed. The initial integration checkout used for
temporary staging was restored to its original clean Git state.
