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


## Phase 1.3D-B2b-2 - dormant authenticated consent and withdrawal

Implemented from clean `fcecb9b8b6535bd6c8e93b11c10312cf9f44f881` on
`integration/main-consolidation`; all changes remain uncommitted. No Downloads
files were accessed, copied or published. No policy revisions/text were approved
or seeded, no provider was contacted and no normal service was started.

Owner-approved business decisions are recorded as requirements: B2B only;
14-day eligible-business trial; explicit advance consent for automatic paid
renewal; paid cancellation stops future renewal and preserves paid-period access;
refund-review requests within 14 days of the first paid charge, without a refund
guarantee and subject to applicable law and seller/provider obligations; initially
unchecked recurring-consent control plus any additional provider-required consent.
These decisions do not establish legal copy, current eligibility or provider readiness.

New `authenticated_consent.py` composes the existing reservation and protected A1
repositories. Current authenticated tenant/actor must own the exact reservation,
Checkout and original binding. It requires a trusted B2B eligibility attestor and
an immutable approved policy catalog, a 14-day frozen duration, matching language,
full agreement-text SHA256, installed A1 approved revision/disclosure/trial-start/
retention references and approval reference, plus operator/refund versions.
The catalog's approval reference MUST pin the entire immutable bundle. DTOs and
client Booleans are not an approval source; no runtime implementation of this
catalog or business attestor is installed. Legal/language versions, operator
information, trial-start rules and required disclosures remain unapproved.

Default-off routes below `/billing/trial-journeys/{operation_id}/consent` provide
GET `preparation` and JSON POST `present`, `accept`, `withdraw`. They use existing
JWT, fail-closed session revocation/current-principal validation and B2a's initiating-
actor/current-billing-role read. Both the B2a preview gate and new
`RECURRING_CONSENT_ENABLED` must be explicitly true. Request models reject actor,
amount, terms, timestamps and extra fields; acknowledgement must be a strict
Boolean true. SecretStr masks challenge representations. Responses disable caching.
Only a future trusted `app.state.recurring_consent_factory(ctx)` context manager
may supply scoped repositories/catalog; no factory, service login, credential
resolver, role switch or runtime consent-writing/confirmation grant is installed.
Missing approval/factory blocks actual presentation/acceptance. Withdrawal requires
the protected service boundary but does not require new legal approval.

A1 owns random challenge creation/hash-only persistence, expiry, database timestamps,
immutable full terms/digest, stabilized billing authorization and one-time acceptance.
Presentation IDs reuse B1's deterministic operation/policy UUID; acceptance UUIDs
are deterministic per presentation. Lost-response/duplicate acceptances fail closed;
no automatic new presentation, accepted identity, Customer or Checkout is created.
The new protected `billing_consent_read` returns exact scoped evidence/invalidation
without challenge or challenge digest. No discovery/latest-operation endpoint exists.

Forward migration `20261207000000_consent_withdrawal_fencing.sql` is migration 173,
after A2; all 172 historical migrations remain unchanged. It appends no policy or
commercial data and retains all accepted/associated/attested evidence. Invalidation
now locks reservation FOR UPDATE, then presentation, then uses A1's existing
NOWAIT/TRY authorization stabilization. Matching withdrawal retries return the
original invalidation; conflicting retries fail. Invalidated presentations cannot
be accepted or associated again, including exact association retries.

New SECURITY DEFINER insert triggers fence A1-origin B4 attestations/confirmations.
They check current tenant and invalidation while retaining a reservation SHARE
lock through COMMIT. Attestation already owns its observation row, so the new
reservation edge is NOWAIT: it cannot introduce a blocking reverse lock cycle.
Confirmation already holds the exclusive reservation lock. Withdrawal first denies
consumption; confirmation first completes atomically and later withdrawal returns
55000, requiring subscription cancellation instead of rewriting historical consent.
A trigger refusal rolls back all provisional subscription/trial/entitlement writes
in the existing B4 transaction. Exact reads/retries of an already recorded historical
attestation are not new authorization; confirmation still fences it. Pre-A1 trusted
B4 evidence keeps its existing contract; no new writer for that authority is added.

The new helper revokes PUBLIC EXECUTE, uses `pg_catalog,public,pg_temp`, and is owned
by the existing NOLOGIN consent owner. Only that owner receives a tenant-scoped
attestation SELECT policy; only the existing dormant NOLOGIN consent service receives
the new read EXECUTE. Ordinary runtime and attestor/confirmer EXECUTEs are unchanged.
No provider work occurs in these transactions. Full production restricted-installer
verification remains unproven; isolated migrations use fixture installation authority.

The onboarding page adds `TrialConsentPanel`, off unless both
`VITE_RECURRING_CONSENT_ENABLED` and the existing preview build flag are true.
It displays persisted payment terms, explicitly lists eight missing approval areas,
and starts its labeled checkbox unchecked/disabled until an approved presentation
exists. Only exact presentation/challenge/acknowledgement fields are submitted.
Tenant/actor/operation/language isolate query and UI state; challenges stay in memory.
English/Arabic/RTL and local consent versus provider readiness/cancellation are
separate. No legal pages were added. Existing legacy Checkout remains unchanged;
its future coordinated cutover must enforce the new consent before dispatch.

Focused verification (no historical broad suite rerun): **177 passed** in the
six-module auth/A1/B4/native selection; one new lock fixture correctly failed because
the consent-service role cannot directly lock tables. Using the disposable installer
as that test's lock holder, its **one targeted retry passed**. Thus all 178 selected
cases passed across those runs; one unrelated signup compatibility case was explicitly
deselected. Initial collection failure from a misread UTF-8 test marker was corrected
before that run. The directly affected migration-count guard also passed separately.
Existing warnings are retained in evidence; an undersized synthetic JWT secret in
an earlier run was enlarged in the final verifier. No runtime implementation fix
was needed after the 177 passing cases.

Fresh **173** install/replay, populated legacy-trial **172 -> 173** upgrade/replay,
injected rollback, unchanged effective existing runtime EXECUTEs, no new runtime
function grants, NOLOGIN/membership checks and historical trial preservation passed.
Native tests include real restricted password identities, FORCE RLS/ACLs, revoked
roles, expiry/replay, reservation/binding/terms, synchronized acceptance/withdrawal
in both orders via pg_blocking_pids, associated withdrawal and exact-reassociation
refusal, new attestation denial, confirmation rollback, post-confirmation cancellation
boundary and recoverable NOWAIT. Synthetic provider/legal evidence is explicitly
not real customer or Stripe acceptance. Containers were unique, loopback-only,
tmpfs, --pull=never and stopped; inherited credentials were cleared and the accepted
socket/libpq network guard reused. No application/shared database was accessed.

