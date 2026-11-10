# Public policy candidate review — 2026-11-09

Integration follow-up verified 2026-11-10: the complete local application at
http://127.0.0.1:5273 now includes these candidates and migration 180. The policy
text remains UNAPPROVED. Initial-review statements below describe the original
preview-only checkpoint unless superseded by this follow-up.

Status: local review only, not approved or deployed. Candidate bundle
`keel-public-candidate-2026-11-09.2` has no effective date and is not installed
as a consent agreement. Opening a policy page does not persist acceptance.

## Scope and provenance

Prepared on `feature/public-policy-review-20261109`, based on assembled application
`ef90bb71bb07041ff3ed9f30c51b58b8e06d8af6`. The original integration checkout,
running backend and financial records remain unchanged. This branch additionally
contains the owner-approved future Standard-plan trial policy described below.

The five EN/AR draft sources are the existing `01_terms_of_service.md` through
`05_recurring_consent_disclosure.md` in the main-consolidation worktree's private
`.dev/sandbox-session/policy-review/{en,ar}` directory. Candidate copies live in
`frontend/src/features/legal/content/{en,ar}`. The private source/digest manifest
is `.dev/policy-source-manifest.json`; original drafts are preserved.

Known operator facts are Huda Hassuneh (هدى حسونة), an individual in Jordan,
KEEL, and keel.business.ai@gmail.com. No address, incorporation or registration
has been invented. Public privacy retention is not inferred from Sandbox retention.
Engineering-only A1 notes were adapted into customer-facing draft acceptance and
withdrawal descriptions; no implementation readiness is asserted.

## Local pages and links

Unauthenticated routes: `/terms`, `/privacy`, `/refund-policy`,
`/subscription-policy`, `/trial-renewal`, `/contact`. All support English/Arabic,
RTL, keyboard navigation, visible draft warnings and noindex/nofollow metadata.
The landing footer and pricing section link all six; navigation links contact. Standard checkout
review and the Custom Plan builder link the candidates without recording consent
or changing payment guards. These are review routes, not a public deployment.

The separate loopback frontend preview is http://127.0.0.1:5373 and uses existing
local read APIs. The original application remains at port 5273.

## Downgrade notice

The closest matching notice is `billing.errors.plan_transition_mixed_rights`
(`frontend/src/assets/locales/en.json:2783`). `PlanChangePreview.jsx` displays it
when preview returns that code. The backend `_classify_rights_change` and
`_plan_change_context` in `backend/src/ai/billing/service.py` reject combinations
that gain some allowances and lose others, or cannot safely be classified.
This protects existing commercial rights; it is not a public legal-policy
acceptance workflow. Rejection occurs before provider mutation. Ordinary
downgrades use `schedule_change`, preserve current rights until the effective
boundary, and return a scheduled result. The owner reports the notice disappeared
and the downgrade scheduled successfully; the earlier exact toast was not captured.
No downgrade was repeated for this review. No legal acceptance is inferred from
viewing the notice or scheduling a plan change.

## Decisions still needed before public approval

- The owner has now approved 14-day trials for Standard/Starter, Plus/Growth and
  Pro/Enterprise. Custom remains governed by its approved quote. Monthly USD
  prices remain 29/59/99; three/six-month totals remain 87/174, 177/354, 297/594.
  No currency, price, interval, allowance or existing entitlement was changed.
- Supply the public operator contact address; confirm whether any additional
  identity/contact information is legally required. Paddle's seller handbook asks
  for a buyer-support email and phone number; a public support phone is missing.
  No incorporated-company or registration claim is made. Private personal details
  required for Paddle identity checks must not automatically become public text.
- Review governing law/liability, acceptable use, suspension/notice, plan-change,
  proration, delinquency, overage and data-export wording against actual behavior.
- Complete privacy data/purpose/legal-basis inventory, subprocessors/transfers,
  retention, cookies/marketing, rights requests and incident-response disclosures.
- Verify public provider-specific cancellation/trial-cutoff and withdrawal
  instructions, refund wording and seller/Merchant-of-Record identification.
  Preserve the settled paid-period access and 14-day first-charge refund-request
  review intentions; no guaranteed refund is promised.
