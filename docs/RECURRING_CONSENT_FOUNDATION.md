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

## Phase 1.3D-A2 - dormant evidence progression

Implemented 2026-11-08 (Asia/Amman), starting from clean
`integration/main-consolidation` HEAD
`45b26f149c5849d371506dcc0b99b1d8b32926be`. No separate 1.3D cutover
assessment was found in the current documentation. A1 low-priority cleanup
findings and all 171 historical migrations are unchanged.

**Root cause:** B4's replacement B3 recorder compared the latest two observations
with exact `billing_confirmation_semantic` equality. The attestor compared every
historical observation with the latest using that same equality. Only the payment
method retrieval timestamp was ignored. Missing facts becoming known, Checkout
open becoming complete, and pending setup becoming ready therefore poisoned
ordinary progression despite unchanged identity/commercial facts.

**Change manifest:**

* `backend/src/infrastructure/database/migrations/20261206000000_trial_evidence_progression.sql`:
  forward migration 172 adds a restricted immutable comparison helper and replaces
  only the B3 recorder/B4 attestor definitions. Same original operation/request,
  binding, protected roles, row-lock ordering, freshness/claim fencing and exact
  latest-provider-facts comparison remain. No new runtime grant or role is added.
* `backend/src/ai/billing/stripe_verification.py`: versioned dormant reader can
  retrieve a card from the original subscription-linked, successful off-session
  SetupIntent when a default is absent; Customer, mode, object and method checks
  still apply. It does not discover/adopt arbitrary same-Customer SetupIntents.
* `backend/tests/billing/test_evidence_progression_db.py`: focused native
  progression, material identity/financial contradictions, source refinement,
  repeated/stale/concurrent reads, scope, capabilities and consent/rights checks.
* `backend/tests/billing/test_stripe_verification.py`: focused reader progression
  and negative correlation tests; one existing absent-default expectation updated.
* `backend/tests/billing/test_verification_observations.py`: count 171 -> 172 only.
* `backend/scripts/verify_evidence_progression.py`: focused disposable verifier,
  reusing A1's reviewed socket/libpq guard and local Docker endpoint predicate.
* This existing report records A2 evidence and remaining gates.

Trial-only progression permits missing facts to fill, explicit unknown capabilities
to resolve, open -> complete, pending -> trialing, and unknown/attached/pending setup
readiness to refine toward confirmed reusable authority. An unresolved subscription
source may refine to a correlated setup source; an already-positive setup or payment
identity cannot change. Known Customer/Checkout/subscription/payment identities,
terms, trial/period dates, settlement and cancellation facts cannot change or vanish.
B3 compares **all** earlier rows, retains every stored observation/digest, preserves
sticky conflict flags and rejects out-of-order trial reads. Subscription-observation
comparison is unchanged. B4 still requires the exact latest provider facts, live
claim, trusted local consent, all nine supported capabilities and financial checks;
its history comparison now admits the explicit refinements. New evidence continues
to fence old attestations through claim/version and full history digest checks.

**Executed verification:** clean-environment offline Stripe/contracts/B3/B4 boundary
selection: **424 passed**, four existing syntax warnings. Command from `backend`:

```powershell
..\.dev\venv\Scripts\python.exe -B -m scripts.verify_evidence_progression --isolated-local
```

Final native evidence: `.dev/evidence/phase1-3d-a2/05f3b41bae93/`
(`result.json`, `pytest.log`, `junit.xml`): **125 passed, zero failures/errors/skips**.
Fresh PG17 chain 172, populated paid/trial 171 -> 172 upgrade, replay, injected DDL
rollback, all existing public-table fingerprints, existing runtime EXECUTE ACLs and
role attributes passed. Real password sessions exercised B3/B4, selected A1 ACL/RLS
checks and A2 behavior. Owned PG17/Redis containers used random loopback-only ports,
tmpfs/no persistent volumes, scrubbed credentials and no image downloads; both were
stopped. The first run is retained at `36754a515146`: migration/ACL checks and 87
existing tests passed, while 30 A2 cases had missing imported fixture dependencies;
test wiring was corrected before the final passing run. A1's full 1,077-test evidence
was reused, not rerun. Unstaged and new-file whitespace checks passed.

