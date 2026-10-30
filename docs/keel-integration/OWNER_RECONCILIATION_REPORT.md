# Owner architecture selections — reconciliation report

**All 13 existing ADRs now record the owner-selected architecture/policy direction dated 2026-10-20.** Implementation and production release remain **NOT AUTHORIZED**. This report supersedes earlier all-ADR-pending statements; earlier source/test reports remain historical.

Authority: [supplied consolidated owner register](reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md), copied byte-for-byte. Each ADR contains its complete selection verbatim, an explicit policy-selected status, approval provenance, pending-detail section and implementation/release prohibition. [Decision index](DECISION_REGISTER.md) and [owner worksheet](OWNER_DECISION_WORKSHEET.md) record the same selections. No unselected alternative remains presented as the current decision.

| Decision | Recorded selection |
|---|---|
| AUTH-001 | Verify before permanent new identity/workspace; fail-closed revocation |
| AUTH-002 | Strict platform authority; exceptional financial/spend powers reserved to Platform Owner |
| CATALOG-001 | Preserve current Python commercial terms; port catalog management capabilities |
| ENT-001 | Existing Credit-based competitor policy; each active persistent connection counted once; grandfather rights |
| PROMO-001 | Per tenant; initial invoice settlement including valid zero-total invoices; no discounted-custom stacking |
| CUSTOM-001 | Acceptance alone never activates; normal confirmed Stripe precedence; bounded owner-authorized exceptions |
| CUSTOM-002 | Cost-based engine; initial USD checkout; approved FX frozen within quote validity |
| TRANSITION-001 | Entire mixed change next billing period; keep existing overcapacity data, block growth |
| IMPORT-001 | Auto-promote validated unambiguous rows; source-owned inventory; safe overlap detection |
| PRICE-001 | Qualified, labeled fallback with evidence, eligibility, entitlement and usage protections |
| MPI-001 | UNKNOWN/null for insufficient approved sample; preserve weighted scoring and all three subjects |
| ACCOUNTING-001 | Usable retained output allowance charging; audited uncertain-delivery adjustment; preserve actual provider costs |
| PRIVACY-001 | Verified targeted attributable-personal-data erasure/restriction and reimport fences; lawful retention only |

The summaries above do not replace the full owner text in each ADR. Exact rates, margins, fees, FX source, quote validity/renewal/approval rules, per-promo terms, source rollout impact, exceptional overlapping grant semantics, observation freshness, MPI thresholds, metering/adjustment limits, import collision/priority rules and privacy legal/field/retention/destructive-action permissions remain **PENDING** as specified. No new value or legal conclusion was inferred.

Only documentation under `docs/keel-integration/**` changed. The unified ledger retains prior phase entries and adds every owner-reconciliation operation, reason, affected decision and verification. The new verifier checks the owner's text exactly, all 13 states, pending details, original Python/Node hashes, unchanged HEAD, document links, actual Git inventory and an actual Git no-index diff against the hash-checked prior 129-file documentation archive. Exact operations/counts/results are in [verification JSON](evidence/owner-decisions/OWNER_RECONCILIATION_VERIFICATION.json).

Run `python docs/keel-integration/evidence/verify_phase0.py --python-root <absolute Python root> --node-root <absolute Node root>` to reproduce current read-only checks; add `--write-result` only to refresh the document result. Older Phase 0/0R verifier results are historical snapshots and still describe their earlier pending-owner state.

No production source, frontend, migration, algorithm, provider, credentials or database was changed or contacted. No production/native/provider/browser tests were rerun; none are newly certified. SOURCE-001, native Phase 0V, sandbox certification and end-to-end release gates remain unchanged. No commits, pushes, merge or deployment occurred. Next implementation still requires a separately scoped owner instruction; material pending details must be resolved before affected behavior is enabled.