- Approve exact EN/AR text, versions and effective dates, then separately authorize
  deployment and any consent-bundle installation. Dynamic order fields must be
  supplied by frozen server terms, never by these placeholders.

## Trial policy implementation and rollout

`backend/config/billing/standard_plan_catalog.json` is now the immutable template
version `standard-plans-trial14-v2`. Changing an existing installed version in place
would violate the catalog digest contract, so the version was advanced.

Forward migration `20261213000000_standard_trial_fourteen_days.sql` is terminal
migration 180, after the existing definitive-retry migration. It serializes on the
existing `keel_platform_authority` advisory lock, locks the three canonical plan
rows, changes only `trial_days` to 14 when needed, and records old/new values in
the existing audit log. No runtime grants, functions or RLS policies change.
All 179 historical files and manifest hashes are preserved. The verifier manifest
adds only the new file/hash.

At the initial preview-only checkpoint the running integration database was left
unchanged and its old Pro duration was flagged. On 2026-11-10 the owner separately
authorized local integration and migration: a full backup was restored into a
disposable database copy and verified before applying migration 180 through the
existing launcher/runner. All three tiers now return 14 in the running API.
All 59 protected billing/tenant/price/entitlement table fingerprints and effective
RLS/EXECUTE privileges were preserved, and replay applied zero migrations.
Existing seven-day trials, subscriptions and frozen orders retain their dates and
terms. Legacy local signup trials remain a separate mechanism; this is no cutover
to authenticated provider-backed recurring consent. The downgrade safeguard,
provider-confirmed trial-start requirement, explicit-consent and B4 gates remain.

Stripe's existing paths use a frozen trial end or trial duration in the Checkout
request, not a required Price-level default trial. No Stripe price/amount sync is
needed solely for this duration change. Historical requests retain their original
boundary. Any separately configured Stripe Price trial default must be reviewed
before use; no external inventory was fetched in this task.

Paddle recurring Prices carry their trial configuration. The previously verified
Starter monthly Sandbox Price already has 14 days. Verify/synchronize any Plus,
Pro or other period mapping before offering it; any seven-day provider Price must
not be silently reused for a 14-day frozen offer. Use the existing guarded catalog
sync with separate authorization; no external object or credential was changed.

## Commercial consistency and Paddle readiness

| Area | Result / remaining gate |
| --- | --- |
| Product/landing and pricing | Existing branding retained; prices remain backend-authoritative. Removed the misleading unlimited-competitor claim: plan capacity and Data Credits are separate. |
| Public routes and contact | Six local draft routes, bilingual links and working support email; Custom contact action falls back to `/contact` when no email setting is supplied. |
| Trial and renewal | Three canonical future tiers are 14 days; card requirement, unchecked explicit consent, automatic renewal and original-provider dates disclosed. Existing local trials are distinguished. |
| Cancellation and downgrade | Paid-period access and no automatic refund stated; mixed-rights safeguard preserved. Verify final provider-specific instructions/trial cutoff before publication. |
| Custom Plans | Approved quotes, eligibility and review remain required; no automatic Custom price or entitlement promise. |
| Refunds | First-paid-charge 14-day review window, email/reference procedure, no guarantee or promised processing deadline. Paddle and mandatory legal obligations preserved. No 30-day guarantee adopted. |
| Merchant of Record | Paddle scoped only to Paddle orders. Obtain final multi-gateway reseller wording: handbook's universal-order clause cannot truthfully describe Stripe orders. |
| Privacy / legal identity | Known sole-proprietor facts shown as draft; address, privacy inventory and legal clauses require owner/legal resolution. |
| HTTPS / public discovery | Local only. Final approved HTTPS deployment, route rewrites and domain approval are unverified; no website submitted. |
| LIVE operations / fulfillment | Disabled. Public policies do not establish recurring authority or Paddle B4 readiness; fulfillment must be independently accepted before selling through that path. |

Official references checked 2026-11-09:
- https://developer.paddle.com/build/go-live-checklist/ — accessible policies,
  matching prices, discoverable contact, domain/account verification; Sandbox and
  LIVE are separate.
