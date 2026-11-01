# KEEL Platform Billing Owner Manual

This guide describes the integrated Python billing implementation and its current
limits. Open **Platform Owner → Billing** using an active Platform Owner account.
A customer tenant Owner or Admin is not a Platform Owner. Controls marked
unavailable deliberately do not perform an unsafe or unsupported operation.

## How the tabs fit together

```text
Provider Accounting → What does KEEL pay?
AI/Data Credits     → How provider usage is represented and limited
Features + Plan Features → What a plan includes
Pricing Studio      → What is economically safe under explicit assumptions?
Plans / Custom Plans → What KEEL sells / contracted customer packages
Subscriptions      → What a customer currently has
Promo Codes        → Commercial discounts
Custom Quotas      → Custom quote review and versioned quotation economics
```

Provider cost is not a selling price. Credits are customer allowance units;
they are not subscription revenue. Actual provider spend, quotation cost rates,
and commercial contract amounts are separate records. Pricing Studio supplies
decision support, not automatic publishing or subscriber repricing.

## Initial setup and completeness

The Billing page now opens with a compact **Billing setup** guide. Expand its
recommended workflow to move between the nine tabs. READY means the cited
catalog record exists, not that a provider or a published price is economically
safe. INFO means the step needs an owner review. The provider count includes
optional alternatives, so it is not a plan completion percentage. Opening a tab
never marks a step complete. Each tab has an expandable explanation of its
effect and a contextual next link. Studio warning links point to the relevant
configuration area; follow the warning's actual evidence before changing a
rate or policy. The Provider Accounting table distinguishes rate evidence from
credential presence, and its owner-management link opens the guarded rate editor.

The installation migration workflow (`dev.ps1 migrate` for local operators)
installs the canonical catalog. Repeated setup reconciles missing approved
initial records; normal API requests and API-process restarts do not seed prices.
Only the installation operator runs migrations, against the intended database
with the required verified backup for a normal-environment rollout. Do not run a
migration merely to dismiss a warning.

Existing provider values always win, including zero and deliberately unpriced
values. Reconciliation records its catalog version and provenance in the audit
history. An owner change is never replaced by a later catalog default. There is
no automatic refresh from vendor websites. Missing prices remain missing.

The approved Groq catalog contains USD 0.075 per million input tokens and USD
0.30 per million output tokens for `openai/gpt-oss-20b`, approved 2026-10-28.
These are provider costs, not the customer price. A different model needs its own
verified rates. Historical public/self-hosted and conditional free-account rows
are not evidence that a paid account is free today. Check the actual account.

Open Pricing Studio's **Economic catalog and setup completeness** panel before
setting assumptions. It shows runtime-backed feature coverage and optional
provider paths, missing accounting units, credential *presence*, and conditional
content-storage approvals. Presence means untested; the panel neither calls the
provider nor approves its terms. Unused alternatives do not all need configuring.
Public services still have terms, fair-use limits and availability constraints.
Local sentiment, OCR, forecasting and storage need working infrastructure.

## Plans

**Purpose.** View the published Standard Plan catalog and manage availability.
Use it when checking what new customers can buy or taking a package off sale.

**Important fields.** Name/Arabic name identify the package. Monthly price and
billing options describe commercial terms. Active means available for new
purchases; it does not prove payment configuration is ready. Trial days describe
the offered trial. Current Standard, Plus and Pro use USD commercial prices of
29, 59 and 99 monthly for the approved initial launch catalog. Three-month totals
are USD 87, 177 and 297; six-month totals are USD 174, 354 and 594. These terms
have no additional multi-month discount. Historical customers may retain earlier
prices and discounts. Custom Plan discounts remain governed separately.
Retired packages may remain visible for history. Custom is not a fixed-price
Standard purchase.

