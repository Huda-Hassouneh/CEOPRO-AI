# Owner decision worksheet — selections reconciled 2026-10-20

**13/13 architecture policy directions SELECTED by the owner.** Outstanding detailed values and legal/operational decisions remain PENDING. Implementation and production release are **NOT AUTHORIZED**. This sheet supersedes its earlier unanswered-option version.

Authority: [supplied owner register](reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md). Selections below reproduce its decision text verbatim. Current-source comparisons are historical Phase 0R facts, not evidence that the selected behavior is implemented.

## AUTH-001 — Signup and signed-out sessions

| Current Node behavior | Current Python behavior |
|---|---|
| Node creates pending_signups, then the company/user after verified token consumption. Its default login tokens contain sessionId, but authenticateUser checks the session table only when that claim is supplied. Refresh-token utility exists without a mounted refresh route; forgot/reset client URLs are placeholders. | Python creates user/company/owner during signup and restricts unverified email when configured; issues/refreshes one JWT system. Redis revocation fails open on outage. SQL get_current_tenant already rejects removed human memberships; that protection is not absent. |

**Owner-selected policy (verbatim)**

**Selected: signup B + revocation A.** Keep Python as the identity/JWT/refresh/reset/workspace/RLS authority. For **new** signups, verify email before creating the permanent user/company/workspace (Node-style pending registration), with safe, idempotent verification. For protected operations, fail closed if token revocation cannot be verified; do not silently reinstate logged-out tokens when Redis/revocation infrastructure is down. Preserve existing users, memberships, accounts and safe session compatibility. Test duplicate registration, retries, invitations, existing tenants, trials, session refresh and outage behavior.

**Outstanding details / gates**

No additional signup/revocation policy choice is specified as pending in the owner register. Preserve existing-user/session compatibility; rollout details and implementation permission remain separate gates.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-AUTH-001-identity-bootstrap-and-session-policy.md).

## AUTH-002 — Platform authority

| Current Node behavior | Current Python behavior |
|---|---|
| Node platform role requires an active platform-tenant owner/admin and permission namespace. Platform invitations grant platform membership, not ordinary customer team seats. Customer owners cannot become platform operators by owning their company. | Python has owner/admin/accountant and other tenant roles, tenant-team invitations and operator billing CLI. There is no corresponding mounted platform management API/UI. |

**Owner-selected policy (verbatim)**

**Selected: A (strict platform ownership).** Keep tenant owner/admin separate from KEEL platform owner/admin. Platform admins may manage companies, ordinary catalog/promotions/quotes within assigned permissions. **Only the Platform Owner** may authorize below-floor pricing, exceptional unpaid/manual financial access, or provider spending-control changes. Separate platform invitations from customer team invitations; enforce permission checks server-side with immutable audit trails. Tenant ownership never grants platform staff privilege.

**Outstanding details / gates**

No additional platform-authority policy choice is specified as pending. Actual assigned permissions and exceptional owner authorizations must be explicit and audited; no impersonation or other unstated powers are granted.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-AUTH-002-platform-authority-and-role-boundaries.md).

## CATALOG-001 — Commercial catalog

| Current Node behavior | Current Python behavior |
|---|---|
| Node defines 21 feature codes, plan links, billing options, private plans and historical Stripe price versions. Seed/demo amounts do not establish a production commercial agreement. | Python latest migrations display Standard/Plus/Pro/Custom while retaining starter/growth/enterprise/custom keys and legacy keys. Source declares USD 55/140/350, trial days 14/14/7; later Pro migration sets products 500 and seats 50. These are source declarations, not a fresh live catalog export. |

**Owner-selected policy (verbatim)**

**Selected: A (preserve current Python commercial terms).** Keep existing Python public plan prices, limits, trial eligibility/durations, price mappings, historical contracts, private terms and grandfathered access unchanged. Port missing Node-style catalog management, versioning, configurability and history to Python without automatically changing customers' purchased terms. Any future new commercial catalog requires a separately approved version, customer cohort, values, date and impact review.