- https://www.paddle.com/seller-guides/seller-handbook — sole-proprietor identity,
  support phone/email, reseller clause and pre-purchase terms/refund acceptance.
  Its 30-day money-back guarantee is a recommendation, not KEEL's approved policy.

Pre-purchase versioned acceptance is not established by these page links. The
authenticated consent foundation remains separately policy-gated, and the legacy
Stripe plan-change notice is not an acceptance record. Do not describe this branch
as authorizing LIVE sale or consent collection.

Paddle website review additionally needs the completed policies, pricing/contact
links and working public HTTPS pages on the intended domain, plus Paddle's current
domain/account verification. Local pages and approved isolated Sandbox policies
do not establish LIVE merchant approval. See Paddle's official go-live checklist:
https://developer.paddle.com/build/go-live-checklist/ . No provider operation or
public publication was performed for this task.

## Focused evidence

- Focused frontend tests (policy, launch catalog, billing API, EN/AR render): 35 passed.
- Targeted ESLint for the new legal components/catalog/test: passed.
- Frontend production build: passed.
- 36 private browser checks passed across EN/AR desktop and mobile, six public
  routes, landing navigation/footer and both billing policy-link contexts;
  zero billing mutations, external requests blocked. WCAG 2 A/AA and 2.1 AA axe
  scans of all six policy pages found no violations in the tested viewports.
  The initial footer smoke check raced lazy rendering; waiting for the real
  rendered link fixed the private harness, with the application link preserved.
  Screenshots and results are
  in private `.dev/policy-browser-results.json` and `.dev/*-*.png`.
- Disposable PG17: fresh 180 migrations, populated 179→180, replay empty;
  9 focused native cases passed (historical rights, prices, ACL equivalence,
  downgrade/cancellation, Credit-period preservation and expired access).
- Actual password-authenticated `ceopro_app`: non-superuser/non-BYPASSRLS;
  direct catalog update rejected with SQLSTATE 42501. No runtime authority added.
- 9 focused offline signature/consent/B4 rejection cases passed. Historical real
  Stripe TEST evidence is reused; no external acceptance repeated.
- Initial native failures were a stale seven-day assertion, an unescaped `%` in
  the new test helper, and missing private harness runtime URL. Corrected without
  weakening application behavior. Initial logs preserved privately.
- Migration installation used disposable local administrator authority. This does
  not replace full production restricted-installer verification.
- Existing build warnings remain: unresolved Sora ExtraBold font reference,
  large chunks and an auth adapter mixed static/dynamic import. No build failure.
- Git whitespace check passed. No credential changes; new infrastructure removed.

Git operations: inspection and local feature-branch commit are SAFE; the forward
data migration is CAUTION and was tested only in newly owned disposable PostgreSQL.
Push, merge, branch rewrites, production access and external payment writes are
UNSAFE without separate authorization and were not performed. This feature branch
depends on the assembled billing/teammate stack at its base; do not publish it as
an independent replacement for that stack.

## Draft PR dependency and integration follow-up

The original `aa50ff771b1f50032579fbb8da51ad36b9f6277c` has assembled application
ancestry; publishing that branch against main would include unrelated work.
The clean publication branch `pr/keel-public-policies-trial14` instead transplants
only that policy commit, with provenance, onto PR #124's exact head
`95da7f322bcee94e7208de92205887892336311c`. Its initial implementation patch ID
matches the original and its review diff has only the 34 intended files. The
additional follow-up commit changes this report only.