**Save/change effect.** Supported availability changes are audited and change
new-purchase visibility. **Analyze Pricing** opens Studio with the plan selected.
**Create Plan** creates a new stable identity with explicit English/Arabic names,
trial days and a monthly USD commercial price. Optional periods use the discounts
you enter. The plan starts inactive. You may select **Create from catalog
template**: Standard, Plus or Pro. Expand the template to inspect its grouped
features and approved default allowances before saving. A template copies all
customer capabilities and quantitative allowances, including bounded trial
Credits; it never copies a live customer's contract or Stripe mapping. Enter a
new key and names: retired identities cannot be reused. Your explicit price is
not replaced with a template price or Studio recommendation.

After template creation, **Edit** can change its names, descriptions, trial,
tier and explicit commercial terms while it remains inactive and has never been
activated, mapped to Stripe or referenced by customer records. Its stable key
cannot change. Earlier price rows are retired and retained, and the edit is
audited; copied allowances are not reset. After that draft stage, the existing
commercial publication guards apply. Use **Plan Features** to edit allowances
and supported Boolean entitlements, then review readiness and explicitly activate. Blank saved numeric
limits mean explicitly unlimited under the existing editor contract; do not use
blank to mean "not yet decided." Templates distinguish missing owner decisions
from unlimited. Stripe setup is still required before checkout. Activation does
not itself create Stripe objects. Existing commercial-term editing/deletion
guards remain for commercially used plans: use the approved versioned publication process if such a control
is unavailable; a template does not bypass it.

The default Standard/Plus/Pro templates include every canonical customer feature.
They differ through approved limits, Credits and capacities. Platform Billing,
Provider Accounting, Pricing Studio and platform/security administration are
never customer feature entitlements. Categories organize the display only.
Setup does not overwrite edited plans or restore an owner-removed allowance.

**Does not happen.** An analysis does not save a plan. Taking a plan off sale
does not cancel customers, rewrite their saved allowances or change their Stripe
price. Changing a catalog record is not permission to change historical terms.

**Dependencies/statuses.** Plan Features determines included allowances/modules;
Stripe catalog configuration determines checkout readiness. Active/inactive and
retired are availability/history concepts, not payment states.

**Safe workflow/example.** Inspect Plus, follow Analyze Pricing, assess the
assumptions and evidence, and record a commercial decision. If a price update
control is unavailable, use an explicitly approved catalog publication procedure;
do not substitute Provider Accounting edits to change the customer price.

## Pricing Studio

### Approved launch price publication

The `standard-plans-launch-v2` templates record the owner's pre-launch acquisition
decision. Launch price is a commercial acquisition decision and does not imply
that modeled delivery cost has decreased. AWS Frankfurt + Neon Launch costing,
local workload measurements, policy v4, provisional support/operations economics
and affordable-launch sensitivity analysis remain independent evidence. Expect
provisional, negative-margin and unsafe-price warnings; do not edit cost evidence
to dismiss them. This is the initial base catalog, not an expiring promotion.

An installation operator uses the existing authenticated-owner billing tool:
`python -m scripts.billing_admin publish-standard-catalog --by OWNER_UUID
--owner-token-stdin --reason "APPROVED_DECISION" --evidence decision.json`.
This previews the repository catalog. After a verified recoverable backup, repeat
with `--apply --expected-state PREVIEW_STATE_HASH`. Supply the real owner's Python
bearer token through stdin; never place credentials in command history. The
evidence JSON should identify policy v4 and the study/approval basis above.
Publication appends new price rows and retires old availability, preserving old
amounts, Stripe IDs, subscriptions and assignment snapshots. Repeating the same
publication is a no-op; later owner changes require a new reviewed version.
Normal bootstrap still never overwrites owner pricing.

New prices deliberately start without Stripe bindings. Reconcile the catalog
using `scripts.stripe_sync_catalog --dry-run`, inspect it, then apply in the
intended account. Local acceptance permits TEST keys only. Production operators
must separately approve LIVE Product/Price creation and verify all nine amounts,
USD currency and 1/3/6-month intervals. Never update old Stripe Price amounts or
automatically move existing subscribers. Annual remains hypothetical only.

**Purpose/use.** Compare a Standard Plan's published price with expected and
heavy-use economics, or simulate a different configuration before deciding.

