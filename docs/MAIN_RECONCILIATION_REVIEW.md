# Updated main reconciliation review

Finalized 2026-10-29. **PASS for the verified local reconciliation scope.**
Ready for separately authorized promotion into the protected integration branch;
no promotion or deployment is performed or authorized by this report. Verification
was executed on October 28 and its retained evidence rechecked on October 29.

## Source and isolation

- Original branch: `integration/keel-full-migration`,
  `66c18dd77cf2b2410c329a0d390e2da7c87959ab`.
- Merge input: verified cached `origin/main`,
  `2c3224e32be56dab02c35edc5d610c997089a410`.
- Shared ancestor/local main: `041f9f24a6a32d8d03d934a3f89b6b3734eecadb`.
- Review branch: `review/reconcile-main-20261028`.
- Separate worktree:
  `C:\Users\Mohamamd-P\AppData\Local\Temp\KEEL\review-main-20261028-66c18dd7`.
- One `merge --no-commit --no-ff` of the verified SHA was performed there.
  No fetch, pull, push, rebase, reset, branch switch or merge into the original
  integration branch/main occurred. Main's 28 commits are retained as ancestry.
- The local review merge commit containing this report has the two full SHAs
  above as parents. Identify its exact SHA with
  `git log -1 --format=%H -- docs/MAIN_RECONCILIATION_REVIEW.md`; the finalization
  response also records that SHA. No redundant follow-up commit is needed.

Setup created a fresh review-owned virtualenv, frontend dependencies, generated
credentials, Docker project and loopback ports. No original `.dev` fixture,
provider/Stripe credential, customer data or database dump was copied. Automatic
approval rejected optional Python reuse pointing into the active checkout;
fresh installation was used instead. Dependencies/models libraries were installed
from the existing manifests; model weights and live providers are separate checks.

## Actual conflicts and resolutions

All twelve conflicts were inspected against their indexed shared ancestor and
both branches. No blanket ours/theirs resolution was used.

| Conflicted path | Combined behavior |
|---|---|
| `backend/src/ai/rag/advisor.py` | Retain historical-sales scope and distinct pricing refusal; incorporate evidence relevance, recalled user passages and explicit non-AI mode. |
| `backend/src/ai/routers/alerts.py` | Cache company alert computation; retain persistent-notification deduplication, current user's read state and preferences. |
| `backend/src/ai/routers/dashboard.py` | Keep usage/entitlement imports and endpoint checks alongside cached reads. |
| `backend/src/ai/routers/forecasting.py` | Keep forecast entitlement enforcement alongside cached overview reads. |
| `backend/src/ai/routers/rag.py` | Combine JSON-body validation imports with file-upload imports; retain uploads, URL compatibility, persisted failures and safe settlement. |
| `backend/src/ai/sentiment/pipeline.py` | Retain atomic reservation/settlement; upgrade rating stand-ins without charging the same review again. |
| `backend/src/ai/tests/test_pipeline.py` | Keep invalid/incomplete horizon regressions and the quiet-fortnight interval regression. |
| `backend/src/ai/tests/test_rag_query_router_integration_db.py` | Retain unpriced-provider recovery/history checks and test evidence-only exhausted-budget behavior without provider invocation. |
| `frontend/src/assets/locales/en.json` | Preserve pricing-unavailable wording and add exhausted-allowance wording. |
| `frontend/src/assets/locales/ar.json` | Preserve both corresponding Arabic messages. |
| `frontend/src/features/knowledge-base/utils/references.js` | Map both pricing and exhausted-allowance evidence statuses. |
| `frontend/src/features/settings/components/SecuritySettings.jsx` | Retain session clearing/re-login after password change; show wrong-current-password feedback on the field. |

Other compatible upstream improvements remain: forecast interval/validation
changes, sentiment recovery, model-download diagnostics, shared Redis clients,
batched competitor reads, streamed sales queries, truthful invitation delivery,
campaign invalidation after failure, estimated-price wording, lazy Arabic,
network-aware prefetch, gzip and immutable built-asset caching. No worker entrypoint
or Python billing authority was replaced.

## Semantic reconciliation and safeguards

### RAG, provider costs and Credits

Textual merging alone left an evidence-only path dereferencing a missing
reservation. Settlement now handles the absence of an AI allowance reservation.
Only an exhausted **positive** configured RAG allowance can use that fallback;
missing/zero allowance and inactive access remain refusals. Non-AI mode disables
both answer generation and paid public research. Existing server-side provider
disable/cap refusals may show tenant evidence without invoking that provider.
Other financial/concurrency/accounting refusals remain refusals.

