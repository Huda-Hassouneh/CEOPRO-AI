# Document Storage test results

Status: **source audit complete; live database and MinIO E2E blocked**.

The source contract run produced **7 passing architectural checks and 6 failing regression checks**. The six failures represent confirmed source gaps listed in `README.md`, not infrastructure failures. Playwright completed with **9 skipped/BLOCKED scenarios** because no disposable DB, API, tenant fixtures, cleanup fixture, or MinIO endpoint is configured.

| Area | Status | Reason |
| --- | --- | --- |
| RAG route, BYTEA schema, tenant transaction | Source contract | Static source/migration verification only |
| Storage catalog and capacity resolver | Source contract | Static source verification only |
| Frontend size and extension parity | Regression | Current UI/API/client limits disagree |
| RAG processing status mapping | Regression | List client discards persisted status |
| Atomic storage quota | Regression | Check then insert has no reservation |
| Delete and capacity reclamation | Regression | No delete route/UI |
| Tenant-qualified summary object key | Regression | Current key omits tenant ID |
| PostgreSQL live upload/read isolation | BLOCKED | No safe disposable DB/API/tenant fixture |
| MinIO tenant policies and cleanup | BLOCKED | No disposable MinIO endpoint or restricted test credentials |
| Business upload vs retained-storage accounting | Regression | Transient upload size is checked, retained metadata total excludes it |

Do not interpret source contracts or skipped Playwright registrations as end-to-end proof. Re-run after the regressions are fixed and real fixture-specific assertions are implemented.

The previously recorded cross-feature baseline remains in `tests/reports/document-extraction/TEST_RESULTS.md`; it was not rerun as part of this storage-only task.
