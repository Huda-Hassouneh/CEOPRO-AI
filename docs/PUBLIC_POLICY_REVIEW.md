# Public policy candidate review — 2026-11-09

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

Do not apply this migration to the running integration database during this task.
The local preview still reads that unchanged backend and truthfully flags its old
Pro duration. The new branch's fresh database/API mapping has all three at 14;
deployment of the approved branch and migration is required to update that runtime.
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