The optional JSON request body and legacy URL form coexist. The frontend uses
JSON while retaining failure-session headers, citations and restored history.
All-history sales facts, exclusion of fixed-window generated sales summaries,
document access checks, original question persistence and atomic answer/allowance
settlement are retained. Full stored history is not a promise that every turn
fits in the model prompt: recent turns and relevant user passages are selected.

Main's 8,000-token retry preference is bounded by the existing approved output
policy (4,000 in the installation fixture). The policy is read through the
restricted accounting identity; each attempt independently reserves and settles
as before. No policy value or rate is rewritten. A still-truncated completion
at the ceiling raises an error rather than becoming a supposedly complete answer.
Tests cover the 1,500 -> 3,000 -> 4,000 sequence, actual USD settlement for each
attempt and no outstanding reservation. No paid external AI request was made.

Approved Groq bootstrap, owner-configured schedules, catalog audit/history,
customer Credits and subscription prices remain separate. Existing Phase 3
marketing factual-grounding and market-observation provenance logic is retained.

### Pooling and RLS

A new native regression failed on both commit and rollback: reusing an existing
cursor saw empty tenant/user settings because main restored context only when
opening a new cursor. Context is now restored immediately after transaction
boundaries, including subclass webhook receipt context. Main's retained sockets,
batched settings and timezone cache remain. The deferred-context performance
optimization is deliberately not retained; no performance-equivalence claim is made.

Native checks use `ceopro_app`, setup, webhook and accounting credentials, including
same-cursor reuse and receipt scope. Existing cross-tenant, role separation,
payment evidence, trial/downgrade and Credit tests remain enabled. No FORCE RLS
or restricted-role attribute was weakened.

### Caching and reports

A focused regression reproduced an English cached response being returned for
an Arabic request. Every cache key now includes request language. Connection-based
cached reads additionally include the authenticated user; Command Center keys
include their connection principal. Authorization still runs before lookup.
Tenant-wide invalidation and shared Redis generations remain, including a native
test where a second Python process invalidates the first process's cached value.
Native HTTP checks cover translated sales rows and invalidation after a write.

Reports retain capability checks, idempotent usage reservations and failure
release. Incoming named cursors stream the complete ordered sales result while
their connection/transaction remains alive; cursor completion precedes commit
and connection close. Existing native export/content and failure regressions
remain in the backend selection.

## Migrations

| Migration | Review |
|---|---|
| `20261031000000_add_invoices_tenant_issue_date_index.sql` | Incoming tenant/date index; retained unchanged. |
| `20261031010000_add_refresh_sales_statistics.sql` | Incoming fixed-table statistics command; retained unchanged. |
| `20261116000000_harden_sales_statistics_function.sql` | New forward hardening: qualified `public` tables, `pg_catalog, pg_temp` search path, PUBLIC/billing-role execution revoked, only app execution granted. |

The similarly prefixed durable-notification and invoice-index migrations have
different full filenames. The runner tracks full filenames, sorts deterministically
and applies unrecorded older filenames on upgrade. No applied migration was renamed
or edited. Fresh installation contains 150 migrations; repeat application is a no-op.
The upgrade regression first installs the original 147 migrations, persists
synthetic financial/catalog state, then applies exactly the two incoming migrations
and the hardening migration. Row snapshots must remain equal after upgrade/replay.

The statistics function remains owned by the installation authority, never a
runtime role. It accepts no arguments, interpolates no SQL and only analyzes
three fixed qualified tables. It returns no tenant rows or financial records.
Temporary-table shadowing and runtime ALTER/ownership attempts are tested; FORCE
RLS remains enabled. Maintenance affects planner statistics for the shared tables,
not only one tenant's statistics. No migration was run against the active DB.

## Verification evidence

Private evidence is under this worktree's `.dev/`; none is staged as source.
The tests run against an uncommitted merge tree; metadata initially reports its
parent HEAD. The delivered commit contains the reconciled source, not a claim
that an earlier parent already contained these changes.