**Outstanding details / gates**

Any future commercial catalog change remains PENDING a separately approved version, cohort, exact values, effective date and impact review. Existing Python commercial terms remain unchanged.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-CATALOG-001-catalog-trials-and-existing-contracts.md).

## ENT-001 — Entitlements, competitor caps and sources

| Current Node behavior | Current Python behavior |
|---|---|
| Node has independent Boolean rights, ai_pricing recommendation count, MAX capacities and a source-type counting list. Tracked competitors can have an explicit count cap. maxUsesPerUser elsewhere is not a feature. | Python has three module rights, numeric quotas and separate Data/AI Credits; current public competitor counts are NULL/unlimited under credit budgets. Only four missing-limit codes explicitly fail closed. Sources counted are active OWN_SYSTEM_CONNECTOR. |

**Owner-selected policy (verbatim)**

**Selected: competitor A + source A + rights A.** Continue current Python **Data/AI Credit-based competitor policy**, with no new fixed competitor cap on existing public plans; configurable count caps are allowed for **future separately approved custom contracts**. Count **each active persistent** Shopify, WooCommerce, approved database/API or other persistent connection **once** against the connected-source allowance; one-time manual uploads are not persistent connections. Preserve/grandfather all customers' effective feature rights before applying new explicit gates, and require impact assessment plus separate rollout approval for source-count changes that would affect customers. Keep Python Credits distinct from feature counts/capacities.

**Outstanding details / gates**

PENDING: effective-rights impact assessment, grandfathering and separate rollout approval where active persistent-source counting changes customer access. Future custom-contract count caps require a separately approved contract and values; no new fixed public competitor cap.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-ENT-001-feature-rights-units-and-credit-crosswalk.md).

## PROMO-001 — Promotion eligibility and redemption

| Current Node behavior | Current Python behavior |
|---|---|
| Node validates plan/date/active/global/per-tenant usage; the field maxUsesPerUser is implemented as a tenant redemption count. consumePromocode is SERIALIZABLE with unique promo/subscription identity. Actual caller is handleInvoicePaid for initial subscription_create settlement, including zero-paid 100%-off invoices, not merely subscription-created event. | Python hosted Checkout enables Stripe promotion entry but has no equivalent managed promo lifecycle or redemption ledger. Existing payment idempotency is not promo policy. |

**Owner-selected policy (verbatim)**

**Selected: reuse A + consumption A + stacking A.** Promotional redemption allowances are **per tenant/company**, not per person. Count a redemption only after **settlement of the initial subscription invoice**, including valid fully discounted zero-total invoices; failed/abandoned checkouts do not permanently consume a use. **No stacking** a promo with an already discounted custom offer. Stripe remains monetary discount authority; port Node's managed promo eligibility, constraints, atomic redemption, idempotency and reconciliation into Python. Preserve historical Stripe discounts. **Pending for each promo:** amount/type, eligible plans/currencies, dates, global/per-tenant limits, initial vs renewal scope and exact Stripe mapping.

**Outstanding details / gates**

PENDING for each promotion: amount/type, eligible plans/currencies, dates, global/per-tenant limits, initial versus renewal scope and exact Stripe mapping. Architecture selection does not enable any unspecified promo.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-PROMO-001-promotion-authority-redemption-and-stacking.md).

## CUSTOM-001 — Quote acceptance and activation

| Current Node behavior | Current Python behavior |
|---|---|
| Node offer lifecycle validates an approved priced/expiring quote; accept creates private plan/provider price mappings. Acceptance is not itself proof a payment was collected. | Python set_custom_contract immediately assigns active/trialing rights as an explicitly audited operator action. Stripe webhook activation is a separate path. No customer quote lifecycle currently connects them. |

**Owner-selected policy (verbatim)**