**Fields.** Select a plan, Analyze or Simulate mode, and an effective analysis
policy. Simulation quantities come from actual supported plan allowances;
module switches are entitlements. A new policy needs explicit utilization,
margin, risk, processing, rounding and FX assumptions. Schema-v2 policies also
require six monthly internal-cost totals: expected and stress for Standard,
Plus and Pro. These include allocated hosting, local processing,
storage/backups/transfer and support/operations; exclude expenses already counted
through Credits or other economic bindings. No amounts are filled automatically.
Ratios are fractions (0.35 means 35%). JOD per USD converts USD cost
and published price into JOD analysis. Record FX source/version and the reason.
Annual allowance cycles describe a hypothetical annual contract, not an
automatically available annual checkout option.

**Outputs.** Expected/stress cost is exposure under the selected utilization.
Break-even covers expected costs and processing. Safe minimum protects the
configured stress margin/risk buffer. Recommended price is the larger of target
and safe price, rounded upward by policy. Contribution and margins compare the
actual current price against the model. Observed provider spend is evidence,
not another charge added to Credit exposure. The cost breakdown shows where
cost is counted; Credit-covered features add no second vendor cost.

**Save/change effect.** Saving policy creates an immutable effective-dated
version with an audit reason. Running analysis saves a frozen analysis/evidence
snapshot. It reads the actual plan without publishing it. Blank feature coverage
uses the cited runtime catalog where known; explicit owner mappings are retained.
Adding a Credit-funded call as an extra external cost causes a conflict warning
and blocks a safe recommendation. Unknown features still need an explicit mapping.

**Does not happen.** No Stripe checkout, subscription, entitlement, subscriber
repricing or live plan mutation. Recommended is not willingness-to-pay evidence.

**Dependencies/warnings.** A policy, finite Credit budgets and Credit value are
required. Separate external costs need approved unit/usage bindings plus actual
Provider Accounting rates. Missing/unverified/stale rates, unknown coverage,
missing multipliers and unbounded usage block the applicable recommendation.
SAFE means safe **under the configured model**, not provider operational readiness.
WARNING means a calculated risk such as an unsafe current price or discount.
INCOMPLETE DATA means material inputs are absent; a known subtotal is not a full
cost. Unverified optional alternatives in the catalog are distinct from an
actually bound material external rate. A bounded Credit-exposure analysis does
not certify every provider alternative or infer provider availability.

Internal costs are Owner assumptions, not measured provider charges. Each value
has Provisional or Owner approved status and optional evidence reference,
measurement dates and note. Editing a value or its evidence resets the editor's
status to Provisional. Stress must cover expected cost. A result using either
provisional assumption is labeled PROVISIONAL even when it can calculate a price;
Owner approval is an attestation, not independent verification. Internal totals
already describe their scenarios and are not multiplied by Credit utilization.
Longer terms multiply monthly internal costs by the number of months, preserving
the existing Credit allowance reset rules.

Legacy policies remain immutable and are not converted into tier assumptions.
New analyses using them show INCOMPLETE DATA until the Owner saves a schema-v2
policy. Previously saved results and hashes remain unchanged. New policy versions
freeze the six assumptions and their evidence. Owner-created plans outside the
canonical three do not inherit another tier's costs; missing assumptions are
reported explicitly. Simulation changes quantities, not internal-cost estimates:
review whether the selected plan's assumptions still cover the simulated workload.

**Safe workflow/example.** Configure and verify actual costs; enter documented
internal allocations and expected/stress utilization; analyze Pro; simulate more
AI Credits; compare stress cost and the recommendation; return to Analyze to
confirm the published plan is unchanged. Keep the snapshot for the decision.

## Custom Plans

**Purpose/use.** Inspect customer Custom contracts and their purchased features.
Use it to understand an agreed package, not to bypass payment or review.

**Fields.** Customer/company, contract/plan identity, price/currency, selected
features and quantities, and lifecycle state describe the existing contract.
Absent quantities are not an implied unlimited new purchase. Older contracts
can have different currencies or historical module semantics.