Evidence: `.dev/evidence/phase1-3d-b2b2/bbbd6bbceca3/` (177 passed + fixture failure)
and `3712780d80b7/` (corrected single-case PASS, fresh/upgrade/rollback PASS and
migration-count log). Command: from backend,
`python -B -m scripts.verify_authenticated_consent --isolated-local`;
`--select tests/billing/test_consent_withdrawal_db.py::test_busy_attestation_fence_is_nowait_and_recoverable`
reproduces only the corrected test. Frontend: **11 Node tests passed**, **8 offline
Chromium checks passed** (English/Arabic missing policies, frozen amount, initially
unchecked control, synthetic approved acknowledgement and withdrawal; all requests
intercepted), and changed-file ESLint passed after removing one unused test constant.

Changed source: new collection adapter/router; A1 repository read; billing router
registration; forward withdrawal migration; consent panel/API and onboarding insert;
English/Arabic labels. Tests: new collection/native/browser/API cases, narrowly scoped
consent import exception, new withdrawal expectation and 172 -> 173 count assertion;
new isolated verifier and this existing report. No signup, active trial/Checkout/
webhook/subscription/Credit/entitlement command or B1/A2 implementation changed.

B2b-3/release gates: approve/install/pin the full immutable legal/operator/language/
refund/retention/trial-start bundle; prove B2B eligibility; review dedicated collection
service provisioning/factory/session lifecycle (no activation here); complete safe
presentation/challenge/lost-response recovery; bind protected status reads and atomic
consent/withdrawal validity to future dispatch; single-sender Checkout with ambiguous
recovery and withdrawal coordination/remote compensation; preserve additional provider
consent; prove durable SetupIntent correlation and genuine Stripe TEST capabilities;
review trusted B3/B4 handoff, legacy webhook/local-trial cutover and full restricted
production installation. Implement paid cancellation/refund review through approved
existing provider/customer workflows, not this pre-confirmation invalidation command.


## Coordinated customer journey integration - 2026-11-08 (uncommitted)

Baseline: `integration/main-consolidation`,
`9b24a9279cae0efcac66de04aa03e305ca37db90`. This is executable dormant
integration, not production activation. No policy bundle, service factory,
credentials, LOGIN, frontend flag or runtime attestor/confirmer is installed.

The connected synthetic Standard-plan path now executes reservation -> actual A1
presentation/acceptance -> durable Customer -> one elected original-binding Checkout
submission -> immutable authenticated B3 receipt and fresh provider observation ->
A1 association -> B4 attestation/atomic confirmation -> frozen access and exact trial
expiry. Mock provider/legal fixtures are explicitly synthetic and prove no merchant,
Stripe or legal acceptance. Registration/email/company creation reuse the accepted
identity system; native tests separately verify creation-time cohort selection.
The HTTP journey additionally requires a verified account, current tenant principal,
initiating actor and billing authority. It accepts plan/period selectors, a retry nonce
and language, never actor, price, provider identity, commercial terms or acceptance time.

`RECURRING_JOURNEY_ENABLED` defaults off. Only companies created while explicitly
selected are marked by the immutable `companies.subscription_journey_required` flag.
Existing companies remain in their original journey; changing the application flag
cannot clear or enroll an existing company. Pending email verification and workspace
creation set the cohort in the company-creation transaction. Automatic local trials,
legacy Checkout/Custom actions and legacy subscription/assignment writers are fenced
for that cohort. Legacy accounts keep their existing flows. Even the optional legacy
unassigned-default plan cannot grant access to a new-cohort company.

The new authenticated `/billing/trial-journeys` POST derives the operation UUID from
server tenant/actor context plus the client retry nonce. Exact retries preserve the
original reservation/binding/terms; conflicting plan changes fail. `/progress` is
read-only with no provider calls; `/advance` performs explicit work, `/cancellation`
stops supported future renewals, and `/cleanup` performs withdrawn-Checkout recovery.
The context-managed `app.state.subscription_journey_factory(ctx)` remains absent.
When explicitly installed in an authorized environment, its collection also serves
the existing consent routes. No privileged connection fallback or credential resolver
was added. Existing preview/consent gates remain required for those endpoints.

Checkout payloads and idempotency keys are frozen before a transactional one-time
sender election. Authorization/withdrawal are rechecked before POST; every command
commits before provider work. After any submission marker, all retries are GET-only,
even if no object is found or a sender crashed before POST. Customer recovery retains
its accepted earlier no-resubmission contract. Returned sessions must match the
original bound Customer, operation and metadata. Persisted transport is revalidated
against frozen price/quantity/trial/Customer/binding/key before sending. Return URLs
carry original operation/plan/period selectors and never confer rights. Authoritative
Checkout expiry is durable and cannot cause another submission. The Stripe journey
adapter rejects LIVE construction and supports no hypothetical second provider.

SetupIntent correlation reuses an earlier immutable authoritative observation of the
**same original operation, binding, Customer and exact subscription**. After
`pending_setup_intent` disappears, a fresh bound GET must still prove successful
`off_session` setup, matching Customer and payment method. An attached card alone is
insufficient. If no trustworthy earlier association exists, readiness remains pending;
no customer-wide search or inferred link fills the gap. Real Stripe still proves only
its existing supported capability subset; this integration does not mark all nine B4
capabilities supported. Provider observations cannot supply local consent or VERIFIED
trial authority. The local handoff changes only authenticated consent fields, and B4
still validates complete capabilities, financial facts, immutable history, freshness,
eligibility, exclusivity, authorization and withdrawal atomically.