**Selected: manual-contract A; Stripe normally precedes manual.** Preserve Node's customer custom configurator, quote/revision, approval and acceptance workflows. Acceptance alone never activates paid access: normal activation requires confirmed Stripe billing under Python's authoritative subscription assignment. **Platform Owner** may separately authorize a documented, audited and time-bounded manual/offline contract exception. Live Stripe subscription normally takes precedence; explicit manual exceptions cannot silently erase paid rights. Preserve preexisting manual/private contracts and Python credits. **Pending details:** exact precedence/expiry/reconciliation semantics for exceptional overlapping grants.

**Outstanding details / gates**

PENDING: precise precedence, expiry and reconciliation semantics for exceptional overlapping manual/Stripe grants. No manual exception is activated by this ADR; Platform Owner authorization must be documented, audited and time-bounded.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-CUSTOM-001-quote-acceptance-versus-activation.md).

## CUSTOM-002 — Quote economics

| Current Node behavior | Current Python behavior |
|---|---|
| Node computes vendor/infrastructure/other costs using Decimal; cost/(1-margin), optional vendor-cost ratio floor, fixed fee and upward increment. It snapshots FX/rates. Unconfirmed rates produce pricing warnings, and the configurator routes warning cases to manual review rather than automatic checkout. | Python verifies runtime provider cost schedules, calculates Data/AI Credit budgets, and enforces platform/provider/model spend controls. Those are actual cost/credit authority, not a full quote projection workflow. |

**Owner-selected policy (verbatim)**

**Selected: cost-based A + USD-only initial checkout + frozen approved FX during quote validity.** Port full Node quote engine behavior (Decimal calculation, vendor/infrastructure/other costs, margin floor, fees, upward rounding, warnings, approval thresholds and snapshots) to Python; obtain applicable provider-rate truth from Python's verified provider schedules without changing actual Credits/provider-cost accounting. Initial Stripe checkout **USD only**. Keep an approved quote's FX/rate version frozen during its valid acceptance/payment window; after expiry require a new approved quote. Unknown/unverified costs or FX block automated checkout and route to review. **PENDING, not inferred:** exact margin(s), cost floors/ratios, fees, multipliers, rounding increments, verified rates, FX source, quote expiration, renewal rules and instant-approval thresholds. Automatic custom checkout remains blocked until necessary parameters are approved.

**Outstanding details / gates**

PENDING: exact margins, cost floors/ratios, fees, multipliers, rounding increments, verified provider rates, FX source, quote expiry, renewal rules and instant-approval thresholds. Automated custom checkout stays blocked until required parameters are approved.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-CUSTOM-002-quote-economics-provider-costs-and-fx.md).

## TRANSITION-001 — Mixed plan changes

| Current Node behavior | Current Python behavior |
|---|---|
| Node analyzePlanTransition compares effective grants and identifies gains/losses/mixed changes, including private feature configurations. | Python currently classifies by tier and then amount; its Stripe path supports immediate invoiced upgrades, trial preservation, schedules, pending payment and cancellation. |

**Owner-selected policy (verbatim)**

**Selected: mixed A + overcapacity A.** Determine change type by comparing actual effective Boolean, SUM, MAX, private-plan and monitoring grants, not just tier/price. If a change both improves and reduces rights, **schedule the entire change for next billing period**, preserving current paid rights in the interim and requiring appropriate confirmed billing before applying changed entitlements. Pure upgrades with no reductions may take effect sooner after confirmed billing according to established Python provider rules. If a downgrade makes a tenant over capacity, retain existing products, competitors and connections; block additional growth rather than deleting business records. Keep Python Stripe scheduling and defend against stale/delayed events and retries.

**Outstanding details / gates**

No additional mixed-change/overcapacity policy choice is specified as pending. Preserve established Python confirmed-billing rules; release still requires native concurrency, provider-state and compatibility evidence and separately scoped implementation authorization.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-TRANSITION-001-effective-grants-and-mixed-plan-change.md).