**Save/change effect.** This tab primarily exposes existing contracts. Arbitrary
enable/disable is deliberately unavailable where no safe billing transition
exists. Custom quote creation/review is handled in Custom Quotas and the customer
builder rather than by an independent contract toggle.

**Does not happen.** Viewing, quoting, approving or accepting does not grant paid
access. Never treat an approved quote as a paid subscription.

**Dependencies/statuses.** Frozen quote, acceptance, durable checkout and verified
payment reconciliation govern paid activation. Overlapping provider subscriptions
or manual contracts can block a new purchase. Contract status and provider payment
state must be investigated together.

**Safe workflow/example.** For a customer needing more capacity, inspect the
existing contract first; use the supported reviewed quote path rather than
creating a second overlapping subscription.

## Custom Quotas

**Purpose/use.** This is the UI's current label for the Custom quote queue and
quotation economics. Use it for review-required customer configurations,
owner-created quotes, policy versions and vendor/infrastructure quotation rates.

**Fields.** Configuration selects supported modules, quantities and monitoring
cadence. Quote/revision/status/reference identify the approval evidence. Calculated
price and FX evidence are frozen backend results, not browser price overrides.
Cost-rate unit, usage conversion, multipliers, source, verification and version
explain a quotation input. Shared infrastructure is allocated according to the
active quotation policy. Saving a draft policy alone does not activate it.

**Save/change effect.** Draft/revision saves and transitions write history.
Calculate uses the current authoritative calculator; approval needs a calculated
frozen revision and reference. Activate is a separate explicit policy action.
Cost-rate edits create successor versions rather than rewriting frozen quotes.
Approval makes the offer available in the customer's portal; it does not invent
an email-delivery event. The current queue is bounded to the first 100 records.

**Does not happen.** Quotation vendor rates do not change actual provider-spend
accounting. New rates/policies do not silently recalculate accepted historical
terms. No owner approval or customer acceptance grants entitlements.

**Dependencies/statuses.** Draft/submitted/calculated/approved/accepted/rejected/
expired reflect quote workflow, not proof of payment. Invalid combinations,
missing rates or evidence can block calculation. New self-service quotes use JOD
commercial terms with separate frozen USD payment and FX evidence. Existing USD
quotes keep USD terms; the older internal owner-draft route can still use its
existing USD monthly contract. Read the actual quote, not a generic label.

**Safe workflow/example.** Open an oversized quota request, inspect review
reasons, calculate its revision, check both commercial and payment amounts and
provenance, approve with a reference, then let the customer accept and pay.

## Promo Codes

**Purpose/use.** Manage approved discounts and eligibility; inspect redemption
usage. Use for a controlled campaign, not to alter the underlying plan cost.

**Fields.** Code, percentage/fixed discount, currency where relevant, duration,
validity window, eligible plans and redemption restrictions describe the offer.
Active provider-backed terms are immutable; edit a draft before activation.

**Save/change effect.** Draft create/edit is audited. Activation/deactivation
uses the existing guarded provider-verification workflow, including its TEST-only
limits. A saved local draft is not automatically usable at checkout.

**Does not happen.** It does not change Provider Accounting, recalculate plan
economics, retroactively discount existing invoices, or prove payment occurred.

**Dependencies/statuses.** Eligible active catalog prices and matching Stripe
promotion evidence are required. Draft/active/inactive and validity/redemption
rules determine usability. Unsupported provider mode or a mismatch must block
activation rather than simulate success.

**Safe workflow/example.** Create a draft for eligible Plus purchases, check
margin after discount in Studio, confirm dates/limits, and follow the supported
activation process. Do not assume a draft code grants a customer discount.

## Features

**Purpose/use.** Inspect executable capability definitions and maintain labels.
Use when clarifying what customers see or checking the allowance unit.

**Fields.** Identifier, English/Arabic name, boolean versus quantity, unit,
aggregation and reset cycle describe enforcement. Tokens, KB, records, images,
seats and Credits are different units; they are not interchangeable prices.

