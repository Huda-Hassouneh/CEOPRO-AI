# Source evidence index

All source paths are relative to the frozen Python or read-only Node root. Hashes bind evidence to supplied bytes. Each capability row joins by capability_id and domain; source search is not test proof.

| Evidence | Use |
|---|---|
| INPUT_ARCHIVE_HASHES.json / SUPPLIED_CONTENT_HASHES.json | Input identity and all original non-Git byte hashes |
| ACTIVE_PYTHON_ROUTES.csv / FRONTEND_HTTP_CONTRACTS.csv | Actual Python mounted source handlers and both frontends HTTP call candidates |
| ROUTE_CANDIDATES.csv / REACHABILITY.csv | Broad route declarations and entrypoint/indirect/unverified status; no false DEAD classification |
| FUNCTION_CALL_INDEX.csv / CAPABILITY_SYMBOL_REFERENCES.csv | Exact source function lines/call targets and capability domain helper references |
| FUNCTION_BEHAVIOR_FACTS.csv | Python transitive helper argument names, return dictionary keys, conditional branches, SQL/error/commit/reserve/settle callsite lines |
| IMPORT_GRAPH_RESOLVED.csv / TRANSITIVE_CAPABILITY_DEPENDENCIES.csv | Best-effort recursive local import closure, unresolved attribute/dynamic terminals and dependency roles |
| SQL_OBJECT_LINEAGE.csv / PERSISTENCE_SURFACES.csv | Both schemas/migration DDL/policy/grant/trigger/functions and SQL read/write candidate surfaces |
| ENVIRONMENT_DEPENDENCIES.csv | Environment variable names and call sites; no secret values |
| TEST_CATALOG.csv / ACCEPTANCE_TEST_SPEC.csv | Existing test functions/files vs planned atomic acceptance assertions (NOT RUN) |
| INCOMING_GIT_STATUS.txt / INCOMING_SEMANTIC_DIFF.txt | Pre-existing archive dirt; not Phase 0 changes |
| backend-baseline.* / frontend-*.log | Actual available baseline checks |
| PHASE0_VERIFICATION.json / SOURCE_INTEGRITY_FINAL.json | Original-file protection, coverage/links/ledger validation and completion boundary |
| verify_phase0.py | Re-run document/manifest validation from approved roots, without modifying source |

The full contract is copied without editing into ../reference/EXECUTION_CONTRACT.md. SQL/lexical indexes can contain comments/dynamic fragments; resolve effective schema under native PostgreSQL before implementing. No private `.env` file contents or provider credentials are copied into these artifacts.