Review base: `pr/keel-legacy-checkout-lean-compat` (#124), not main. Prerequisites:
the upstream chain in owner guide https://github.com/Huda-Hassouneh/CEOPRO-AI/issues/118
(#110/#117, then #119→#120→#121→#122→#123→#124). #108/#109 are separate assembled
features whose existing review histories are preserved. #104 and #125 are now
merged into main; no duplicate copy is included here. Main was refreshed to
`f1a65f237280c26a9b2baa2fbfbe3fcfb135d178`; newer merged #126 has no policy-file
overlap. Production-branch-only #127/#128 are not imported.

After the upstream stack reaches main, retarget this Draft to main and verify its
diff and checks before marking it Ready. Preserve upstream ancestry; never merge
this child into #124's branch. Migration 180 follows the canonical 179-file chain;
recheck ordering against any later migration additions. Do not merge #93/#94/#95
wholesale; #124 provides the canonical compatible replacement. No published
teammate/billing branch or PR was modified for this follow-up.

The complete integration branch was fast-forwarded to the original policy commit,
retaining every assembled commit. Existing ignored configuration hashes match,
including Stripe TEST settings, egress guard and frontend settings. API and eight
owned workers were paused for the recovery point and resumed through the existing
launcher; frontend remains at 5273, API at 8100, and Mailpit is unchanged.

New focused checks: 11 local HTTP/security/configuration checks; the public catalog
has 14-day trials, original USD amounts and nine enabled original TEST mappings.
The designated synthetic account retains its local trial; the owner's manually
tested Stripe subscription belongs to another account and was verified unchanged
in database snapshots, not impersonated. Custom configurator/quotes remain available,
another synthetic tenant cannot see the original subscription, malformed Stripe
signatures are rejected, and the protected journey remains disabled. No Checkout
or payment was submitted. The integrated production frontend build passed.

Private follow-up evidence and the recoverable dump are under the complete
worktree's ignored `.dev/policy-integration-20261110` directory. Historical provider
acceptance and prior native/offline tests are reused, not represented as repeated.
The 2026-11-10 browser verification uses the complete app, not the separate preview.
All 36 EN/AR desktop/mobile browser cases passed, including six-page accessibility
scans and Standard/Custom policy links. Authenticated onboarding state returns 200.
The post-browser check again preserved all 59 protected table fingerprints,
configuration hashes and RLS/ACLs; API plus eight workers are owned and running,
and attestor/confirmer roles remain dormant. No application correction was needed.

These checks establish local draft rendering/navigation, not legal approval,
Stripe/Paddle acceptance or a new authenticated consent workflow.

## Changed file inventory

- `backend/config/billing/standard_plan_catalog.json`
- `backend/scripts/verification_migrations.json`
- `backend/src/ai/tests/test_subscription_limits_integration_db.py`
- `backend/src/infrastructure/database/migrations/20261213000000_standard_trial_fourteen_days.sql`
- `backend/tests/billing/test_catalog_publication.py`
- `backend/tests/billing/test_lean_plan_limits.py`
- `backend/tests/billing/test_search_entitlement_retirement.py`
- `backend/tests/billing/test_standard_trial_policy.py`
- `docs/PUBLIC_POLICY_REVIEW.md`
- `frontend/src/app/router/index.jsx`
- `frontend/src/app/router/routePaths.js`
- `frontend/src/features/billing/pages/BillingCheckoutPage.jsx`
- `frontend/src/features/billing/pages/CustomPlanBuilderPage.jsx`
- `frontend/src/features/landing/components/LandingNavigation.jsx`
- `frontend/src/features/landing/locales/ar.json`
- `frontend/src/features/landing/locales/en.json`
- `frontend/src/features/landing/sections/PricingSection.jsx`
- `frontend/src/features/legal/PolicyLinks.jsx`
- `frontend/src/features/legal/content/ar/privacy.md`
- `frontend/src/features/legal/content/ar/refund.md`
- `frontend/src/features/legal/content/ar/subscriptions.md`
- `frontend/src/features/legal/content/ar/terms.md`
- `frontend/src/features/legal/content/ar/trial.md`
- `frontend/src/features/legal/content/en/privacy.md`
- `frontend/src/features/legal/content/en/refund.md`
- `frontend/src/features/legal/content/en/subscriptions.md`
- `frontend/src/features/legal/content/en/terms.md`
- `frontend/src/features/legal/content/en/trial.md`
- `frontend/src/features/legal/pages/LegalPage.jsx`
- `frontend/src/features/legal/policyCatalog.js`
- `frontend/src/features/legal/styles/Legal.css`
- `frontend/tests/billingApi.test.mjs`
- `frontend/tests/launchCatalog.test.mjs`
- `frontend/tests/publicPolicies.test.mjs`
