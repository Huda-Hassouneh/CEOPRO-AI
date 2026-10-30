# Source baseline verification — Phase 0V

**Correct audited post-Task-6 working content: VERIFIED. Reviewed clean source commit: NOT SUPPLIED — SOURCE-001 BLOCKED.** No older source was substituted. No commit, reset, rebase, overwrite or merge was performed.

| Identity | Observed value |
|---|---|
| Python branch / HEAD | `main` / `1de393c77dfc6db9d8722d8a611d2384d64d12c0` |
| Python uploaded ZIP SHA-256 | `873cc27c3d98a9a061a843d4a63948ac7db178555c4c8757fbee31c59b2285e7` |
| Python original files | 1,283, all byte-identical to the supplied Phase 0 manifest |
| Python path/content manifest fingerprint | `d91c71d593fbcc23ccb881bb1f85181c8d9e439532caaf5ad6a1bfa2dfadc269` |
| Node ZIP SHA-256 | `c8a3bf461a36e61cba9640d6c791545349db5a3abee09425056b21b02a407788` |
| Node original files | 2,839, all byte-identical; strictly read-only |
| Node path/content manifest fingerprint | `d84f9673bb403f550cfa57ec54b407a8c0fe246881196a48d4f7b9aba6d9b9a9` |
| Current approved architecture ZIP at entry | `dd3eb1213dac47d2f2accec5c5fe53256265e70f86376cb7c387e8fb5ab524c9`; 136 documents matched byte-for-byte |
| Owner register SHA-256 | `7ffc98334396ae8cca8219f561c2d151b25cfca5c7c9f85fcb5675e9b24d91c8` |
| Staged changes | Empty staged diff, 0 bytes |
| Incoming tracked differences from HEAD | 5 semantic source paths; 412 CRLF-only paths |
| Incoming untracked non-integration paths | 34; includes earlier verification harness, Task 6 migration/tests and reports |

The manifest fingerprint hashes the sorted concatenation of `path + NUL + per-file SHA256 + newline`. Full per-file SHA-256 manifests remain in evidence/SUPPLIED_CONTENT_HASHES.json. The HEAD alone is **not** the tested version: the exact uncommitted working content above is. No remote freshness or team approval is inferred. Local Node filename is `my-version.zip`, not `(1)`; its exact digest is the same frozen reference identified by Phase 0R and Task 6. There is no content-version substitution.

## Exact Task 6 semantic production delta versus HEAD

| Existing modified path | Working SHA-256 | Reviewed intended correction |
|---|---|---|
| `backend/src/ai/billing/store.py` | `3400935d5e50f4604923ff0d55781ae2de6e5ff03546b2a5fbe4861a947db403` | Tenant assignment serialization, current replacement protection, same-tenant upserts, monotonic succeeded invoice history |
| `backend/src/ai/billing/webhooks.py` | `4856e699c119d593efb1e75853b12ac969bbbf701019d019122eddc9fb35e010` | Invoice/subscription provider reconciliation under locks; provider identity checks and retry/rollback |
| `backend/src/ai/core/usage.py` | `2944ddc08c002d7fa62188bfc0eb11319a01b57c9e4742d83763d35c387c16c9` | Positive integral quota amounts; active/membership/actor/period/fingerprint checks before replay; UUID-bound once-only release |
| `backend/src/ai/routers/dashboard.py` | `3de605c711fefb0f0e8af894eac9bd0209c36c838a35373045487672605ec2fb` | Existing demand-prediction dependency added only to forecast alias metadata |
| `backend/src/ai/routers/reports.py` | `8c1e0e839d86e6ca341eb433020109d5be1d860d8b81086aa49e613789eb0153` | Stable report parameter fingerprint passed with authenticated actor to existing usage owner |

New production migration already supplied: `backend/src/infrastructure/database/migrations/20261024000000_report_request_identity.sql` — period-aware key PK, request_fingerprint, replayed flag, UUID receipt; existing history/RLS/grants preserved by intended SQL. This phase added/applied **zero** production migrations. Raw SQL is not itself repeat-idempotent (ADD COLUMN/DROP CONSTRAINT); repeat behavior must be verified through the existing migration runner's applied-file ledger, not by blindly executing this SQL twice. Empty/populated migration and native role preservation were NOT RUN here.

## Task 6 tests and verification inventory

`backend/tests/remediation/{__init__,conftest,test_commercial_boundaries,test_forecast_gate,test_migration_upgrade,test_native_concurrency}.py` are the supplied remediation harness. `backend/tests/billing/test_database.py` and `backend/scripts/integration_review.py` contain prior Task 6 test maintenance. These are untracked versus the older Git HEAD; the 34 incoming untracked files are not all newly created by Task 6 or by Phase 0V. All are individually enumerated and hashed in SOURCE_BASELINE_PREFLIGHT.json. The uploaded Task 6 report and in-repository report/log/XML remain prior evidence; 140 passed/10 skipped and PGlite 17.5 are **not** native results from this task.

Source review confirmed each of the five intended corrections and the matching tests, not their native correctness. Current offline checks exercise non-DB policy/adapter/static gate tests, while actual SQL, late-invoice monotonic persistence, old/new-subscription assignment races, report actor/period/receipt behavior and forecast gate with real SQL remain skipped. Native lock ordering, concurrent transactions, real runtime-role login and populated upgrades cannot be certified by reading the patch.

## Exact provenance evidence and required team action