New-cohort webhooks are classified before legacy event handling. A marker, persisted
identity match, failed lookup or unavailable trusted reconciler cannot fall through
to legacy activation. Cross-namespace ambiguity quarantines conservatively. The
explicit `JourneyWebhookReconciler` uses B3 immutable authenticated receipts (including
body-digest/time replay checks), fresh observations and the same consent/B4 workflow.
Matching completed-Checkout retries are harmless; changed identity/body fails. Paid
invoice/subscription lifecycle events remain quarantined until a supported trusted
paid-period contract exists, rather than treating provider status as payment proof.
The existing HTTP webhook has no new production reconciler installed. A separate
`POST /billing/trial-journeys/webhook` is connected to the trusted reconciler through
explicit `app.state.subscription_journey_webhook_decoder` and
`subscription_journey_webhook_handler` dependencies, both absent by default. It
requires the feature gate and an original merchant-scoped TEST signing secret;
its decoder reuses the accepted signature decoder, rejects LIVE/wrong-account
notifications and binds every reference to the installed original binding. This
endpoint cannot dispatch legacy processing even on an unknown association. A native
HTTP test verifies the actual SDK signature over original bytes, actual restricted
SQL confirmation, exact replay and invalid-signature refusal. Evidence:
`dc27b6689c29/result.json`; six final decoder/import checks passed in
`offline/bound-endpoint-final.xml`. The remaining native unknown-event receipt check
passed in `590a66ca60ae/result.json`. No bound decoder/handler was installed in a
running application.

Supported cancellation has a durable one-time intent and stable key, retrieves the
original bound subscription, requests only `cancel_at_period_end=true`, rejects
unhandled schedules and changed period boundaries, and recovers ambiguity by GET.
It neither shortens local access nor rewrites confirmed consent/subscriptions. No
refund is promised or automatically issued. Pre-confirmation withdrawal retains A1's
append-only invalidation/B4 fences. Cleanup can find and expire a late **open**
Checkout; a completed Checkout requiring remote subscription compensation remains
explicitly blocked. A paused external sender cannot be fenced by a local deadline.

Forward migration `20261208000000_subscription_journey_dispatch.sql` is migration
**174**, ordered after all 173 historical migrations, which are unchanged. It adds
two FORCE-RLS protected checkpoint tables, cohort/rights fences, a scoped issuer helper,
a dormant consent-service dispatch/cancellation command and an observer history read.
The original Checkout scope guard and historical B4/A1/A2 functions are unchanged.
PUBLIC EXECUTE and inherited default app table-write grants are explicitly revoked.
Existing runtime function EXECUTEs are unchanged; the ordinary webhook role receives
only the new boolean cohort-classification read, never write/confirmation authority.
The new global read owner is NOLOGIN/NOINHERIT/NOBYPASSRLS with no role memberships or
retained schema CREATE. Authorization uses A1 READ COMMITTED, reservation-first locks
and current company/user/membership SHARE NOWAIT plus advisory TRY stabilization.
Provider work happens after commit. B4 locking/withdrawal protection is retained.

English/Arabic onboarding consumes the durable server cohort flag, keeps consent
initially unchecked, uses exact frozen decimal display and separates acceptance,
verification and cancellation. Tenant/actor/operation scope query and UI state.
Confirmed checkpoints refresh the actual subscription projection; browser redirects
cannot grant access. Backend entitlement caches now expire provider trials at their
exact cutoff, and the frontend subscription hook expires cached trial access and
refetches at that instant. Existing paid/legacy commercial calculations are unchanged.

Verification:

- **PASS:** 625 distinct offline cases across focused selections; 48 final targeted
  checks and two final import-boundary checks passed. Five database-only offline
  skips were tested separately in disposable PostgreSQL. An extra selection initially
  lacked PUBLIC_FRONTEND_ORIGIN for one existing test; its targeted configured retry
  passed. Initial implementation/fixture failures remain in private evidence, not
  erased. Existing AST SyntaxWarning messages are retained.
- **PASS:** the final 73-case isolated selection had zero failures/errors/skips,
  including connected synthetic confirmation, missing policy/unchecked consent,
  tenant/role failures, concurrency, withdrawal, ambiguity, frozen transport,
  stale/conflicting evidence, expiry, cancellation, legacy Standard/Custom paid
  activation, paid renewal/failure/recovery, trial downgrade and Credit integrity.
  A subsequent two-case run proved durable webhook receipt/replay fencing and the
  LIVE adapter refusal; the remaining native unknown-event legacy receipt check
  was run separately. These counts overlap and are not additive provider evidence.
- **PASS:** fresh 174, populated 173 -> 174, replay, injected rollback, effective
  existing EXECUTEs, restricted-password roles, RLS/ACL denial and preserved historical
  trial data. Containers were newly created PG17, loopback-only, tmpfs, no volumes,
  --pull=never, inherited credentials cleared, accepted network guard, owned cleanup.
  Full production restricted-installer verification is still **BLOCKED**.
- **PASS:** nine focused Node tests, ten fully intercepted Chromium checks in English
  and Arabic (including actual hook expiry and account-switch disclosure), changed
  frontend ESLint, UTF-8 and whitespace checks. No normal application service was
  started; local application services remained stopped/unavailable.

Commands: from backend, `python -B -m scripts.verify_subscription_journey
--isolated-local` (bounded `--select` also supported); from frontend,
`node --test tests/subscriptionJourney.test.mjs tests/trialConsent.test.mjs
tests/trialJourneyPreview.test.mjs` and `node tests/browser/subscription-journey.mjs`.
Recorded evidence is under `.dev/evidence/phase1-3d-journey/`, especially
`0c1ca3c7d91b/result.json` (73), `22e153647828/result.json` (two targeted) and
`offline/` (offline logs/JUnit). The combined result/manifest records subsequent
checks and final source hashes. No application/shared DB or real provider was used.

Focused same-agent adversarial review checked original identity/price substitution,
role revocation and lock order, receipt/replay ambiguity, default privileges,
legacy activation fallthrough, unassigned access, withdrawal and positive setup
correlation. Identified defects were corrected and targeted checks passed; this is
not an external security audit or production certification.

Launch/acceptance remains **BLOCKED**. Do not enable enrollment or provision the
factories until owner/operator/legal/language/refund/retention/trial-start bundles
are approved, pinned and installed, and B2B eligibility is proven. Further gates:
real Stripe TEST merchant/additional-consent and all required capability evidence;
no-history SetupIntent association; trusted paid-renewal settlement/lifecycle handling;
completed-Checkout withdrawal compensation and abandoned/challenge-loss recovery;
provider cancellation/schedule and authorized administrator recovery acceptance;
Custom cohort confirmation (existing B4 has no Custom trial coverage); restricted
production installation, coordinated permission/webhook cutover, merchant/LIVE
approval. Unsupported Custom journeys fail closed without changing legacy Custom
pricing or paid flows. The supported Standard synthetic journey is executable, but
this is **not yet ready for full authorized Stripe TEST E2E confirmation**.