**Still blocked:** when `pending_setup_intent` disappears, no durable trusted
subscription-to-SetupIntent recovery association exists in these foundations.
An attached/default card or metadata cannot fill that gap: readiness stays
unconfirmed. Actual Stripe TEST acceptance must establish supported API shapes,
SetupIntent lifecycle/correlation and merchant-specific recurring capabilities;
this implementation still emits PENDING for trial Checkout, advertises only proven
authoritative reconciliation, and never fabricates VERIFIED or all nine capabilities.
Provider readiness remains distinct from local consent and confirmation authority.
Unknown commercial/legal policy is not invented. A1 authenticated collection,
post-association withdrawal, legacy local-trial/webhook cutover, browser/RTL and real
provider acceptance remain activation gates. Fresh/upgrade installation here used a
disposable superuser; full production restricted runner/post-install validation
remains an unverified merge/release gate. No provider API calls or normal application
services were started. A2 is ready for focused security review, remains dormant and
uncommitted, and does not authorize runtime activation.

## Phase 1.3D-B1 - dormant backend coordinator

Implemented 2026-11-08 (Asia/Amman) from clean HEAD
`e46ad34d76d31b3fb4300ce7c71faba6addc5039` on
`integration/main-consolidation`. No commit or runtime registration/enable flag.

Changes: `backend/src/ai/billing/trial_coordinator.py`, new focused
`backend/tests/billing/test_trial_coordinator.py`, this report, and narrowly scoped
coordinator allowlist additions in `test_payment_webhook_decoder.py`,
`test_provider_verification_contracts.py`, `test_verification_observations.py`.
The new import-boundary test forbids all other source from importing the coordinator.
Active signup/trial/Checkout/webhook/onboarding source, A1/A2 implementations and all
172 migrations are unchanged. No new schema, credentials, permissions or contracts
in `payment_contracts.py` were needed.

The internal coordinator composes existing reservations, A1 presentation/association,
durable Customer resolution and B3 observation commands. Stable server-owned journey
UUIDs are mandatory; retries reuse original frozen terms/binding. Customer UUIDs are
deterministic per tenant/original binding, observation UUIDs per attempt, presentation
UUIDs per attempt/policy. No replacement identity or provider default is chosen.
`status` reconstructs persisted checkpoints without provider calls, collection or
mutation. `advance` rechecks its integration boundaries instead of treating status
as authorization. The read-only reservation view uses existing setup/RLS privileges,
active billing membership and the original initiating user. No new authorization
or lock protocol replaces the existing commands; repository transactions end before
provider work. The protected consent reader must also end its transaction on return.

Consent collection/acceptance is absent. An absent protected consent reader blocks
advancement; its future trusted snapshot is an immutable CustomerPayload containing
exact A1 acceptance/presentation/invalidation rows, not request JSON or a Boolean.
The coordinator validates original actor/tenant/attempt/binding/frozen terms. Existing
A1 association performs the authoritative post-Checkout validation. Presentation
challenges remain one-time; deterministic duplicate presentation fails closed rather
than inventing a recovered challenge. Durable Customer work delegates to the existing
resolver; ambiguous Customer outcomes remain pending with the same operation identity.

**Checkout sending remains an explicit B2 block:** current generic Checkout encoding
lacks a bound approved trial-policy adapter and the existing submission marker alone
cannot elect one external sender. B1 has no Checkout sender/replay method. An ambiguous
submission with no recorded session stops before any Customer/provider work; it never
creates a replacement Customer or Checkout. Known sessions can be read through the
original binding and exact B3 context; A1 association precedes the claim/provider GET.
Conflicts, stale claims, authorization errors and insufficient readiness/capabilities
remain pending/blocked. Provider-emitted VERIFIED trial evidence or local consent is
rejected. Even complete synthetic provider prerequisites stop at a trusted-confirmation
handoff. B1 imports no B4 attestor/confirmer and cannot grant subscriptions, entitlements
or Credits. Existing confirmed state is reported only as a historical B4 checkpoint.