| Check | Result / evidence |
|---|---|
| Original branch/runtime baseline | Clean `66c18dd7`; API ready; private config/process-ledger hashes recorded. |
| Cache defect reproduction | FAIL before fix: `.dev/cache-language-before.log`. |
| Cursor reuse reproduction | FAIL before fix for commit and rollback: `tests/4e2a258ef004/backend.log`. |
| Fresh/repeat migration runs | PASS: 150 migrations, repeat no-op, restricted login, 120 FORCE RLS tables. |
| Initial broad backend run | 4,395 passed / 293 failed / 23 skipped; `tests/580e66993435`. Failures retained, not suppressed. |
| Corrected offline customer fixtures | PASS: 397 tests; `.dev/verified-fixtures-offline.log`. |
| Broad backend/billing rerun | 4,678 passed / 23 skipped / 12 fixture setup errors, zero test failures; `tests/cccb24eb98ce`. The setup errors used an incorrect verification column in two test fixtures. |
| Corrected native fixture recheck | PASS: all 12 cases, zero failures/errors/skips; `tests/7e6bbe290def`. Fixtures use the actual `email_verified_at` timestamp. |
| Combined backend/billing evidence | PASS: **4,690 distinct passing cases, 23 explicit skips, zero unresolved failures/errors**, recomputed from both JUnit files. This is not represented as one completely green broad invocation. |
| Frontend | PASS: 230 tests, zero skips/failures; ESLint and production build; `.dev/evidence/frontend/`. |
| Authenticated browser | PASS: `tests/4dfdb9a627c9`; 81 screens across EN desktop, AR mobile and EN dark mobile. |
| Assistant browser presentation | PASS: EN/AR evidence banner, references and administrator note. Explicit response fixtures, not real model acceptance. |
| Environment inventory | Regenerated from reconciled source; `--check` passes. |

Commands: `dev.ps1 setup`, `dev.ps1 setup --models`, frontend `npm run test`,
`npm run lint`, `npm run build`, `dev.ps1 test --suite browser-ci`, and:

```powershell
.\dev.ps1 test --suite backend --pytest-args --import-mode=importlib src tests/billing -q
.\dev.ps1 test --suite backend --pytest-args --import-mode=importlib src/ai/tests/test_main_integration_db.py src/ai/tests/test_import_drafts_http_integration_db.py -q
```

Importlib mode avoids pre-existing test-package name collisions without removing
tests. SMTP in the supported runner exposed older fixtures that minted unverified
tokens for tests intended to exercise authorized operations. One identical failure
was reproduced on archived unmodified `66c18dd7`; those fixtures now explicitly
represent verified synthetic principals. Native fixture users are also marked
verified. Negative unverified-email tests remain, including a new upload denial.
No production authentication toggle or entitlement check was disabled.

Some marketing fixtures returned campaign JSON for the additional independent
factual-review call. Explicit offline responses now represent both contracts,
without bypassing the actual grounding validator. Allowance expectations include
both calls. Billing UI render fixtures preload lazy Arabic and use the public
translation API; the JSON chat fixture reads the request body for failure recovery.

The 23 skips remain visible: nine real embedding cases, seven real sentiment
cases, one real reranking case, three OCR/font-dependent cases, one optional
background-removal case, one live-provider smoke and one Stripe E2E case.
Missing weights, optional software and external authorization were not converted
into passes. The frontend build retains its dynamic-import warning.

Finalization recomputed results by full test identity, with the native rerun
replacing only its 12 prior setup errors. It checked source modification times
against the applicable evidence; no backend source was newer than its test run.
The 12 conflict resolutions remain staged/reviewable, with no unmerged index
entries. The report is the only file changed during finalization.

## Protected environment preservation

The original checkout remains clean on `integration/keel-full-migration` at
`66c18dd77cf2b2410c329a0d390e2da7c87959ab`. Local main remains
`041f9f24a6a32d8d03d934a3f89b6b3734eecadb`, and cached origin/main remains
`2c3224e32be56dab02c35edc5d610c997089a410`.

Private configuration, integrations, process-ledger and mode-file hashes are
compared with the original baseline. API, frontend and all eight original worker
process identities are checked without restarting them; the original API readiness
and frontend HTTP checks remain successful. Test databases use the separate review
cluster and disposable names. No original database migration, direct data query,
customer/demo mutation, billing operation or credential change was performed.
This is preservation of the existing environment by this work, not a claim that
a running database is byte-for-byte static or that historical demo discrepancies
were repaired. Evidence: `.dev/evidence/original-preservation-final.json` and
the finalization verification record in the review worktree.

## Remaining boundaries and integration decision

**No critical reconciliation blocker or unresolved selected test failure remains.**
The candidate is suitable for a separately authorized promotion, subject to normal
review of the commit and the explicit coverage limits below. It is not a claim
of complete production or live-provider acceptance.
No paid AI, real Stripe payment, merchant-store acceptance, production deployment
or newly downloaded model-weight acceptance is claimed. Upstream performance
measurements are historical evidence, not benchmarks of this combined candidate.

Before any later integration, review the merge commit/diff and this evidence,
confirm the original branch still has the recorded HEAD, and separately authorize
the integration. Since the original HEAD is a parent, an unchanged original branch
can later advance to the reviewed merge commit without rebasing its 174 commits.
No such advancement is performed here.
