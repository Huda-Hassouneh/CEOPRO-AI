> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Architecture decision register — owner selections recorded

**13/13 policy directions SELECTED as of 2026-10-20.** Numerical, contractual, legal and operational specifics explicitly left open remain PENDING. **Implementation and production release NOT AUTHORIZED.**

Python is the sole operational authority; Node and its AI subtree remain read-only. [Supplied owner register](reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md) is the authority. [Worksheet](OWNER_DECISION_WORKSHEET.md) includes exact selections and current-source comparisons.

| Decision | Selected direction | Policy status | Implementation |
|---|---|---|---|
| [AUTH-001](architecture/ADR-AUTH-001-identity-bootstrap-and-session-policy.md) | signup B + revocation A | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [AUTH-002](architecture/ADR-AUTH-002-platform-authority-and-role-boundaries.md) | A (strict platform ownership) | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [CATALOG-001](architecture/ADR-CATALOG-001-catalog-trials-and-existing-contracts.md) | A (preserve current Python commercial terms) | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [ENT-001](architecture/ADR-ENT-001-feature-rights-units-and-credit-crosswalk.md) | competitor A + source A + rights A | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [PROMO-001](architecture/ADR-PROMO-001-promotion-authority-redemption-and-stacking.md) | reuse A + consumption A + stacking A | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [CUSTOM-001](architecture/ADR-CUSTOM-001-quote-acceptance-versus-activation.md) | manual-contract A; Stripe normally precedes manual | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [CUSTOM-002](architecture/ADR-CUSTOM-002-quote-economics-provider-costs-and-fx.md) | cost-based A + USD-only initial checkout + frozen approved FX during quote validity | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [TRANSITION-001](architecture/ADR-TRANSITION-001-effective-grants-and-mixed-plan-change.md) | mixed A + overcapacity A | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [IMPORT-001](architecture/ADR-IMPORT-001-canonical-identity-stock-and-invoice-ownership.md) | promotion A + inventory A + overlap A | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [PRICE-001](architecture/ADR-PRICE-001-pricing-evidence-freshness-and-fallback.md) | A (qualified fallback) | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [MPI-001](architecture/ADR-MPI-001-mpi-eligibility-sample-and-public-reliability.md) | B (suppress unreliable numeric scores) | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [ACCOUNTING-001](architecture/ADR-ACCOUNTING-001-partial-failure-replay-and-crash-charging.md) | feature A + uncertain-delivery B | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |
| [PRIVACY-001](architecture/ADR-PRIVACY-001-provider-privacy-and-retained-business-records.md) | A (targeted privacy erasure/restriction) | SELECTED — owner, 2026-10-20 | NOT AUTHORIZED |

## Outstanding specifics

- **AUTH-001:** No additional signup/revocation policy choice is specified as pending in the owner register. Preserve existing-user/session compatibility; rollout details and implementation permission remain separate gates.
- **AUTH-002:** No additional platform-authority policy choice is specified as pending. Actual assigned permissions and exceptional owner authorizations must be explicit and audited; no impersonation or other unstated powers are granted.
- **CATALOG-001:** Any future commercial catalog change remains PENDING a separately approved version, cohort, exact values, effective date and impact review. Existing Python commercial terms remain unchanged.
- **ENT-001:** PENDING: effective-rights impact assessment, grandfathering and separate rollout approval where active persistent-source counting changes customer access. Future custom-contract count caps require a separately approved contract and values; no new fixed public competitor cap.
- **PROMO-001:** PENDING for each promotion: amount/type, eligible plans/currencies, dates, global/per-tenant limits, initial versus renewal scope and exact Stripe mapping. Architecture selection does not enable any unspecified promo.
- **CUSTOM-001:** PENDING: precise precedence, expiry and reconciliation semantics for exceptional overlapping manual/Stripe grants. No manual exception is activated by this ADR; Platform Owner authorization must be documented, audited and time-bounded.
- **CUSTOM-002:** PENDING: exact margins, cost floors/ratios, fees, multipliers, rounding increments, verified provider rates, FX source, quote expiry, renewal rules and instant-approval thresholds. Automated custom checkout stays blocked until required parameters are approved.
- **TRANSITION-001:** No additional mixed-change/overcapacity policy choice is specified as pending. Preserve established Python confirmed-billing rules; release still requires native concurrency, provider-state and compatibility evidence and separately scoped implementation authorization.
- **IMPORT-001:** PENDING: any universal source priority and external shared-key collision rules not already supported by verified identity. Do not guess precedence or merge legitimate identical sales.
- **PRICE-001:** PENDING: maximal admissible observation age, FX/reference freshness where applicable and newest-invalid-observation handling. Final input policy is not signed off until these values/rules are approved.
- **MPI-001:** PENDING: minimum eligible-review count, sampling cap, recency and source rules. Numeric-score visibility and applicable release acceptance depend on these approvals; no threshold is inferred.
- **ACCOUNTING-001:** PENDING: exact per-feature metering units and allowable ambiguous-delivery adjustment limits where not already contractually established. Customer allowance adjustments never erase actual provider cost or rewrite the immutable Credits ledger.
- **PRIVACY-001:** PENDING legal/operational sign-off: jurisdictions, specific affected fields, retention schedules, legal bases/exceptions and permission/approval for irreversible actions. This policy selection does not authorize deletion or invent any retention duration.

## Next authorization gate

Preserve the supplied post-Task-6 source snapshot and establish its reviewed clean commit (SOURCE-001). Native Phase 0V and separate provider certifications remain required. After any material pending detail is resolved, the owner must separately authorize one bounded implementation slice. Policy selection alone authorizes no source, migration, payment, deletion, commit, merge or deployment action.
