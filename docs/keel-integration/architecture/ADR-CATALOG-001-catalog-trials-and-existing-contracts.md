# ADR CATALOG-001: catalog trials and existing contracts

Status: **OWNER POLICY SELECTED — implementation NOT AUTHORIZED**.
Owner selection recorded: **2026-10-20**, by the owner through the supplied consolidated register. No additional personal approval identity is inferred.
Affected capabilities: SUB-001/SUB-002/SUB-012/SUB-013; PLATFORM-003.

## Approved architecture and business direction

**Selected: A (preserve current Python commercial terms).** Keep existing Python public plan prices, limits, trial eligibility/durations, price mappings, historical contracts, private terms and grandfathered access unchanged. Port missing Node-style catalog management, versioning, configurability and history to Python without automatically changing customers' purchased terms. Any future new commercial catalog requires a separately approved version, customer cohort, values, date and impact review.

The paragraph above reproduces the owner's CATALOG-001 selection verbatim. It is a policy approval, not evidence that any production behavior changed.

## Outstanding details and enablement gates

Any future commercial catalog change remains PENDING a separately approved version, cohort, exact values, effective date and impact review. Existing Python commercial terms remain unchanged.

**Implementation permission: NOT GRANTED. Production release permission: NOT GRANTED.** SOURCE-001, native Phase 0V PostgreSQL 17/RLS/concurrency, provider certification and applicable end-to-end checks remain open. A separate bounded task must name writable paths, migrations, tests and acceptance criteria before production edits.

## Context and confirmed source behavior

Node: Node 21-code catalog, plan-feature/configuration/private plans and independent subscription commercial records. Node seed price 49 is a fixture, not production policy.

Python: Migration 20261020000000 displays Standard/Plus/Pro/Custom, prices USD 55/140/350 and trials 14/14/7; 20261021000000 supersedes Pro products/seats to 500/50; legacy standard/pro price mappings remain.

Source/function evidence: see the matching atomic rows in CAPABILITY_TRACEABILITY.csv and evidence/CAPABILITY_SYMBOL_REFERENCES.csv. Detailed caller/data flow: FEATURE-billing.md. Both are bound to the hashes in SOURCE_BASELINES.md.

Read [source corrections](../SOURCE_TRACE_CORRECTIONS.md) and the exact Phase 0R caller/DTO/DDL evidence before relying on older source-inference wording. Current implementation facts are distinct from the selected target policy.

## Alternatives and decision outcome

The owner selected **A (preserve current Python commercial terms)**. Earlier alternatives were evaluated in the Phase 0R worksheet; the selected direction above replaces the former unresolved recommendation. Unselected options are not enabled. Outstanding details remain limited by the explicit PENDING list and the owner register's interpretation rule.

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

Policy approval source: [KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md](../reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md), section **CATALOG-001 — Commercial catalog**. [Owner worksheet](../OWNER_DECISION_WORKSHEET.md) and [decision index](../DECISION_REGISTER.md) record the same selection. No implementation or runtime acceptance tests were performed during this documentation reconciliation.
