# KEEL — Phase 0R Owner Architecture Decision Register

**Owner selections consolidated:** 2026-10-20  
**Status:** 13 of 13 architecture policy selections recorded; implementation **NOT AUTHORIZED**.  
**Authority:** Explicit owner selections made in the integration review conversation.  
**Companion source:** `KEEL_Phase0R_Architecture_Review.zip` (ADR and trace evidence) and `KEEL_Phase0R_Owner_Decisions.md`.  
**Scope:** Python/FastAPI main repository is the integration destination and sole operational authority. Node.js reference repository and its AI subtree remain strictly read-only.

> **Interpretation rule:** An approved architecture/policy direction does not approve unspecified numbers, fees, dates, retention periods, algorithms or destructive migrations. Any `PENDING` item requires a separate explicit decision before the affected behavior is enabled. No implementation, migration, deployment or merge is authorized by this register alone.

## Universal engineering principles

1. Preserve every relevant existing Python capability, including login/refresh, Stripe billing and historical contracts, RLS, Data/AI Credits, provider-cost ledgers, AI inference algorithms and canonical sales/invoice data.
2. Port missing/better Node business behavior to Python; where both implementations overlap, retain the approved best behavior without introducing duplicate identity, payment, subscription, entitlement, usage or canonical-data authorities.
3. For each bounded feature, trace frontend/API/auth/service/helpers/persistence/worker/retry/return path and all related migrations, permissions and entitlements. Map each Node behavior to a Python implementation or a documented approved exclusion.
4. Use forward-only, reversible-by-plan schema changes, staged tenant-impact checks, idempotency and native PostgreSQL 17/RLS/concurrency tests. Preserve current customer contracts and data.
5. For every Python file changed (including added, edited, renamed or deleted tests, migrations, documentation and frontend files), record file path, change type, reason, affected capability and verification in `docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md`; reconcile against Git diff.
6. Keep implementation phases bounded. Implementation readiness and production release are distinct gates. No new implementation is authorized until the owner gives a separately scoped instruction.

## Decision register

### AUTH-001 — Signup and signed-out sessions
**Selected: signup B + revocation A.** Keep Python as the identity/JWT/refresh/reset/workspace/RLS authority. For **new** signups, verify email before creating the permanent user/company/workspace (Node-style pending registration), with safe, idempotent verification. For protected operations, fail closed if token revocation cannot be verified; do not silently reinstate logged-out tokens when Redis/revocation infrastructure is down. Preserve existing users, memberships, accounts and safe session compatibility. Test duplicate registration, retries, invitations, existing tenants, trials, session refresh and outage behavior.

### AUTH-002 — Platform authority
**Selected: A (strict platform ownership).** Keep tenant owner/admin separate from KEEL platform owner/admin. Platform admins may manage companies, ordinary catalog/promotions/quotes within assigned permissions. **Only the Platform Owner** may authorize below-floor pricing, exceptional unpaid/manual financial access, or provider spending-control changes. Separate platform invitations from customer team invitations; enforce permission checks server-side with immutable audit trails. Tenant ownership never grants platform staff privilege.

### CATALOG-001 — Commercial catalog
**Selected: A (preserve current Python commercial terms).** Keep existing Python public plan prices, limits, trial eligibility/durations, price mappings, historical contracts, private terms and grandfathered access unchanged. Port missing Node-style catalog management, versioning, configurability and history to Python without automatically changing customers' purchased terms. Any future new commercial catalog requires a separately approved version, customer cohort, values, date and impact review.

### ENT-001 — Entitlements, competitor caps and sources
**Selected: competitor A + source A + rights A.** Continue current Python **Data/AI Credit-based competitor policy**, with no new fixed competitor cap on existing public plans; configurable count caps are allowed for **future separately approved custom contracts**. Count **each active persistent** Shopify, WooCommerce, approved database/API or other persistent connection **once** against the connected-source allowance; one-time manual uploads are not persistent connections. Preserve/grandfather all customers' effective feature rights before applying new explicit gates, and require impact assessment plus separate rollout approval for source-count changes that would affect customers. Keep Python Credits distinct from feature counts/capacities.

### PROMO-001 — Promotion eligibility and redemption
**Selected: reuse A + consumption A + stacking A.** Promotional redemption allowances are **per tenant/company**, not per person. Count a redemption only after **settlement of the initial subscription invoice**, including valid fully discounted zero-total invoices; failed/abandoned checkouts do not permanently consume a use. **No stacking** a promo with an already discounted custom offer. Stripe remains monetary discount authority; port Node's managed promo eligibility, constraints, atomic redemption, idempotency and reconciliation into Python. Preserve historical Stripe discounts. **Pending for each promo:** amount/type, eligible plans/currencies, dates, global/per-tenant limits, initial vs renewal scope and exact Stripe mapping.