[Preflight facts](evidence/phase0v/SOURCE_BASELINE_PREFLIGHT.json), [full Git status](evidence/phase0v/GIT_STATUS_BEFORE.txt), [Task 6 semantic diff](evidence/phase0v/TASK6_UNSTAGED_SEMANTIC_DIFF.patch) and [untracked inventory](evidence/phase0v/GIT_UNTRACKED_BEFORE.txt) preserve focused provenance. The broad and empty patch snapshots are described below; they are not included in the proposed Git commits.

**Request to authorized team:** review the five-file semantic repair, migration, intended verification files and incoming line-ending noise; establish a genuinely reviewed clean post-Task-6 commit through your workflow and provide its SHA/full diff/manifest. Do not discard repairs or silently stage unrelated CRLF changes. This task does not authorize us to create that commit. Until supplied, SOURCE-001 remains BLOCKED and the tested version must be named HEAD-plus-working-manifest, not clean main.

Node Git metadata was not supplied in the archived reference, so no Node commit or Git status is invented. Its original file/ZIP hashes are the available provenance. There are 78 existing migration source files in MIGRATION_SOURCE_INVENTORY.csv; none was executed here. TASK6_FORECAST_BODY_CHECK.json confirms the forecast handler body still matches HEAD exactly, apart from its intended access decorator/import changes.

## Local commit packaging and source-hash reconciliation

The root `PHASE1A_DELIVERY_MANIFEST.json` and the archive's `FINAL_SOURCE_HASHES.json` / `FINAL_RECONCILIATION.json` are preserved byte-for-byte as historical delivery evidence. Their source digest, `9b7331f67221ce06b7d2850becd1edef9f1e24fcda3cbed861b73c69526fb848`, describes the original 1,308-path delivery snapshot; it is not a Git commit ID and does not include later local documentation edits.

After fixing the Windows-only test path resolution in `frontend/tests/locales.test.mjs`, the same canonical 1,308-path calculation yields `1da3b57777c2a358fb38d4ed2546771b1e7c6a4e37fe4a790486739a41ed1a1a`. The locale test is the only path whose content hash differs from the original map (`1db662dde087aca2161d2ca7ee6dd4bc441a5f2e33f13484653534c155f4fd76` originally; `1cc520cfedf82c04538a8f1fa6ed602eaf87d8b497e23c3d300c11fed528a357` now). No original manifest or hash record was rewritten.

The following supplied patch snapshots remain local but are excluded from the proposed documentation commit:

- `evidence/phase0v/GIT_UNSTAGED_FULL_DIFF.patch` and `evidence/phase1a/STARTING_GIT_DIFF.patch` are broad working-tree snapshots (about 4.9 MB each) containing unrelated changes and line-ending noise; they would misrepresent this delivery if committed as focused evidence.
- `evidence/phase0v/GIT_STAGED_DIFF.patch` and `evidence/phase1a/STARTING_STAGED_DIFF.patch` are empty files and add no verification value.

The focused `SUBSCRIPTION_REMEDIATION.patch` is retained because the Task 6 package manifest lists it and its hunks are limited to the five Task 6 production files and the report-request migration. It is provenance for review, not an instruction to reapply the changes. Its original Task 6 ZIP SHA-256 is `78328a7b52b57e933b8fd543650d2d98a816e5868a78ae002fcbfd496922f0d2`.

The staged whitespace check has 21 historical-file exceptions. Each file's SHA-256 was verified against its original ZIP entry, and, where available, the recorded Phase 1A starting hash. Git's staged blobs differ from the ZIP bytes only by CRLF-to-LF normalization; the original trailing spaces are present in the delivered bytes and remain in the staged content. The 21 exact paths are:

- `SUBSCRIPTION_REMEDIATION.patch`
- `docs/keel-integration/evidence/phase0r/SCHEMA_DDL_OBJECTS.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_AUTH.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_CONNECT.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_CREDIT.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_CUSTOM.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_ENT.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_IMPORT.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_MPI.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_PLATFORM.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_PRICE.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_PROMO.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_SHOP.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_STORE.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_SUB.csv`
- `docs/keel-integration/evidence/phase0r/SCHEMA_LINEAGE_WOO.csv`
- `docs/keel-integration/evidence/phase0v/TASK6_UNSTAGED_SEMANTIC_DIFF.patch`
- `docs/keel-integration/reference/KEEL_PHASE0R_OWNER_ARCHITECTURE_DECISION_REGISTER.md`
- `docs/keel-integration/reference/KEEL_PHASE0V_WORK_PROMPT_20261020.md`
- `docs/keel-integration/reference/LEDGER_TEMPLATE.md`
- `docs/keel-integration/reference/PHASE0_INDEPENDENT_REVIEW_AND_NEXT_PROMPT.md`

The check is run with pathspec exclusions for only those 21 files; every other staged file must pass. The unrestricted `git diff --cached --check` does not pass and is not claimed to pass. No source artifact or Git whitespace configuration was changed for these exceptions. The Task 6 report, source-integrity/capability records, PGlite XML and run log are retained with their environment limitations. The 214-file architecture package (about 43 MB) also contains large structured source/schema/capability mapping CSVs; these are retained as traceability evidence, not temporary logs or dependency output. The focused Task 6 semantic diff and bounded test logs/reports remain eligible documentation evidence. Original archive entries and hashes remain auditable from the preserved manifests; the repository commit package is intentionally not represented as a byte-identical copy of the archive.