Exact changed-file manifest (all uncommitted; no staging or commit):

- `backend/scripts/verify_subscription_journey.py`
- `backend/src/ai/billing/authenticated_consent.py`
- `backend/src/ai/billing/journey_policies.py`
- `backend/src/ai/billing/journey_webhooks.py`
- `backend/src/ai/billing/stripe_api.py`
- `backend/src/ai/billing/stripe_journey.py`
- `backend/src/ai/billing/stripe_verification.py`
- `backend/src/ai/billing/subscription_journey.py`
- `backend/src/ai/billing/verification_observations.py`
- `backend/src/ai/billing/webhooks.py`
- `backend/src/ai/core/entitlements.py`
- `backend/src/ai/core/pending_registration.py`
- `backend/src/ai/core/usage.py`
- `backend/src/ai/routers/auth.py`
- `backend/src/ai/routers/billing.py`
- `backend/src/ai/routers/subscription_journey.py`
- `backend/src/ai/routers/trial_consent.py`
- `backend/src/infrastructure/database/migrations/20261208000000_subscription_journey_dispatch.sql`
- `backend/tests/billing/test_authenticated_consent.py`
- `backend/tests/billing/test_contract.py`
- `backend/tests/billing/test_payment_reconciliation.py`
- `backend/tests/billing/test_payment_webhook_decoder.py`
- `backend/tests/billing/test_provider_verification_contracts.py`
- `backend/tests/billing/test_recurring_consent.py`
- `backend/tests/billing/test_subscription_journey.py`
- `backend/tests/billing/test_subscription_journey_db.py`
- `backend/tests/billing/test_trial_coordinator.py`
- `backend/tests/billing/test_verification_observations.py`
- `docs/RECURRING_CONSENT_FOUNDATION.md`
- `frontend/src/assets/locales/ar.json`
- `frontend/src/assets/locales/en.json`
- `frontend/src/features/billing/api/subscriptionJourneyApi.js`
- `frontend/src/features/billing/components/SubscriptionJourney.jsx`
- `frontend/src/features/billing/hooks/useSubscription.js`
- `frontend/src/features/billing/pages/OnboardingPaymentPage.jsx`
- `frontend/src/features/billing/utils/onboardingRouting.js`
- `frontend/tests/browser/subscription-journey.mjs`
- `frontend/tests/subscriptionJourney.test.mjs`


## Unified multi-gateway lifecycle - 2026-11-08 (uncommitted)

Baseline `c3da109cead9cb0c58a07e7ca70c8313e79c9244`, branch
`integration/main-consolidation`. This implements executable, default-off domain
integration. It does **not** make either merchant commercially approved or enable
production payments. No factory, credential, policy, provider approval, feature flag,
LOGIN or runtime attestor/confirmer is installed.

Completed behavior:

- Fixed the confirmed UI LOW finding: durable conflict/expired/blocked/confirmed
  states override cached advance results. English/Arabic browser checks exercise
  both conflict and expiry, and disable Continue. Paid and trial caches expire at
  their exact authoritative access cutoff; redirects never grant access.
- Forward migration **175**, `20261209000000_neutral_subscription_lifecycle.sql`,
  adds original-binding Customer/subscription/price identities and immutable approved
  terms alongside nullable historical Stripe columns. Paddle IDs are never stored
  in Stripe columns. All 174 historical migration files and historical customer data
  remain unchanged. There is no guessed binding/backfill for unscoped legacy rows.
  The existing global one-current-subscription index covers both providers; scoped
  Customer and subscription/tenant/binding composite FKs protect associations.
- B4's initial confirmation retains its complete freshness, original actor,
  eligibility, financial, authorization, locking, global exclusivity, frozen-rights
  and withdrawal checks. Its forward replacement can persist Paddle TEST identities
  only with a separate immutable installation approval reference and the same nine
  independently proven capabilities. No approval rows are shipped. Actual Paddle
  trial verification returns UNSUPPORTED; real Stripe capabilities remain limited.
  Synthetic all-capability fixtures are explicitly **not provider acceptance**.
- `SubscriptionLifecycle` connects bound signed notifications, immutable B3
  receipts/authoritative observations, separate dormant attestor and confirmer
  sockets, atomic lifecycle consumption, frozen assignments and entitlements.
  Confirmed journey webhooks use this consumer when explicitly installed; their
  receipt belongs to the exact subscription operation, never both trial and
  subscription operations. Unsupported non-Stripe events cannot reach legacy
  Stripe processing. Both bound HTTP signature paths reach actual restricted SQL
  in synthetic integration tests, including replay, transient-read retry and bad-signature denial.
- B3 subscription observations may now progress through legitimate state, period
  and settlement changes. All history is retained. Every historical positive
  Customer/subscription/price/currency/amount/interval/quantity/trial fact remains
  consistent. An invoice identity cannot acquire different payment/coverage facts,
  including across an incomplete intervening observation. Older observation times
  are refused. Trial observation rules remain unchanged.
- Shared lifecycle SQL requires the original B4 confirmation and current initiating
  billing authority. It consumes only fresh immutable authoritative observations,
  exact bound receipts and the expected subscription version. Paid access requires
  positive, exact renewal settlement and exact calendar-period coverage (original UTC anchor, including month-end clamping) after the
  original trial; zero invoices, status labels, missing evidence and stale events
  cannot extend access. Reconciliation of an unchanged already paid period can reuse
  its existing cutoff, without extending it. Payment failure denies access;
  verified recovery restores the frozen paid allowances. Cancellation preserves
  already settled access through its cutoff. No Credit balances/usage are reset.
- A FORCE-RLS, append-only neutral settlement ledger feeds the existing invoice
  read alongside historical Stripe payments. It keeps exact amounts and bound
  invoice identities. Unique conflicts are rechecked **after** the index wait so
  a foreign winner hidden by RLS cannot authorize another tenant. Invoice URLs are
  absent where no provider document capability has been accepted. Frozen current
  price preview prefers original approved payment terms over today's catalog.