**Save/change effect.** Supported metadata edits change catalog presentation
with audit. Create/delete or changing unit/type/reset/aggregation is disabled
when no approved executable entitlement migration exists.

**Does not happen.** Renaming a feature does not implement a capability, create
a provider mapping or establish its cost. Local sentiment is not a hosted token
charge simply because it uses an ML model.

**Dependencies/statuses.** Runtime enforcement defines supported features; Plan
Features controls their inclusion. Unavailable controls indicate a required
contract decision, not an invitation to edit the database directly.

**Safe workflow/example.** Improve the Arabic label of document storage while
retaining MB and its capacity semantics. Check its plan links afterward.

## Plan Features

**Purpose/use.** Link supported features to a plan and set future plan allowances.
Use when changing what newly assigned customers will receive.

**Fields.** Plan, feature, included status and quantity. Boolean modules have no
numeric quantity. Zero means no allowance; an included null numeric limit can
mean unlimited. Unlimited capacity needs a finite usage assumption for economics.

**Save/change effect.** Supported link/unlink/quota changes update and version
the catalog and write audit history. Existing assignments retain their immutable
catalog snapshot; new assignments receive the new catalog terms.

**Does not happen.** No new paid subscription or Credit reset, no historical
contract rewrite, and no automatic customer price change.

**Dependencies/statuses.** Canonical supported feature definitions and plan
existence are required. Only supported premium modules and numeric contracts are
editable; baseline module controls can be restricted. Sum allowances reset by
the actual assigned billing period, not automatically once each calendar month.

**Safe workflow/example.** Simulate a higher AI Credit allowance in Studio first.
If approved for future customers, change that plan-feature allowance, record the
reason and verify the next catalog snapshot. Do not expect existing contracts to
receive the change retroactively.

## Subscriptions

**Purpose/use.** Investigate customer plan/status/period and scheduled changes.
Use for support questions such as a trial ending or a cancellation taking effect.

**Fields.** Tenant/customer, plan, status, billing interval, trial/period dates,
provider identity and scheduled changes explain the current assignment. A trial
date is not a paid-period boundary. Cancellation scheduled for period end is
different from immediate expiration.

**Save/change effect.** This tab is an investigation view, not an arbitrary
payment-state editor. Use established customer/provider transition and verified
reconciliation workflows for changes, with their current permissions.

**Does not happen.** Viewing a subscription cannot charge, activate, reset
Credits or correct a mismatched invoice. Do not change rates or feature quotas
to repair payment state. A success redirect or $0 trial invoice proves no paid
post-trial period.

**Dependencies/statuses.** Stripe's verified state, local reconciliation and
tenant assignment snapshots determine rights. Trialing, active, past due,
pending, payment failed and paused are distinct states; several block a second
checkout even when the customer says payment failed.

**Safe workflow/example.** For a customer who canceled but still has access,
inspect cancellation timing and the verified current period. Preserve the period
until its real end; do not force expiration or reset allowances.

## Provider Accounting

**Purpose/use.** Record KEEL's actual provider cost per accounting unit. Use
when configuring a paid integration or after a vendor price/account change.

**Fields.** Budget AI/Data identifies the Credit pool. Provider + operation +
unit must match the real adapter (for example Groq model + input_token).
USD cost/unit is **per token**, not per million tokens: divide a per-million
price by one million. Reservation safety margin protects estimates, not selling
margin. Charged-on-failure and final-cost behavior describe provider settlement.
Source, verified date and reason document the decision. Configured by distinguishes
catalog/migration origins from owner/operator edits.

**Save/change effect.** Confirming a supported edit replaces the current schedule
for future reservations, with before/after audit evidence. Existing ledger and
frozen quote/analysis evidence retain their original financial facts.

**Does not happen.** No API keys are installed, no vendor account or legal approval
is created, and no customer price, published plan or existing subscription is
recomputed. A zero row is not proof of an account's free-tier eligibility.