## IMPORT-001 — Canonical import, inventories and overlap

| Current Node behavior | Current Python behavior |
|---|---|
| Node provides typed invoice/inventory preview/review/confirm, ID/SKU/name conflict matching and external store-owned links. Woo stock uses reserved warehouse_location strings, not a separate warehouses table. | Python sales promotion already writes transactions plus invoice/item mirrors with content+occurrence identity and barcode matching. Generic DB/API workers stage but do not call canonical promotion. Python RAG upload is optional PDF registration through extraction; no separate mounted rag/upload endpoint was found. |

**Owner-selected policy (verbatim)**

**Selected: promotion A + inventory A + overlap A.** Keep Python canonical transactions plus invoice/item mirrors and existing product identity. Auto-promote **strictly validated and unambiguous rows**; preview, hold and require review for conflicts, invalid values and ambiguous identity. Maintain **source-owned inventory lineage** for Shopify, WooCommerce and manual imports; never silently overwrite conflicting stocks. Detect manual/store overlapping sales using available external references, source/invoice metadata and product mappings, but do not coalesce distinct legitimate identical sales. Preserve IDs/history, taxes/shipping/refunds, idempotent retries, accurate partial statuses, tenant RLS and no duplicate revenue/stock decrements. **PENDING:** any universal source priority and shared-key collision rules not already supported by verified identity.

**Outstanding details / gates**

PENDING: any universal source priority and external shared-key collision rules not already supported by verified identity. Do not guess precedence or merge legitimate identical sales.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-IMPORT-001-canonical-identity-stock-and-invoice-ownership.md).

## PRICE-001 — Recommendation evidence and fallback

| Current Node behavior | Current Python behavior |
|---|---|
| Actual Node getPricingRecommendation filters original_currency===product.currency for the scoring sample; converted observations are references only. It requires current 30-day market/7-day verified FX references, rejects newest invalid data, returns UNKNOWN/no charge without usable local sample, and independently recomputes localMarketTarget before guardrails. | Python also treats cross-currency as reference only; old observations are annotated after 90 days, not automatically excluded. It has wider-market/peer/internal fallback and demand/stock hold context. These are real remaining differences; cross-currency blending is not one. |

**Owner-selected policy (verbatim)**

**Selected: A (qualified fallback).** Preserve Python's pricing inference, demand/stock context and qualified peer/wider-market/internal fallback when direct local competitor evidence is inadequate; label the factual basis, confidence and limitations, and never imply fallback is verified local market pricing. Incorporate missing Node eligibility, currency/evidence validity, guardrails, entitlement and usage protection for single and bulk routes. Preserve history and evidence provenance. **PENDING:** maximal admissible observation age, FX/reference freshness where applicable and handling of a newest invalid observation. Do not sign off on final input policy until set.

**Outstanding details / gates**

PENDING: maximal admissible observation age, FX/reference freshness where applicable and newest-invalid-observation handling. Final input policy is not signed off until these values/rules are approved.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-PRICE-001-pricing-evidence-freshness-and-fallback.md).

## MPI-001 — Review samples and visible scoring

| Current Node behavior | Current Python behavior |
|---|---|
| Node validates subject ownership and safe/allowed/nonfuture/nonempty/dedup/newest-100 reviews. Below the minimum it returns UNKNOWN/null and does not call inference; upstream insufficient results also suppress the final reliable score. | Python scores persisted sentiment rows across BUSINESS/PRODUCT/COMPETITOR, retains weighted contributions/volume damping and returns top-level OK with nested LOW_SAMPLE_SIZE for nonempty small samples. Zero usable reviews are UNKNOWN, not zero. COMPETITOR IDs are global_competitor_id linked through tenant_competitors. |

**Owner-selected policy (verbatim)**

