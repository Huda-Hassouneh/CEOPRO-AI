# ADR ACCOUNTING-001: partial failure replay and crash charging

Status: **OWNER POLICY SELECTED — implementation NOT AUTHORIZED**.
Owner selection recorded: **2026-10-20**, by the owner through the supplied consolidated register. No additional personal approval identity is inferred.
Affected capabilities: ENT-010; CREDIT-003/CREDIT-004; IMPORT-011; PRICE-006.

## Approved architecture and business direction

**Selected: feature A + uncertain-delivery B.** Consume feature allowances for **usable retained outputs** under the applicable defined metering unit; refund/release proven unused reservations and account for confirmed partial commits. If provider work may have completed but client delivery cannot be proved, provide a **controlled, auditable, idempotent customer allowance adjustment** while **retaining actual provider cost** in Python's immutable ledger. Maintain separate customer feature allowances, customer Data/AI Credits and actual provider USD spend; enforce durable request/period receipts, once-only settlement, crash recovery, no duplicate retry charges and period-safe adjustments. **PENDING:** exact per-feature metering units and allowable adjustment limits where not already contractually established.

The paragraph above reproduces the owner's ACCOUNTING-001 selection verbatim. It is a policy approval, not evidence that any production behavior changed.

## Outstanding details and enablement gates

PENDING: exact per-feature metering units and allowable ambiguous-delivery adjustment limits where not already contractually established. Customer allowance adjustments never erase actual provider cost or rewrite the immutable Credits ledger.

**Implementation permission: NOT GRANTED. Production release permission: NOT GRANTED.** SOURCE-001, native Phase 0V PostgreSQL 17/RLS/concurrency, provider certification and applicable end-to-end checks remain open. A separate bounded task must name writable paths, migrations, tests and acceptance criteria before production edits.

## Context and confirmed source behavior

Node: Per-feature usage reservations/releases, pricing request identity and ingestion retry/recovery business rules.

Python: Task 6 conservatively retains replayed report usage; credits stale reservations charge; provider cost ledger distinguishes sent/measured/billed-unreported; uploads can commit before later error.

Source/function evidence: see the matching atomic rows in CAPABILITY_TRACEABILITY.csv and evidence/CAPABILITY_SYMBOL_REFERENCES.csv. Detailed caller/data flow: FEATURE-entitlements.md. Both are bound to the hashes in SOURCE_BASELINES.md.

Read [source corrections](../SOURCE_TRACE_CORRECTIONS.md) and the exact Phase 0R caller/DTO/DDL evidence before relying on older source-inference wording. Current implementation facts are distinct from the selected target policy.

## Alternatives and decision outcome

The owner selected **feature A + uncertain-delivery B**. Earlier alternatives were evaluated in the Phase 0R worksheet; the selected direction above replaces the former unresolved recommendation. Unselected options are not enabled. Outstanding details remain limited by the explicit PENDING list and the owner register's interpretation rule.

## API, state and worker flow — future implementation constraints

Extend existing Python routers/services/frontend clients additively. Existing public fields and error envelopes remain unless a separately approved adapter/version is provided. Any durable operation has tenant/actor/period/request fingerprint/revision and lease/receipt linkage. Authorize API → persist intent/outbox → claim/revalidate worker → provider/local work → conditional canonical write/settle → status/read model. Never hold long SQL transactions across provider network calls; signed webhooks persist/reconcile under existing billing owner.

These are design constraints for a separately authorized implementation, not implemented workflows. Apply the exact selected policy above rather than inventing commercial, metering, numeric or privacy values.

## Data, backfill and compatibility

Preserve the existing Python behaviors and historical contracts expressly named in the approved direction. No destructive migration, data deletion, session reset, catalog rewrite or grant cutover is authorized by this ADR. Use forward-only schema changes with a reversible rollout plan, tenant-impact comparisons, idempotency and native empty/populated/repeat migration verification when specifically authorized. Proposed file scopes in IMPLEMENTATION_PHASES.md require review against this selection before use; this ADR does not authorize those scopes.

## Security, RLS and metering

Existing Python tokens/memberships remain authority. Runtime ceopro_app/service roles cannot be superuser/BYPASSRLS; global bootstrap/operator tasks use narrowly granted functions and audit, fixed search_path and parameterized SQL. No credentials in DTOs/logs. Feature reservation is distinct from Data/AI credits and provider USD spend; both required controls apply where relevant. Cleanup/reconciliation identity must not become an unrestricted customer action.

## Failure and operational risks

Use typed 401/403/404/402/409/422/502/503 consistent with current contracts; preserve idempotency/tenant identity on retries. Provider success with local failure requires reconciliation rather than a second provider action. Existing-user migration, concurrent requests and delayed jobs/events are release blockers until demonstrated. Do not enable the affected path based on fixture-only proof.

## Acceptance proof and decision record

Run affected AT IDs from evidence/ACCEPTANCE_TEST_SPEC.csv, the domain's existing regression tests, native PostgreSQL RLS/concurrency, populated migration rehearsal and frontend contract/E2E. Provider test mode/live sandbox where applicable. **Not executed as implementation acceptance tests in Phase 0.** Record exact command/runtime/commit/result/logs and reconcile ledger against Git diff before DONE.

Policy approval source: [KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md](../reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md), section **ACCOUNTING-001 — Failed, partial and ambiguous work**. [Owner worksheet](../OWNER_DECISION_WORKSHEET.md) and [decision index](../DECISION_REGISTER.md) record the same selection. No implementation or runtime acceptance tests were performed during this documentation reconciliation.