**Dependencies/statuses.** Missing means no price. Zero means configured zero,
not verified. Non-final means reconciliation evidence is still needed. The
existing table's configured label is not a verification certificate; Studio's
evidence separately reports VERIFIED/UNVERIFIED/STALE/MISSING. A source/date and
finality are required for a verified analysis-bound rate. Operational credentials,
approval and availability are separate checks.

**Safe workflow/example.** Read the actual Tavily account contract, enter its
verified per-request USD rate with source/date/reason, confirm the save, and rerun
Studio. Do not copy the customer subscription price or assume free credits make
every request permanently free.

## Complete owner workflows

### 1. Create/manage a Standard Plan

Inspect Features → inspect/edit supported Plan Features → inspect the Plan →
Analyze Pricing → document the owner price decision → use approved publication
controls/procedure if available. Arbitrary new-package publication and price
mutation remain policy-gated; this release does not invent a publishing path.
Availability changes and quota changes have their distinct supported effects.

### 2. Determine a safe Standard price

Provider Accounting → verify required costs and actual account terms → inspect
completeness → create an evidence-based Studio policy → analyze expected and
stress economics → check tier/discount warnings → record an owner decision.
Do not fill missing support/infrastructure/utilization with fabricated defaults.

### 3. Manage a Custom Plan

Customer builder → backend validation/calculation → automatic review decision.
Under limits with verified quotation evidence: show price and allow eligible
direct checkout, without manual approval. Otherwise show indicative price where
available plus review reasons → submit request → owner calculate/revise → frozen
approval → customer acceptance → eligible checkout → verified paid reconciliation
→ purchased allowances/modules activate. Quota above the resolved automatic
maximum, JOD monthly price above the maximum, or unverified vendor rates trigger
review. Active versioned policy overrides the legacy fallbacks of 500000 units
and 2500 JOD/month. JOD price thresholds run before USD payment conversion.
Frozen commercial JOD, payment USD and FX evidence stay associated with checkout.
Retry an uncertain checkout using its existing request/attempt identity rather
than starting a second purchase. Existing subscription/contract conflicts block it.

### 4. Provider price changes

Verify the new provider terms → save a reasoned Provider Accounting change →
retain its audit → run a new Studio snapshot → compare impact → decide future
commercial pricing separately. If Custom quotation rates also need revision,
change their versioned policy/bindings explicitly. Historical customer terms,
paid invoices, usage ledger and frozen quotes are not silently rewritten.

### 5. Diagnose INCOMPLETE DATA

Read the specific Studio warning. POLICY_MISSING: create an explicit effective
analysis policy. COST_COVERAGE_MISSING: unknown capability needs a justified
coverage mapping. RATE_MISSING: check both approved feature/unit binding and
actual Provider Accounting schedule. RATE_UNVERIFIED/STALE: verify account terms,
source/date/finality under policy. COST_MULTIPLIER_MISSING: supply the approved
usage conversion/multipliers. UNBOUNDED_USAGE/MONITORING_ASSUMPTION_MISSING:
provide finite usage and cadence. CREDIT_COVERAGE_CONFLICT: remove the duplicate
external charge; retain the Credit exposure. Missing credentials or approval in
the readiness panel are operational blockers, not prices. Ask the installation
operator to provision legitimate credentials or obtain approval; never bypass it.

### 6. Investigate a subscription

Find the tenant in Subscriptions → inspect actual status, trial/paid period and
scheduled change → compare provider reconciliation/audit evidence → use the
established billing transition process for discrepancies. Do not edit Provider
Accounting, apply a manual Custom contract or approve a quote as a substitute
for payment verification. Escalate uncertain provider state without a second charge.

## Before future usage-based pricing

PAYG is not implemented by this catalog work. First validate provider unit
coverage, real account terms, usage/settlement evidence, operational approvals,
internal allocations and owner policy. Credit exposure is a bounded planning
model, not a market price or a universal per-unit customer rate. See
[the economic coverage inventory](BILLING_ECONOMIC_COVERAGE.md) for source paths,
known gaps and the distinction between mapping coverage and safe-plan coverage.