Executed tests (all provider/DB interactions mocked): initial seven-module targeted
selection **307 passed**, six existing syntax warnings. After the read-only status
addition, **33 coordinator tests passed**, one existing syntax warning; unaffected
regressions were not rerun. Coverage includes stable identities/terms, ambiguity,
consent/scope conflicts, one-time presentation response limits, original binding,
permission/stale-claim refusal, non-verified outcomes, absent activation and dormant
imports. New read-only SQL was source-reviewed and tested with DB-API doubles; native
restricted-role coordinator acceptance is not claimed. No DB schema changed, so no
migration or disposable-database suite was run. Earlier accepted A1/A2 native security
and migration evidence is reused. Whitespace checks include the new files.

Exact B2 integration dependencies (all remain blocked until separately implemented):

* Authenticate tenant/actor, issue/persist the server-owned journey UUID, own scoped
  repository factories and preserve that UUID on lost responses. Never route client
  fields into service GUCs, protected consent snapshots or gateway selection.
* Approve legal/language/policy versions, explicit collection/session/CSRF protections,
  protected A1 read/retry lifecycle and withdrawal/supersession fencing. Implement the
  consent reader with current authorization/validity checks and atomic consent validity
  at future dispatch/confirmation; a preflight read alone is insufficient.
* Supply a bound Checkout encoder with approved trial-start/return-URL/commercial
  policy, protected single-sender dispatch election, frozen transport persistence and
  exact ambiguous-outcome reconciliation. Do not auto-resubmit after submission or
  adopt a different Customer/session. Existing Customer provenance and changed account
  contact data require explicit review; existing SQL can also block first Customer
  creation if selection changed after reservation, rather than switch its binding.
* Coordinate B3 recovery/claims and a separately authorized B4 handoff with complete
  trusted provider evidence, original consent, current authorization and withdrawal
  fencing. Do not fabricate VERIFIED, local consent or all nine capabilities.
* Independently prove durable SetupIntent correlation after its pointer disappears,
  real Stripe TEST recurring readiness/capabilities, legacy webhook fallthrough/local
  trial cutover protection, native coordinator/RLS acceptance, browser/RTL flows and
  the full production restricted installer. B1 resolves none of these release gates.


## Phase 1.3D-B2a - dormant customer status and terms preview

Implemented from clean `8664da96995cd4ea54826b2943a71c4fc58e56e7` on
`integration/main-consolidation`. Changes remain uncommitted. Both new gates
remain off by default; no configuration was enabled:
`RECURRING_JOURNEY_PREVIEW_ENABLED` (backend, explicit `true` only) and
`VITE_RECURRING_JOURNEY_PREVIEW_ENABLED` (frontend build, exact `true` only).

`GET /billing/trial-journeys/{operation_id}` authenticates through the existing
JWT/revocation/current-principal boundary. The exact UUID is only a lookup key;
there is no creation, latest-operation discovery, tenant override or client terms.
It reuses B1's unchanged reservation/Checkout SELECT: current active billing
membership (owner/admin/accountant), original initiating user, tenant RLS and
original binding. Another tenant or actor, demotion, removal or suspension hides
the row. Authorization is checked at the read snapshot; this is not a locked
preflight authorization for a later mutation. No new lock protocol was added.

A strict read-only `ceopro_billing_setup` socket has no administrative fallback,
uses the existing fixed-role verifier, and decodes numeric JSONB as Decimal.
It uses existing SELECT privileges; no role, ACL, SECURITY DEFINER function,
checkpoint SQL, migration or runtime EXECUTE grant changed. All 172 migrations
and the B1 coordinator source remain unchanged. The scoped socket is closed
on success/failure. The response uses the coordinator's single captured read,
whitelists persisted plan/payment currency/renewal amount/interval/trial duration,
and compares them with the reservation columns. No binary-float monetary
conversion, current catalog/provider selection, analysis currency, provider IDs,
raw payloads, challenges, consent or confirmation evidence are returned. Success
responses prohibit caching. Missing credentials/infrastructure fail closed.