- Paddle API v1 adapter pins sandbox origin/version, checks `/account` against the
  original merchant, disables redirects/retries, sanitizes failures and rejects LIVE.
  Its HMAC decoder checks original bytes, constant-time digest comparison, a five-
  second timestamp window and duplicate JSON/header ambiguity. Receipt commitment
  excludes delivery-only `notification_id`, retaining the complete immutable event
  core and original signed bytes in the DTO. Provider snapshots are not consent.
- Paddle renewal proof requires the exact subscription/Customer, a completed
  automatically collected recurring transaction, captured payments, precise unit
  price and totals, exact coverage and explicit zero adjustments. The GET requests
  include adjustments; refunds/revisions, taxes, discounts, credits, proration,
  unsupported currencies and multi-item arrangements fail closed. Supported monetary
  parsing is deliberately USD/EUR/GBP only, not invented universal currency support.
- Paddle's elected Checkout encoder uses its transaction API and a separately
  approved/installed merchant payment page. It verifies the bound catalog price,
  original frozen request and returned transaction terms. It invents no provider
  idempotency header or non-creation proof. Unknown transaction recovery returns
  unresolved and never resubmits. Browser navigation additionally requires an
  explicit installed Paddle origin; it defaults absent. This does not install
  Paddle.js, a merchant payment page or a durable Paddle Customer dispatcher.
- Completed-Checkout withdrawal compensation has a protected durable one-sender
  intent. Open Checkout cleanup remains supported. Completed **trial** subscriptions
  may be canceled immediately through a reviewed bound adapter; a lost response is
  recovered by GET without another POST. Local invalidation/history remain intact.
  Paid or scheduled compensation requires review; no automatic refund is inferred.
  Post-confirmation cancellation remains a separate durable action. Paddle uses its
  `effective_from` semantics; it does not inherit Stripe's cancellation payload.

Security/installation boundaries:

- No ordinary runtime EXECUTE, protected write, subscription-confirmation or consent
  authority is added. The only new application table privilege is tenant-scoped
  SELECT on the settlement ledger. Existing NOLOGIN split services receive narrowly
  scoped commands; PUBLIC EXECUTE is revoked, FORCE RLS applies, owners retain no
  schema CREATE, and no credentials/memberships are provisioned. Installation rejects
  pre-existing LOGIN, privileged, inherited/member or schema-replacement role models.
- Lifecycle uses billing-tenant -> subscription -> TRY platform authorization /
  company-user-membership SHARE NOWAIT -> observation locking. Authorization is
  rechecked after blocking locks and stabilized until commit. Attestation and
  confirmation stay separate; all provider requests occur after repository commits.
  Busy/stale claims fail explicitly and cannot select a legacy activation fallback.
- Same-agent adversarial review checked forged consent/VERIFIED authority, original
  binding substitution, stale/rebound invoices, foreign unique-index winners under
  RLS, replay/receipt ownership, acknowledgement-before-consumption, revocation, compensation ambiguity and paid cutoff
  bypass. The receipt-ownership and post-conflict recheck boundaries were tightened
  during implementation. This is not an independent external security audit.

Verification (selections overlap; counts are not additive):

- PASS: 104-case isolated affected selection, including B4, withdrawal, connected
  journeys, both provider identities, concurrency and legacy Standard/Custom paid
  activation, failure/recovery, downgrade and Credits. Subsequent affected selections
  passed 41 and 9 cases. Final ledger/signed-adapter/cross-tenant selection passed six
  cases on the final schema. Evidence under `.dev/evidence/multi-gateway-billing/`:
  `49d415a08b39`, `e954ae9df768`, `c4d88886cca8`, `859a5fdea72a`.
  Subsequent signed retry and unsafe-role checks passed (`96cb0376a069`,
  `03871043c5c5`). Final original-anchor/clamping plus signed adapter-to-SQL
  checks passed three cases (`52105815b346`); final line-total/price consistency
  checks additionally reject contradictory Paddle calculated line items. Final
  signed retry/adapter-to-SQL cases passed (`625b2e52301e`).
  Two final native revocation cases passed (`9408c45e8bf0`): a pending demotion
  prevents stabilization; stabilization first fences demotion until commit, and
  committed demotion denies subsequent consumption. An initial fixture used a
  masked DSN and was corrected; no runtime authorization fix was needed.
- PASS: fresh 175, populated 174 -> 175, replay, injected rollback, effective existing
  EXECUTEs, password-authenticated restricted roles, RLS/ACL denials and preserved
  historical trial. Each verifier owns a new loopback-only PG17 tmpfs container,
  no volumes/provider calls, clears inherited credentials and uses the accepted
  network guard. Owned containers are stopped; failed iterations are retained.
  A negative unsafe-LOGIN installer fixture is rejected before DDL. Production
  restricted-installer installation is **not verified**.
- Offline affected selection: 303 passed; one existing contract fixture lacked
  PUBLIC_FRONTEND_ORIGIN. Its configured targeted retry passed. Final adapter tests:
  **45 passed** (`adapters-final.xml`); the configured 39-case targeted result includes
  that retry (`offline-final.xml`). No provider acceptance is implied.
- PASS: 12 focused Node tests, 16 intercepted Chromium checks (English/Arabic),
  changed frontend ESLint and whitespace. Existing application services remain
  stopped/unavailable. No normal application/shared database was contacted.

Commands: backend `python -B -m scripts.verify_multi_gateway_billing --isolated-local`
(with bounded `--select` for targeted evidence), pytest modules
`test_multi_gateway_adapters.py` / `test_multi_gateway_lifecycle_db.py`; frontend
`node --test tests/subscriptionJourney.test.mjs tests/trialConsent.test.mjs
tests/trialJourneyPreview.test.mjs`, `node tests/browser/subscription-journey.mjs`.

External/release blockers (not simulated success): approved legal/operator/language,
refund/retention/trial-start and MoR/tax policy bundles; real Stripe TEST / Paddle
sandbox merchant/additional-consent and recurring-authority capability acceptance;
durable Paddle Customer submission/recovery consistent with the accepted Customer
contract; no-history Stripe SetupIntent association; installation/acceptance of the
Paddle payment page and webhook destination/secret/account scope; ambiguous Paddle
transaction discovery; Custom initial confirmation/approved amendments (existing B4
is Standard self-serve trial only); tax/discount/credit/proration/other currencies;
refund/chargeback/reversal policy and reconciliation, paid/scheduled withdrawal
compensation and administrator recovery; explicitly approved legacy binding mapping;
full production restricted installation, permission/webhook cutover and LIVE approval.
Existing legacy Custom and Stripe flows are preserved, not certified as Paddle flows.
Neither provider is ready for unrestricted E2E activation from this change alone.

