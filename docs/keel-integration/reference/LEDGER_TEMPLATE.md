# KEEL — Unified File Change Ledger

**Destination repository:** AI team's Python/FastAPI main. **Node reference is strictly read-only.**

This is the single authoritative file-change record for the KEEL Python integration. Copy it to `docs/keel-integration/UNIFIED_FILE_CHANGE_LEDGER.md` in the destination repository when implementation starts. Add one entry for **every** added, modified, deleted or renamed tracked file, including tests, migrations, frontend, generated source (if intentionally version-controlled), docs and configuration.

**Baseline Python commit:** `PENDING_POST_TASK_6_BASE_SHA`  
**Current implementation commit:** `PENDING`  
**Node reference SHA-256/commit:** `PENDING`  
**Current phase:** `PENDING`  
**Ledger owner:** GPT Work implementation agent; audited by KEEL owner.

## Change log

| Phase | Capability ID(s) | Path within Python main repo | Operation | Why this file must change | Exact behavior added/modified/removed | Existing Python behavior protected | Schema/contract impact | Test evidence | Commit / status |
|---|---|---|---|---|---|---|---|---|---|
| _example only; delete on first use_ | SUB-CUSTOM-001 | `backend/src/ai/billing/example.py` | ADD | _Explain specific missing capability from approved ADR_ | _Mention exact functions, calculation, checks, side effects_ | _Explain what existing code is reused_ | _Forward migration ID or none; API contract_ | _Test path and result_ | _SHA / not started_ |

**Entry rules:**
- Use one row for each path changed; never combine different files into one row. If a file supports many capability IDs, list them all.
- Use `ADD`, `MODIFY`, `DELETE`, or `RENAME`. For `RENAME`, name both the old and new path or use paired rows.
- Avoid descriptions such as "fix", "update", "cleanup", "misc", or "improve" without an exact behavior and reason.
- A changed file that was subsequently reverted to baseline does not remain in the final diff; note the reverted attempt in the phase history if material.
- List the migration version, API/frontend contract change, and the actual executable tests used to verify it.
- The ledger itself and all architecture documents/tests belong in the ledger once added to Git.
- Do not commit real tokens, passwords, keys, live customer exports, temporary caches or debug artifacts.

## Git reconciliation at every phase gate

Run from the destination Python repository root after the phase is implemented and before declaring it complete:

```bash
# Replace the placeholder with the recorded phase base commit.
BASE_SHA='<phase-base-commit>'

git status --short
# Includes added, modified, renamed and deleted committed/staged changes relative to base.
git diff --name-status "$BASE_SHA" HEAD
# Includes worktree edits not yet committed.
git diff --name-status
# Include newly created unstaged files that Git diff does not show.
git ls-files --others --exclude-standard
```

**Review requirement:** Every delivered changed path from these outputs must have a matching row in the ledger. Check *path, action, reason, capability ID and tests*, not only counts. Use a machine-checkable path set, then review descriptions manually. Record the reconciliation at every phase.

| Phase | Baseline → current SHA | Git changed-path count | Ledger changed-path count | Missing paths | Extra/stale paths | Verified by | Result |
|---|---|---:|---:|---|---|---|---|
| PENDING | PENDING | 0 | 0 | PENDING | PENDING | PENDING | NOT VERIFIED |

## Cross-reference and release gate

Each row must be traceable to:
1. An atomic capability in `CAPABILITY_TRACEABILITY.csv`.
2. Its selected architecture note or ADR in `docs/keel-integration/architecture/`.
3. A test or a **clearly marked blocked/unrun** verification item in `TEST_EVIDENCE.md`.
4. Migration and rollback/disable instructions, when database state or contracts change.

**No release or phase completion if any delivered file is absent from this ledger or if its business reason, behavior or verification is unknown.**