The onboarding payment page adds only a default-off, read-only panel and an
optional `trial_operation` UUID selector. It has no action buttons or issuance
logic. Existing plan selection, signup, local-trial, Standard/Custom Checkout,
webhooks and onboarding completion remain unchanged while disabled. English and
Arabic/RTL follow the existing i18n provider. Query keys include tenant, actor and
exact operation; cancellation is forwarded, retries disabled, inactive data is
not retained, and refresh/error states hide old terms.

`eligible` means **reserved terms available for review**, displayed as "Ready for
terms review"; it is not current purchase eligibility, consent or access authority.
Known or ambiguous Checkout identities display pending verification. Persisted
Checkout expiry displays expired; released/historical-confirmed checkpoints stay
blocked. Scope/frozen-term contradictions display conflict without terms. No TTL,
agreement version, legal text, quantity or trial-start policy is invented.
Protected Customer/A1/B3 status readers are deliberately not wired: this projection
covers reservation/Checkout checkpoints only. A known session remains pending even
if protected evidence later becomes ready or conflicts. B2b requires an explicitly
authorized, narrow status projection before exposing those additional facts.

Changed files: `backend/src/ai/db.py`, `routers/billing.py`, new
`routers/trial_journey_preview.py`; `backend/tests/billing/test_trial_coordinator.py`
(exact read-only import exception), new `test_trial_journey_preview.py`;
`frontend/src/features/billing/api/trialJourneyApi.js`,
`components/TrialJourneyPreview.jsx`, `pages/OnboardingPaymentPage.jsx`;
`frontend/src/assets/locales/{en,ar}.json`,
`frontend/tests/trialJourneyPreview.test.mjs`,
`frontend/tests/browser/trial-journey-preview.mjs`, and this report.

Verification: focused offline backend selection initially **104 passed** (four
existing syntax warnings); the subsequently added missing-credential HTTP test
and renamed import guard passed **3 final focused checks** (one existing syntax warning). Existing offline
Standard/Custom Checkout regressions: **14 passed**, four native-only cases
intentionally deselected. One initial Custom Checkout failure lacked the public
origin in the scrubbed test environment; only that case was rerun with a synthetic
loopback origin and passed. Frontend selected Node tests: **18 passed**, including
locales, existing Checkout/local-trial API contracts and onboarding routing.
Offline Chromium acceptance: **10 checks passed** across English and Arabic,
using the real panel/query/client with all network requests intercepted; no API,
provider or database was contacted. Changed frontend files passed ESLint.
Evidence: `.dev/evidence/phase1-3d-b2a/3c1d364d7c26/result.json`.

No new SQL or migrations require a native run. Reused native proof:
`.dev/evidence/phase1-3d-b1-review/79603e501939/result.json` (29 checks,
172-migration disposable PG17 fixture, actual restricted-password setup/app
identities, FORCE RLS, wrong actor/tenant and revocation/suspension denial).
Its checkpoint source SHA-256 still matches. The new read-only connection factory
and exact Decimal decoder are tested with doubles, not newly claimed native
acceptance. `dev.ps1 status` reports Docker unavailable; no services were started.

B2b/cutover remain blocked on server-owned operation issuance/recovery, approved
legal/language/trial-start and return-URL policies, authenticated consent collection
and withdrawal fencing, scoped protected status reads, single-sender bound Checkout
dispatch and ambiguous recovery, authorized B3/B4 handoff, durable SetupIntent
correlation after the pending pointer disappears, real Stripe TEST recurring
readiness/capability acceptance, legacy webhook/local-trial cutover protection and
full production restricted-installer verification. This GET/panel resolves none
of those activation gates and never creates consent, VERIFIED evidence, Customer,
Checkout, subscriptions, entitlements or Credits.