**Selected: B (suppress unreliable numeric scores).** Preserve Python sentiment classification, weighted scoring and historical evidence for **BUSINESS, PRODUCT and COMPETITOR**. Validate tenant ownership/subject identity; port Node eligibility/deduplication/input validation and usage protections. When eligible reviews are below approved minimum, show **UNKNOWN/null**, not numeric zero or a misleading score; do not re-charge for repeated summary reads. **PENDING:** exact eligible-review minimum, sampling cap, recency and source rules. Do not invent these thresholds.

**Outstanding details / gates**

PENDING: minimum eligible-review count, sampling cap, recency and source rules. Numeric-score visibility and applicable release acceptance depend on these approvals; no threshold is inferred.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-MPI-001-mpi-eligibility-sample-and-public-reliability.md).

## ACCOUNTING-001 — Failed, partial and ambiguous work

| Current Node behavior | Current Python behavior |
|---|---|
| Node pricing records request/product identity, reserves one feature use and releases on UNKNOWN/failure/expiry; successful response charges. Ingestion can retain partial progress/retry state. These are feature counts, not actual provider cost. | Python credits distinguish sent/measured/billed-unreported provider work, conservatively charge stale reservations and support audited adjustment. Task 6 retains replayed report usage conservatively when failure cannot prove no usable delivery; extraction batches may commit before a later failure. |

**Owner-selected policy (verbatim)**

**Selected: feature A + uncertain-delivery B.** Consume feature allowances for **usable retained outputs** under the applicable defined metering unit; refund/release proven unused reservations and account for confirmed partial commits. If provider work may have completed but client delivery cannot be proved, provide a **controlled, auditable, idempotent customer allowance adjustment** while **retaining actual provider cost** in Python's immutable ledger. Maintain separate customer feature allowances, customer Data/AI Credits and actual provider USD spend; enforce durable request/period receipts, once-only settlement, crash recovery, no duplicate retry charges and period-safe adjustments. **PENDING:** exact per-feature metering units and allowable adjustment limits where not already contractually established.

**Outstanding details / gates**

PENDING: exact per-feature metering units and allowable ambiguous-delivery adjustment limits where not already contractually established. Customer allowance adjustments never erase actual provider cost or rewrite the immutable Credits ledger.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-ACCOUNTING-001-partial-failure-replay-and-crash-charging.md).

## PRIVACY-001 — Shopify privacy and retained records

| Current Node behavior | Current Python behavior |
|---|---|
| Node Shopify source has signed privacy/data-request/redact topics, delivery dedup, source-linked exclusions/reports and process_shopify_event side effects. Source-owned/shared product and invoice references can differ. | Python has retained business invoices, manual/shared products and user/company deletion/export paths but no dedicated Shopify privacy consumer. A customer-company delete endpoint is not an equivalent signed provider request. |

**Owner-selected policy (verbatim)**

**Selected: A (targeted privacy erasure/restriction).** Implement verified signed Shopify privacy/uninstall/data requests, including shop/topic/delivery checks, dedupe, recoverable audited jobs, tenant attribution and fences preventing reimport of data erased under a valid request. Erase or restrict **Shopify-attributable personal information** that is covered by the request; retain financial/audit records only where applicable law and an approved policy permit or require. Preserve Python's existing company export/delete protections and unrelated manual/customer data. **PENDING for legal/operational sign-off:** jurisdictions, specific affected fields, retention schedules, legal bases/exceptions and permission/approval for irreversible actions. Do not invent retention periods or execute irreversible deletion without authorization.

**Outstanding details / gates**

PENDING legal/operational sign-off: jurisdictions, specific affected fields, retention schedules, legal bases/exceptions and permission/approval for irreversible actions. This policy selection does not authorize deletion or invent any retention duration.

Policy status: **SELECTED**. Owner/date: **owner; 2026-10-20**. Implementation: **NOT AUTHORIZED**. [ADR](architecture/ADR-PRIVACY-001-provider-privacy-and-retained-business-records.md).
