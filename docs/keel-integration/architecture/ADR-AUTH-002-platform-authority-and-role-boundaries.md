# ADR AUTH-002: platform authority and role boundaries

Status: **OWNER POLICY SELECTED — bounded Phase 1A IMPLEMENTED; isolated tests PASS; native integration/release BLOCKED**.
Owner selection recorded: **2026-10-20**, by the owner through the supplied consolidated register. No additional personal approval identity is inferred.
Affected capabilities: PLATFORM-001 through PLATFORM-005; AUTH-009/AUTH-011; CUSTOM-008/CUSTOM-012.

## Approved architecture and business direction

**Selected: A (strict platform ownership).** Keep tenant owner/admin separate from KEEL platform owner/admin. Platform admins may manage companies, ordinary catalog/promotions/quotes within assigned permissions. **Only the Platform Owner** may authorize below-floor pricing, exceptional unpaid/manual financial access, or provider spending-control changes. Separate platform invitations from customer team invitations; enforce permission checks server-side with immutable audit trails. Tenant ownership never grants platform staff privilege.

The paragraph above reproduces the owner's AUTH-002 selection verbatim. It is a policy approval, not evidence that any production behavior changed.

## Outstanding details and enablement gates

No additional platform-authority policy choice is specified as pending. Actual assigned permissions and exceptional owner authorizations must be explicit and audited; no impersonation or other unstated powers are granted.

**Implementation permission: GRANTED for Phase 1A by the latest user instruction. Production release permission: NOT GRANTED.** The exact dirty Task 6 state was snapshotted before isolated edits; missing infrastructure blocks full verification/release, not this bounded implementation. Native PostgreSQL 17/RLS/concurrency, Redis, migration, full application and browser checks remain open.

## Context and confirmed source behavior

Node: Platform admin permission namespace and tenant membership/platformStatus gates; separate pricing override privilege.

Python: Tenant role checks exist; billing operator functions are CLI with approved_by/reason; no matching mounted platform API/dashboard.

Source/function evidence: see the matching atomic rows in CAPABILITY_TRACEABILITY.csv and evidence/CAPABILITY_SYMBOL_REFERENCES.csv. Detailed caller/data flow: FEATURE-auth.md. Both are bound to the hashes in SOURCE_BASELINES.md.

Read [source corrections](../SOURCE_TRACE_CORRECTIONS.md) and the exact Phase 0R caller/DTO/DDL evidence before relying on older source-inference wording. Current implementation facts are distinct from the selected target policy.

## Alternatives and decision outcome

The owner selected **A (strict platform ownership)**. Earlier alternatives were evaluated in the Phase 0R worksheet; the selected direction above replaces the former unresolved recommendation. Unselected options are not enabled. Outstanding details remain limited by the explicit PENDING list and the owner register's interpretation rule.

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

Policy approval source: [KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md](../reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md), section **AUTH-002 — Platform authority**. [Owner worksheet](../OWNER_DECISION_WORKSHEET.md) and [decision index](../DECISION_REGISTER.md) record the same selection. No implementation or runtime acceptance tests were performed during this documentation reconciliation.


## Phase 1A implementation evidence

The approved policy paragraph above remains verbatim. Production changes now implement the bounded AUTH-001/AUTH-002 foundation; historical context describes the frozen input, not current behavior. See [implementation report](../PHASE1A_IMPLEMENTATION_REPORT.md), [active source trace](../PHASE1A_TRACE_MAP.md), [migration compatibility](../PHASE1A_MIGRATION_AND_COMPATIBILITY.md), [native runbook](../PHASE1A_NATIVE_VERIFICATION.md) and [file ledger](../UNIFIED_FILE_CHANGE_LEDGER.md). No native integration success or wider commercial capability completion is implied. Owner-only financial approval records are not commercial executors; PLATFORM-003 remains unimplemented and PLATFORM-004/005 partial.