### CUSTOM-001 — Quote acceptance and activation
**Selected: manual-contract A; Stripe normally precedes manual.** Preserve Node's customer custom configurator, quote/revision, approval and acceptance workflows. Acceptance alone never activates paid access: normal activation requires confirmed Stripe billing under Python's authoritative subscription assignment. **Platform Owner** may separately authorize a documented, audited and time-bounded manual/offline contract exception. Live Stripe subscription normally takes precedence; explicit manual exceptions cannot silently erase paid rights. Preserve preexisting manual/private contracts and Python credits. **Pending details:** exact precedence/expiry/reconciliation semantics for exceptional overlapping grants.

### CUSTOM-002 — Quote economics
**Selected: cost-based A + USD-only initial checkout + frozen approved FX during quote validity.** Port full Node quote engine behavior (Decimal calculation, vendor/infrastructure/other costs, margin floor, fees, upward rounding, warnings, approval thresholds and snapshots) to Python; obtain applicable provider-rate truth from Python's verified provider schedules without changing actual Credits/provider-cost accounting. Initial Stripe checkout **USD only**. Keep an approved quote's FX/rate version frozen during its valid acceptance/payment window; after expiry require a new approved quote. Unknown/unverified costs or FX block automated checkout and route to review. **PENDING, not inferred:** exact margin(s), cost floors/ratios, fees, multipliers, rounding increments, verified rates, FX source, quote expiration, renewal rules and instant-approval thresholds. Automatic custom checkout remains blocked until necessary parameters are approved.

### TRANSITION-001 — Mixed plan changes
**Selected: mixed A + overcapacity A.** Determine change type by comparing actual effective Boolean, SUM, MAX, private-plan and monitoring grants, not just tier/price. If a change both improves and reduces rights, **schedule the entire change for next billing period**, preserving current paid rights in the interim and requiring appropriate confirmed billing before applying changed entitlements. Pure upgrades with no reductions may take effect sooner after confirmed billing according to established Python provider rules. If a downgrade makes a tenant over capacity, retain existing products, competitors and connections; block additional growth rather than deleting business records. Keep Python Stripe scheduling and defend against stale/delayed events and retries.

### IMPORT-001 — Canonical import, inventories and overlap
**Selected: promotion A + inventory A + overlap A.** Keep Python canonical transactions plus invoice/item mirrors and existing product identity. Auto-promote **strictly validated and unambiguous rows**; preview, hold and require review for conflicts, invalid values and ambiguous identity. Maintain **source-owned inventory lineage** for Shopify, WooCommerce and manual imports; never silently overwrite conflicting stocks. Detect manual/store overlapping sales using available external references, source/invoice metadata and product mappings, but do not coalesce distinct legitimate identical sales. Preserve IDs/history, taxes/shipping/refunds, idempotent retries, accurate partial statuses, tenant RLS and no duplicate revenue/stock decrements. **PENDING:** any universal source priority and shared-key collision rules not already supported by verified identity.

### PRICE-001 — Recommendation evidence and fallback
**Selected: A (qualified fallback).** Preserve Python's pricing inference, demand/stock context and qualified peer/wider-market/internal fallback when direct local competitor evidence is inadequate; label the factual basis, confidence and limitations, and never imply fallback is verified local market pricing. Incorporate missing Node eligibility, currency/evidence validity, guardrails, entitlement and usage protection for single and bulk routes. Preserve history and evidence provenance. **PENDING:** maximal admissible observation age, FX/reference freshness where applicable and handling of a newest invalid observation. Do not sign off on final input policy until set.

### MPI-001 — Review samples and visible scoring
**Selected: B (suppress unreliable numeric scores).** Preserve Python sentiment classification, weighted scoring and historical evidence for **BUSINESS, PRODUCT and COMPETITOR**. Validate tenant ownership/subject identity; port Node eligibility/deduplication/input validation and usage protections. When eligible reviews are below approved minimum, show **UNKNOWN/null**, not numeric zero or a misleading score; do not re-charge for repeated summary reads. **PENDING:** exact eligible-review minimum, sampling cap, recency and source rules. Do not invent these thresholds.