Paddle primary references checked during implementation:
[API/version/sandbox](https://developer.paddle.com/api-reference/about/),
[account identity](https://developer.paddle.com/api-reference/account/get-account/),
[signature verification](https://developer.paddle.com/webhooks/about/signature-verification/),
[transaction creation](https://developer.paddle.com/api-reference/transactions/create-transaction/),
[transaction settlement/adjustments](https://developer.paddle.com/api-reference/transactions/get-transaction/),
[cancellation](https://developer.paddle.com/api-reference/subscriptions/cancel-subscription/).

Changed-file manifest (all uncommitted; no staging or commit):

- `backend/scripts/verify_multi_gateway_billing.py`
- `backend/src/ai/billing/journey_webhooks.py`
- `backend/src/ai/billing/paddle_gateway.py`
- `backend/src/ai/billing/store.py`
- `backend/src/ai/billing/stripe_api.py`
- `backend/src/ai/billing/stripe_journey.py`
- `backend/src/ai/billing/subscription_journey.py`
- `backend/src/ai/billing/subscription_lifecycle.py`
- `backend/src/ai/billing/webhooks.py`
- `backend/src/ai/core/entitlements.py`
- `backend/src/ai/core/usage.py`
- `backend/src/ai/routers/billing.py`
- `backend/src/ai/routers/subscription_journey.py`
- `backend/src/infrastructure/database/migrations/20261209000000_neutral_subscription_lifecycle.sql`
- `backend/tests/billing/test_multi_gateway_adapters.py`
- `backend/tests/billing/test_multi_gateway_lifecycle_db.py`
- `backend/tests/billing/test_payment_webhook_decoder.py`
- `backend/tests/billing/test_provider_verification_contracts.py`
- `backend/tests/billing/test_verification_observations.py`
- `docs/RECURRING_CONSENT_FOUNDATION.md`
- `frontend/src/features/billing/components/SubscriptionJourney.jsx`
- `frontend/src/features/billing/hooks/useSubscription.js`
- `frontend/src/features/billing/utils/onboardingRouting.js`
- `frontend/src/features/billing/utils/subscriptionJourneyState.js`
- `frontend/tests/browser/subscription-journey.mjs`
- `frontend/tests/subscriptionJourney.test.mjs`


## Stripe and Paddle completion work - 2026-11-08 (implementation and review)

Baseline `91862194639661a196489060367efbbf2bc55954`, branch
`integration/main-consolidation`. Default-off; no provider operations, service
credentials, policy approval, permission cutover or runtime activation occurred.

Implemented and verified:

- `PaddleDurableCustomerGateway` implements the accepted Customer protocol and is
  consumed by the existing coordinator, not a second billing authority. Original
  tenant/operation, exact frozen logical/transport request, merchant, TEST binding
  and API version are checked before sending and on authoritative recovery.
  Customer creation accepts Paddle's documented HTTP 201. Discovery scans exact
  email across active/archived pages, matches operation metadata, then freshly
  retrieves the unique candidate. Foreign/archived/contradictory candidates fail;
  zero results remain INCONCLUSIVE. Neither email alone nor a negative search can
  adopt a Customer or authorize another POST. Changed contact data requires review.
- Forward migration **176**, `20261210000000_paddle_customer_single_dispatch.sql`,
  narrowly replaces `billing_customer_command`. Only the original Paddle TEST
  encoder with UNKNOWN replay and zero replay window may elect one first send.
  The 30-second local authorization budget is NOT a claimed Paddle replay window.
  A repeated dispatch is refused, including direct SQL. Stripe's existing replay
  contract, ownership, search_path and ACL remain unchanged. All 175 historical
  migrations remain unchanged; no new table, role or grant is introduced.
- Paddle Checkout recovery now scans all transaction statuses for the original
  Customer, matches the exact operation, and re-retrieves/validates the single
  candidate's frozen financial terms and lineage. Empty/duplicate/truncated or
  contradictory discovery cannot create another transaction. Pagination never
  follows provider-supplied URLs; bounded/incomplete scans remain unresolved.
- `/billing/paddle-payment` integrates sandbox Paddle.js using only the protected
  initiating user's original server transaction. The new no-store authenticated
  GET `/billing/trial-journeys/{operation_id}/checkout` reuses current billing-role,
  tenant/actor, approved policy, immutable acceptance and withdrawal checks. It
  performs no provider request or dispatch; a null transaction means not submitted.
  The optional policy bundle digest comes only from the pinned installation catalog.
  Original URLs/transactions are checked before SDK loading; duplicate query
  identities are refused. Account switching aborts in-flight reads/SDK handoffs.
  Checkout uses card-only settings, disables Customer logout and preserves EN/AR.
  Browser/SDK callbacks never grant access. Both frontend journey and Paddle flags,
  public TEST client token and exact approved origin are required; defaults are off.
- Paddle trial observation freshly correlates the original completed transaction,
  Customer, subscription, price, quantity, amount/currency, zero initial financial
  adjustments and exact 14-day item trial dates. It preserves provider facts as B3
  PENDING evidence. A completed $0 transaction or saved card does NOT establish
  reusable recurring authority, local consent, VERIFIED or all nine capabilities.
  The actual adapter therefore stops before B4 confirmation when readiness is unknown.
- Shared renewal/cancellation/expiry/exclusivity still use the committed lifecycle,
  B3 immutable receipts/history and separate B4 authority. Existing Stripe
  Customer/Checkout contracts and successful off-session SetupIntent verification
  are reused unchanged. Positive paid coverage, failure/recovery, paid-period
  cancellation and unchanged Credits are verified for both provider identities.
  Existing Stripe Custom paid activation/frozen limits pass. Pricing Studio,
  Provider Accounting, active legacy routes and historical financial data were not
  modified. No global subscription index, withdrawal fence or rights writer changed.

Verification (overlapping selections, not additive):

- PASS **355 offline cases**, then **35 focused acceptance/policy cases** after
  adding the server-pinned bundle check; final XMLs:
  `.dev/evidence/payment-completion/offline-final.xml` and `acceptance-final.xml`.
  Tests use a socket/libpq guard, cleared inherited credentials and synthetic API
  responses; no external provider traffic. Existing AST scans emit two unrelated
  invalid-escape SyntaxWarnings, with no failures or skips.
- PASS **47 native cases**, new loopback PG17/tmpfs only:
  `.dev/evidence/multi-gateway-billing/7a41a0bec13a/result.json`. Covers actual
  restricted password roles, concurrent one-sender Customer dispatch, lost-reply
  recovery, tenant isolation, demotion, withdrawn/unrelated-actor handoff denial,
  both shared lifecycles, signed real-adapter translation and legacy Custom billing.
- PASS **4 final native cases**:
  `.dev/evidence/multi-gateway-billing/27602534c8a7/result.json`. Actual Paddle
  adapters compose authenticated consent -> durable Customer -> single Checkout ->
  immutable B3 trial observation -> explicit capability block, with no access or
  Credit mutation. Handoff authorization/withdrawal cases also pass. This proves a
  working composition, not Paddle recurring acceptance or an invented trial grant.
- Both native runs pass fresh **176**, populated **175 -> 176**, replay, injected
  rollback, unsafe installer-role rejection and unchanged effective existing
  EXECUTE privileges. FORCE RLS/role protections are inherited, never relaxed.
  Installation used isolated fixtures; production restricted installation remains
  unverified. The first run stopped at the intentional unsafe-role rejection's
  SQLSTATE; the new migration now explicitly returns 42501. Initial native tests
  used a nonexistent `viewer` role; corrected to the existing `staff` role. Failed
  evidence is retained, not reported as passing. All owned PG containers are stopped.
- PASS **9 Node cases**, **8 intercepted Chromium checks** (EN/AR), changed frontend
  ESLint and whitespace. Initial browser harness provider/env setup was corrected;
  final checks execute the actual page with intercepted API and SDK, never Paddle.

Focused same-agent adversarial review: stale authorization/identity during async SDK
loading is canceled; URL transaction substitution and duplicate parameters cannot
load Checkout; missing legal policy or withdrawn consent blocks handoff; unknown
submission never resets a sender marker; partial or conflicting discovery cannot
create/adopt; no saved-card/$0/redirect path becomes recurring authority or access.
This is not an external independent audit. B4's existing stabilized authorization
and immutable-history/financial checks remain the confirmation boundary.

### Approval-gated real sandbox acceptance procedure

Executable driver: from `backend`, run
`python -B -m scripts.gateway_sandbox_acceptance`. This is PLAN ONLY: no requests.
No `--execute` invocation was performed during this implementation.

Before real calls, separately authorize provider operations and supply all of:

1. Owner-approved immutable legal/operator/language/refund/retention/trial-start
   bundle and matching registry/catalog digest; explicit B2B eligibility; merchant
   approval and additional provider-required consent. Current documents are NOT
   approved. Do not fill these references with guessed policies or automated consent.
2. Dedicated synthetic business, verified account and current initiating billing
   user in a disposable/local TEST application. Read actual ports with `dev.ps1 status`.
   Install the existing explicit split-service composition and exact original TEST
   binding/price mappings only under separate authorization; never production
   attestor/confirmer credentials. No service factory is installed by this change.
3. Explicit bound Stripe TEST or Paddle sandbox credentials with least scopes,
   exact merchant verification, pinned API versions and real signature endpoints.
   Paddle needs Customer read/write, transaction read/write, subscription
   read/write, price read and account read; configure an approved HTTPS payment
   origin pointing at `/billing/paddle-payment` as the original server return/payment
   URL, a public `test_` client token, and approved sandbox default payment link.
   Enable local-only frontend/server journey flags and Paddle Checkout flag only
   after review. Browser SDK and provider webhooks must be separately authorized.
4. Independent evidence for every B4 capability and subscription-bound reusable
   recurring authority. Stripe needs successful off-session SetupIntent evidence
   from the original subscription or exact protected B3 source; an attached card
   or arbitrary Customer SetupIntent list is insufficient. Paddle saved-method
   `origin`/Customer association does not independently bind a mandate to this
   subscription. Actual capability/readiness acceptance remains BLOCKED where
   these facts cannot be proved; do not swap in synthetic all-capability observers.

Reserve the existing plan and explicitly accept approved terms in the UI first.
Create a private, reviewed JSON manifest (no API keys or access token in it):

```json
{
  "base_url": "http://127.0.0.1:ACTUAL_LOCAL_API_PORT",
  "operation_id": "ORIGINAL_OPERATION_UUID",
  "binding_id": "ORIGINAL_PERSISTED_TEST_BINDING",
  "provider": "paddle",
  "environment": "test",
  "synthetic_business": true,
  "provider_operations_authorization": "SEPARATE_AUTHORIZATION_REFERENCE",
  "merchant_approval_reference": "REVIEWED_MERCHANT_REFERENCE",
  "legal_approval_reference": "REVIEWED_POLICY_APPROVAL",
  "policy_bundle_digest": "sha256:EXACT_APPROVED_BUNDLE_HEX_DIGEST",
  "language": "en"
}
```

Use `provider: stripe` and the Stripe binding for its separate run. Place the
initiating user's short-lived local access token only in private
`KEEL_SANDBOX_ACCESS_TOKEN`, never in a command argument, output or Git. After
separate approval, use the same manifest/operation for each step:

```text
python -B -m scripts.gateway_sandbox_acceptance --manifest PRIVATE_MANIFEST --action advance --execute
python -B -m scripts.gateway_sandbox_acceptance --manifest PRIVATE_MANIFEST --action checkout --execute
python -B -m scripts.gateway_sandbox_acceptance --manifest PRIVATE_MANIFEST --action status --execute
python -B -m scripts.gateway_sandbox_acceptance --manifest PRIVATE_MANIFEST --action cancellation --execute
```

The driver permits only an explicit loopback application, refuses redirects/env
proxy discovery, checks server original TEST binding/provider and pinned policy
bundle before advance. Cleanup and cancellation first check the exact operation,
provider, TEST environment and original binding through the authenticated progress
read; it reuses current initiating-user/billing authority and remains available
after consent withdrawal. The server independently reauthorizes the subsequent
POST. The driver never supplies actor, price, provider identity, consent or approval
to the server. Manifest references record prerequisites, not proof of
legal or merchant acceptance. Server policy/auth/B4 checks remain decisive.

Manually complete provider-hosted sandbox Checkout only after approved consent.
Deliver authentic signed provider notifications, including exact duplicate and
out-of-order deliveries. Lose a response deliberately and recover the SAME
operation; assert one external Customer and Checkout. Verify B3/B4 records,
positive paid-period coverage, failure/recovery, scheduled cancellation retaining
paid access, exact expiry, unchanged Credit accounting and competing-provider
exclusivity. Browser redirects are never acceptance evidence. After pre-confirmation
withdrawal use `--action cleanup` on the same manifest; never use it as paid refund
or post-confirmation cancellation. Reversal/adjustment tests must remain blocked
until separately supported. No driver result certifies merchant readiness.

Remaining functional/release blockers, precisely:

- Full initial recurring confirmation is NOT complete: nine-capability acceptance
  is not proven, Paddle subscription-bound reusable authority is unresolved, and
  Stripe cannot invent exact SetupIntent correlation when no original/history
  source exists. These adapters intentionally cannot turn such cases into VERIFIED.
- New-cohort Custom trial confirmation remains blocked: B4 admits original
  self-serve catalog trial reservations, not a Custom quote/revision/approved
  entitlement snapshot. No approved Custom trial/start/amendment contract can be
  inferred from Pricing Studio USD analysis. Existing supported Stripe Custom paid
  contracts remain intact; Paddle Custom confirmation is not claimed.
- Taxes, discounts, credits, proration, additional currencies/items, refunds,
  reversals/chargebacks and paid/scheduled withdrawal compensation need exact
  financial/policy reconciliation; they remain explicit fail-closed cases.
- Approved legal/operator/MoR policy bundles, real merchant/provider TEST evidence,
  reviewed local service composition, full production restricted installation,
  coordinated cutover and LIVE approval remain separate gates. B2B 14-day trial,
  unchecked explicit consent, renewal, paid-period cancellation and case-by-case
  first-charge refund review within 14 days remain approved business decisions,
  not fabricated legal text or newly activated behavior.

Primary documentation checked:
[Customer creation](https://developer.paddle.com/api-reference/customers/create-customer/),
[Customer discovery](https://developer.paddle.com/api-reference/customers/list-customers/),
[transaction discovery](https://developer.paddle.com/api-reference/transactions/list-transactions/),
[transaction Checkout](https://developer.paddle.com/paddle-js/methods/paddle-checkout-open/),
[Customer payment methods](https://developer.paddle.com/api-reference/payment-methods/get-customer-payment-method/).

Commit review correction: the MEDIUM acceptance-driver cleanup scope bypass is
fixed. The existing authenticated progress projection now exposes the original
provider/binding/environment after protected ownership and authority checks. Every
mutating driver action validates original scope; cleanup/cancellation use progress
without requiring a still-valid consent or current policy bundle. This adds no
SQL, migration or privilege change beyond the already verified migration 176.

PASS: 26 focused network-free cases in
`.dev/evidence/payment-completion/cleanup-scope.xml`, including provider/binding/
environment mismatch, missing or forged operation, revoked authority and legitimate
post-withdrawal cleanup/cancellation. Five final ASGI HTTP cases additionally verify
401 and exact 403/409 denials, zero POST/provider actions on denial, and a successful
withdrawn original operation with no policy resolver. The test response adapter
normalizes Starlette's httpx2 responses to the driver's httpx type; these final
assertions require HTTP authorization denials, not arbitrary SQL/Python exceptions.
Evidence: `cleanup-http-final.xml` (overlaps the 26-case selection). Prior passing
backend/native/frontend/browser evidence is reused, not rerun. Review found no
remaining local-commit security blocker; all operational gates above remain closed.

Exact future local acceptance environment (not enabled by this implementation):

- Driver: `KEEL_SANDBOX_ACCESS_TOKEN` (private initiating-user session).
- Server: `RECURRING_JOURNEY_ENABLED=true`, `RECURRING_CONSENT_ENABLED=true`,
  `RECURRING_JOURNEY_PREVIEW_ENABLED=true`.
- Frontend: `VITE_RECURRING_JOURNEY_ENABLED=true`,
  `VITE_RECURRING_CONSENT_ENABLED=true`, `VITE_RECURRING_JOURNEY_PREVIEW_ENABLED=true`.
- Paddle frontend additionally: `VITE_PADDLE_CHECKOUT_ENABLED=true`,
  `VITE_PADDLE_CLIENT_TOKEN=test_...` (public sandbox token),
  `VITE_PADDLE_CHECKOUT_ORIGIN=<approved HTTPS origin>`.

The driver defines no Stripe/Paddle secret-key environment variables. Explicit
bound TEST API credentials, webhook secrets, policy catalog, synthetic business,
restricted local service composition and reviewed manifest must be installed
separately after authorization; flags alone are insufficient.

Changed-file manifest (reviewed scope):

- `backend/scripts/gateway_sandbox_acceptance.py`
- `backend/scripts/verify_multi_gateway_billing.py`
- `backend/src/ai/billing/journey_policies.py`
- `backend/src/ai/billing/paddle_gateway.py`
- `backend/src/ai/billing/subscription_journey.py`
- `backend/src/ai/routers/subscription_journey.py`
- `backend/src/infrastructure/database/migrations/20261210000000_paddle_customer_single_dispatch.sql`
- `backend/tests/billing/test_multi_gateway_adapters.py`
- `backend/tests/billing/test_paddle_completion.py`
- `backend/tests/billing/test_paddle_completion_db.py`
- `backend/tests/billing/test_subscription_journey.py`
- `backend/tests/billing/test_subscription_journey_db.py`
- `backend/tests/billing/test_verification_observations.py`
- `docs/RECURRING_CONSENT_FOUNDATION.md`
- `frontend/src/app/router/index.jsx`
- `frontend/src/features/billing/api/subscriptionJourneyApi.js`
- `frontend/src/features/billing/pages/PaddlePaymentPage.jsx`
- `frontend/src/features/billing/utils/paddleCheckout.js`
- `frontend/tests/browser/paddle-payment.mjs`
- `frontend/tests/paddleCheckout.test.mjs`
