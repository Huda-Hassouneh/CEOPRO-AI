# Phase 1A delivery and application instructions

> Historical delivery instructions: the original Phase 1A package has already been reconciled into the local `integration/keel-task6-phase1a` branch. Do not reapply the archive over this checkout. The later authentication/platform stabilization overlay is documented in [PHASE1A_NATIVE_VERIFICATION.md](PHASE1A_NATIVE_VERIFICATION.md), with its current source hash in [POST_STABILIZATION_SOURCE_HASHES.json](evidence/phase1a/POST_STABILIZATION_SOURCE_HASHES.json). Historical archive manifests remain unchanged.

At original delivery time, this was a reviewable, uncommitted production-source package; it was not deployed or native-integration certified, and it included no Phase1B implementation.

## Files supplied

- `KEEL_Phase1A_Changes.zip`: added/modified production source, migration and tests at exact `CEOPRO-AI/` paths, plus the complete current `docs/keel-integration` review package, including unchanged prior architecture references. Dependencies, generated build caches, Node source and Git metadata are excluded. A root delivery manifest identifies every archived file by SHA256 and marks changed paths separately from unchanged review references.
- `KEEL_Phase1A_Report.md`: standalone copy of the implementation report. Relative evidence links resolve within the ZIP's review package.
- `KEEL_Phase1A_Starting_Snapshot.zip`: pre-edit recovery material containing the exact supplied Task6 source, incoming changes, prior architecture files and Git metadata. This is a recovery snapshot, not the implemented version.

## Safe review/application sequence

1. Preserve your current working tree and uncommitted/staged changes. Review the supplied starting source manifest and patches; do not reset or overwrite another person's work.
2. Compare the destination to the exact Task6 baseline: archive SHA256 `873cc27c3d98a9a061a843d4a63948ac7db178555c4c8757fbee31c59b2285e7`, HEAD `1de393c77dfc6db9d8722d8a611d2384d64d12c0` plus incoming repairs/migration/tests. `evidence/phase1a/PHASE1A_STARTING_HASHES.json` records all1,461 starting files. HEAD alone is insufficient. If source differs, review/reconcile differences before applying; do not substitute the older commit or overwrite newer changes.
3. Extract Changes.zip to a separate review directory. Compare `FINAL_INCREMENTAL_DIFF.json`, `FINAL_INCREMENTAL_GIT_NAME_STATUS.txt` and the Phase1A ledger. Existing Task6 files listed unchanged in the reconciliation must remain unchanged, except the one explicit live-principal predicate extension in usage.py.
4. Copy/reconcile only the approved Python-repository paths from `CEOPRO-AI/` into an isolated destination branch/worktree; the new migration uses the existing runner. Do not copy `.git` from the recovery ZIP into an active checkout. Do not copy anything into Node.
5. Run supported tests and all native gates in the verification runbook against the exact candidate. The manifest source-content digest identifies this delivered source. Native migration execution, shared/production writes and deployment require separate release authorization; this delivery performs none of them.

The live implementation copy remains `/workspace/scratch/327eb0b847b6/phase1a/CEOPRO-AI`, isolated branch `keel-phase1a-20261020`. No commit, push or merge was made. Full phase/release completion remains blocked by the expressly unverified native paths and application/browser acceptance obligations; catalog/commercial/outbox work is not silently marked complete.