### ACCOUNTING-001 — Failed, partial and ambiguous work
**Selected: feature A + uncertain-delivery B.** Consume feature allowances for **usable retained outputs** under the applicable defined metering unit; refund/release proven unused reservations and account for confirmed partial commits. If provider work may have completed but client delivery cannot be proved, provide a **controlled, auditable, idempotent customer allowance adjustment** while **retaining actual provider cost** in Python's immutable ledger. Maintain separate customer feature allowances, customer Data/AI Credits and actual provider USD spend; enforce durable request/period receipts, once-only settlement, crash recovery, no duplicate retry charges and period-safe adjustments. **PENDING:** exact per-feature metering units and allowable adjustment limits where not already contractually established.

### PRIVACY-001 — Shopify privacy and retained records
**Selected: A (targeted privacy erasure/restriction).** Implement verified signed Shopify privacy/uninstall/data requests, including shop/topic/delivery checks, dedupe, recoverable audited jobs, tenant attribution and fences preventing reimport of data erased under a valid request. Erase or restrict **Shopify-attributable personal information** that is covered by the request; retain financial/audit records only where applicable law and an approved policy permit or require. Preserve Python's existing company export/delete protections and unrelated manual/customer data. **PENDING for legal/operational sign-off:** jurisdictions, specific affected fields, retention schedules, legal bases/exceptions and permission/approval for irreversible actions. Do not invent retention periods or execute irreversible deletion without authorization.

## Unresolved specifics — not implicitly approved

| Area | Outstanding information / approval | Gate affected |
|---|---|---|
| Custom pricing | Margins, floor ratios, fee schedules, rounding, rate version, quote expiry, renewal and auto-approval rules | Pricing activation and automated custom checkout |
| Promotions | Per-code discount, eligibility, terms, currencies, dates, max redemptions and renewal treatment | Enablement of specific promotions |
| Plan/source entitlements | Effective-rights impact assessment and grandfathering where active source counting changes | Rollout of new source-cap logic |
| Pricing evidence | Max observation age; invalid-newest-observation rule; exact evidence freshness policy | Final pricing policy, applicable tests and release |
| MPI | Minimum eligible reviews, sampling cap, recency/source policy | Numeric score visibility and production release |
| Accounting | Contract-specific metering units and ambiguous-delivery adjustment limits | New/changed charging policies |
| Imports | Ambiguous source priority and external shared-key collision rules | Affected source reconciliation behavior |
| Privacy | Fields, jurisdictions, applicable rules, retention/legal exceptions, irreversible deletion authorization | Privacy consumer processing / release |
| Manual-vs-Stripe | Precise allowed override precedence and reconciliation in special cases | Activation of exceptional overlapping custom contracts |

## Implementation and verification gates

**SOURCE-001:** establish clean, reviewed post-Task-6 Python commit and a matching source manifest. The Phase 0R review references a newer Python working snapshot than the older ZIP that was shared earlier; do not implement against an ambiguous or outdated baseline.

**Phase 0V:** use a disposable **PostgreSQL 17** database to apply/reapply schema/migrations as planned, inspect *effective* RLS/grants/roles/dynamic SQL, and run native multi-session concurrency/usage/Stripe-state tests. Record passes, failures and skips separately. No tests should run destructively against customer databases.

**ADR reconciliation:** update the 13 existing Phase 0R ADRs and owner worksheet to reflect the **exact selections in this register**; retain each unresolved detail as PENDING. No general “best of both” language may substitute for a decision.

**Work allocation:** only after explicit authorization, issue a bounded Phase 1A task with precise writable Python paths, feature IDs, tests, migrations, frontend contracts, scope exclusions and ledger instructions. Subsequent phases need their own approval and evidence.

**Release verification:** provider sandbox/certification (Stripe TEST, Shopify, WooCommerce and applicable AI providers), multi-tenant/RLS tests, browser-to-API-to-DB-to-worker tests, quota and credit consistency, and independent code-diff/ledger audit. A static trace or green unit test alone is insufficient for production release.

## Instructions to the implementation agent

1. Read this owner register with the Phase 0R source traces and ADRs. Mark approved policy choices in the ADRs; keep outstanding numerical/legal/operational values PENDING.
2. Do **not** modify Node.js source. Do **not** create a second billing, identity, quota, credit or canonical transaction authority.
3. Do **not** infer authorization to implement. Wait for a separately scoped implementation instruction identifying allowed files and acceptance tests.
4. When a pending value is material to a feature, implement only safe scaffolding if specifically authorized; do not use guessed values or enable payment/deletion operations that depend on an unapproved policy.
5. Verify the live checked-out post-Task-6 Python baseline and migration state before modifying source. Maintain the complete unified file-change ledger and tests for each implementation phase.

**Owner policy choices: 13/13 selected.**  
**Outstanding detailed business/legal decisions: OPEN.**  
**Phase 1 implementation permission: NOT GRANTED.**  
**Production release permission: NOT GRANTED.**
