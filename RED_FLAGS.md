# CEOPRO AI — Red Flags

A severity-ranked, scannable summary of the serious issues found (and, where marked, fixed) during the
`Final_schema.sql` schema-fork rework and the pre-merge deep edge-case testing pass. This file exists
to answer one question fast — **"what's actually dangerous here, and is it handled?"** — without
digging through `PENDING_ACTIONS.md`'s full history or `AI_PROGRESS.md`'s day-by-day log. Every entry
below links back to those for full detail (root cause reasoning, exact repro steps, code).

**Convention:** like `PENDING_ACTIONS.md`, entries get their status updated in place, not deleted, so
this stays a real record. Newest-first within each severity tier.

---

## 🔴 Critical (security or data-integrity, would have broken in production)

### RLS tenant isolation crashed on first real use — infinite recursion in `get_current_tenant()`
**Found:** 2026-08-27, deep edge-case testing pass. **Status:** ✅ Fixed, regression-tested.

`get_current_tenant()` — the function every Row-Level Security policy in `Final_schema.sql` calls to
scope a query to one tenant — queries `tenant_users` internally to confirm the caller is still an
active member of the claimed tenant. `tenant_users` is itself RLS-protected by a policy that calls
`get_current_tenant()` again. The function was `SECURITY INVOKER` (Postgres's default), so under any
non-superuser role — the actual, intended runtime identity — evaluating it recurses forever:
`psycopg2.errors.StatementTooComplex: stack depth limit exceeded`, on any RLS-scoped query, the instant
real tenant context was set.

**Why it was invisible all session:** every verification up to this point connected as `ceopro_admin`
(a superuser), which bypasses RLS — and therefore every policy call — entirely. The bug only exists on
the path nothing had exercised yet.

**Impact if it had shipped:** the moment anything actually connected as the restricted `ceopro_app`
role with correct session context (the intended, documented deployment shape), every tenant-scoped
query would 500. Not silent under-isolation — a hard crash on the primary code path.

**Fix:** [`migrations/20260827060000_fix_get_current_tenant_recursion.sql`](src/infrastructure/database/migrations/20260827060000_fix_get_current_tenant_recursion.sql)
marks the function `SECURITY DEFINER` (+ locked `search_path`) so its internal lookup runs as the
function's owner (a superuser) and bypasses RLS instead of re-entering it — the standard, documented
Postgres pattern for exactly this situation. Verified with a full two-tenant scenario connected as the
real `ceopro_app` role: correct scoping, fails closed with no context set, a revoked membership loses
access, a user can't claim a tenant they don't belong to. 11 permanent regression tests:
[`src/ai/tests/test_rls_integration_db.py`](src/ai/tests/test_rls_integration_db.py).

Detail: `PENDING_ACTIONS.md` #32, `AI_PROGRESS.md`'s 2026-08-27 "Deep edge-case pass" entry.

---

### `ceopro_admin` (the only role anything connects as today) is a superuser and unconditionally bypasses RLS
**Found:** earlier session, re-confirmed against `Final_schema.sql` 2026-08-27. **Status:** 🔴 Still open — needs an owner decision, not an AI/ML-track fix.

Regardless of how correct the RLS policies are (and, as of the fix above, they now are), **RLS provides
zero actual tenant isolation in the deployed system today**: `docker-compose.yml`'s only DB-connecting
service definition (`migrate`) — and every AI/ML codepath that reads `DATABASE_URL` — authenticates as
`ceopro_admin`, and the official Postgres bootstrap makes that role a genuine superuser
(`rolsuper=t`, `rolbypassrls=t`). Superusers bypass RLS unconditionally; `FORCE ROW LEVEL SECURITY`
has no effect on them. A non-superuser `ceopro_app` role now exists with a synced password
(`APP_DB_PASSWORD`) specifically for this, but **nothing in the repo actually connects as it** — there
is no `ai`/`backend` service in `docker-compose.yml` at all yet (see High severity, below), and no code
anywhere calls `SET app.current_tenant_id`/`SET app.current_user_id` per request.

**What an actual fix needs, all three together:** (1) whatever service ends up handling real requests
must connect as `ceopro_app`, not `ceopro_admin`; (2) that same codepath must set
`app.current_tenant_id`/`app.current_user_id` per connection/request, derived from real
authentication — nothing does this today; (3) `ceopro_admin`/superuser access should be reserved for
migrations and bootstrap only, never a live request path.

Detail: `PENDING_ACTIONS.md` #2, #25.

---

## 🟠 High (would break the system or silently corrupt data, now fixed)

### `evidence_records` structurally couldn't be written to by 4 of 5 AI modules
**Found:** schema-fork rework, 2026-08-27. **Status:** ✅ Fixed (two passes — see below).

`Final_schema.sql`'s `evidence_records` was forecast-only: `forecast_id UUID NOT NULL`, and only
`metric_name`/`metric_value_json`/`contribution_weight` as data columns. `pricing/`, `sentiment/`,
`mpi/`, and `extraction/` all need to write evidence and none of them produce a `forecast_id` —
structurally impossible to satisfy, breaking spec §22's "one consistent evidence architecture, shared
by all AI outputs" requirement outright.

**Fixed** by extending the table rather than forking a second one (`forecast_id` made nullable,
general-purpose columns — `category`/`source_module`/`explanation_text`/etc. — added back, a
`chk_evidence_shape` constraint requires one or the other, not both empty).

**Caught by the live-DB run, not by review:** the first pass of this fix only dropped `NOT NULL` on
`forecast_id` — `metric_name`/`metric_value_json`/`contribution_weight` were still `NOT NULL` from the
original forecast-only definition, so every non-forecasting evidence insert still failed with
`NotNullViolation` until an actual insert was attempted against a real table. This is the clearest
single proof point in this whole effort that manual review + `sqlparse` syntax-checking is not a
substitute for actually running the SQL.

Detail: `PENDING_ACTIONS.md` #28.

### `extraction/data_access.py` queried a table that didn't exist
**Found:** schema-fork rework review, 2026-08-27. **Status:** ✅ Fixed.

`load_known_competitor_names()` queried `FROM competitors` — a flat table the old schema had, but
`Final_schema.sql` (landed in the same commit burst) replaced with
`global_competitors`/`tenant_competitors`/`competitor_product_mappings`. Would have failed on every
single call. Rewritten to join the new tables; also fixed to handle `product_name` now being JSONB.

Detail: `PENDING_ACTIONS.md` #29(a).

### `docker-compose.yml`'s `migrate` service ran a script that didn't exist anywhere in the repo
**Found:** schema-fork rework review, 2026-08-27. **Status:** ✅ Fixed.

`python scripts/apply_migrations.py` — referenced, never written. There was also no working migration
runner of any kind before this (the earlier-tracked gap, `PENDING_ACTIONS.md` #22). Built a real one:
applies `Final_schema.sql` once, then `migrations/*.sql` in filename order, tracked in
`schema_migrations`, idempotent (verified via two clean back-to-back runs on an empty database).

Detail: `PENDING_ACTIONS.md` #29(c).

### `rag_document_chunks` had no `embedding` column, and no `vector` extension was ever created
**Found:** while building the migration runner, 2026-08-27. **Status:** ✅ Fixed.

Semantic (FAISS) retrieval writes embeddings there; the column didn't exist and `Final_schema.sql`
never ran `CREATE EXTENSION vector`. Added via migration, sized at 384 dimensions — confirmed
empirically against the actual production embedding model
(`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`), not assumed.

Detail: `PENDING_ACTIONS.md` #29(c).

### A retired RLS migration would have hard-failed the entire migration sequence
**Found:** schema-fork rework review, 2026-08-27. **Status:** ✅ Fixed (file deleted).

`migrations/20260807230419_add_row_level_security.sql` referenced `transactions` and `competitors` —
neither exists in `Final_schema.sql`. Applying it after the base schema would error out and stop every
migration after it from ever running. Deleted; `Final_schema.sql`'s own RLS (now fixed, see Critical
above) supersedes it.

Detail: `PENDING_ACTIONS.md` #29(c).

### `products.product_name` becoming JSONB broke every hardcoded-string test fixture that touched it
**Found:** across the whole rework, culminating in the forecasting/ fixtures on 2026-08-27. **Status:** ✅ Fixed everywhere except `forecasting/`'s own module code (see Open, below — the fixtures are fixed, the module's data source is a separate, larger gap).

`Final_schema.sql` made `products.product_name` JSONB (multilingual) instead of plain text. Every test
fixture across `pricing/`, `sentiment/`, `mpi/`, `extraction/`, and `forecasting/` that inserted a bare
string literal for it failed with `psycopg2.errors.InvalidTextRepresentation: invalid input syntax for
type json`. Fixed everywhere by switching to `json.dumps({"en": name})`.

Detail: `AI_PROGRESS.md`'s three 2026-08-27 entries.

### `template_detection.py` never matched snake_case headers — silently degraded extraction quality
**Found:** 2026-08-28, post-merge QA pass. **Status:** ✅ Fixed, regression-tested.

`_normalize_header()` only collapsed whitespace and lowercased — it never folded underscores to
spaces. A file with headers like `product_name`/`unit_price` (`Final_schema.sql`'s own
column-naming convention, and the natural shape of anything exported from a database or API rather
than typed by hand in a spreadsheet) never matched `HEADER_SYNONYMS`, silently falling through to
`FALLBACK`/NER extraction instead of the precise `STRICT` typed mapping it should have gotten — same
fields, just a different header spelling. Not a crash, not an error — a silent quality regression
that would have been very easy to miss without deliberately testing this exact module, which had zero
test coverage before this pass.

Fixed by folding underscores to spaces in `_normalize_header()` itself, applied identically to both
the incoming headers and the synonym table (`build_header_mapping()` normalizes both sides through
the same function) — verified this doesn't collide with the synonym table's existing
underscore-containing entries (`total_ttc`, `prix_unitaire`). 6 new tests in
`test_extraction_template_detection.py`.

Detail: `PENDING_ACTIONS.md` #37.

### `row_parsing.py`'s typed percent-cell parser never stripped `%` — same class of silent degradation
**Found:** 2026-08-28, post-merge QA pass, same session as the bug above. **Status:** ✅ Fixed, regression-tested.

`_parse_typed_cell()`'s `"percent"` branch called `normalize_number_string()` directly on the raw
cell text. A `discount_pct` cell written the natural way (`"10%"`, not `"10"` — how Excel/Sheets
write a percent-formatted cell, and how a human typing a discount naturally does too) has
`float("10%")` fail inside `normalize_number_string()`, returning `None` — the cell then silently
fell through to `unmapped_columns` + fallback regex extraction, despite the column already being
correctly identified as `discount_pct` by `template_detection.py`. The regex-based fallback tier
(`extract_percent()` in `regex_patterns.py`) already avoided this — its capture group excludes the
`%` — so this was specifically a `STRICT`-mode/regex-fallback inconsistency, not a `numerals.py` bug.

Fixed by stripping a trailing `%` before normalizing, mirroring what the regex path already does. 8
new tests in `test_extraction_row_parsing.py`.

Detail: `PENDING_ACTIONS.md` #37.

### `torch` imported directly but never declared as a dependency
**Found:** 2026-08-28, post-merge QA pass (static import scan across all of `src/ai/` against
`requirements.txt`). **Status:** ✅ Fixed.

`sentiment/model.py` calls `torch.no_grad()`/`torch.softmax()` directly, but `torch` was never in
`src/ai/requirements.txt` — only present because `transformers`/`sentence-transformers` pull it in
transitively. `requirements.txt` already documents exactly this reasoning for `transformers` itself
("pinned here explicitly since `sentiment/model.py` imports it directly") but hadn't been applied to
`torch`, which is imported the same way in the same file. Fixed — pinned explicitly, CPU range
matching the confirmed deployment target.

Detail: `PENDING_ACTIONS.md` #37.

### A ~700-line subsystem (the Universal Import Engine) is still largely untested
**Found:** 2026-08-28, post-merge QA pass. **Status:** ✅ Largely resolved 2026-08-28 (same day, follow-up
mission) — every file this entry named now has real test coverage; see the two entries below for what
that coverage found.

`ingestion_pipeline.py`, all 5 `extraction/adapters/` files (csv/xlsx/pdf/db/api), `row_parsing.py`,
`template_detection.py`, `locale_config.py`, and `minio_persistence.py` — main's independently-grown
"Universal Import Engine" (spec §12) — had **zero** automated test coverage anywhere in the repo
before this pass, confirmed by grepping every test file for each module's name. This pass added real
coverage for `template_detection.py`, `row_parsing.py`, and `locale_config.py` — and found genuine
bugs in the first two, a strong signal the rest of this subsystem hadn't actually been verified
either, just assumed fine because nothing crashed in normal use. That signal held: the same-day
follow-up pass below found the subsystem's adapters had **no caller anywhere in the repo at all**, and
a real transaction-poisoning bug in `ingestion_pipeline.py`'s DB writes. `minio_persistence.py`'s
document-building logic remains checked only by manual smoke test, not a permanent regression test —
the one piece of this subsystem still without real coverage.

**Not a red flag about correctness specifically** — everything checked so far either works or was
fixed — **it's a red flag about confidence**: this subsystem's actual reliability is currently
unknown, not confirmed-good, for most of its surface area.

Detail: `PENDING_ACTIONS.md` #37.

### "Detect file type" (spec §12, explicit) had no implementation — 5 adapters, zero callers
**Found:** 2026-08-28, building out Document Ingestion & Validation. **Status:** ✅ Fixed, regression-tested.

None of `extraction/adapters/`'s 5 files (csv/xlsx/pdf/db/api) had a single caller anywhere in the
repo, confirmed by grepping the whole codebase for each adapter's function names. Every adapter was
individually correct — each had just gained real test coverage confirming that — but completely
unreachable: nothing decided which adapter a real uploaded file should go through, so an actual
upload had no path into the pipeline at all despite the adapters existing and working. Not a subtle
bug — a required pipeline stage (spec §12: *"Receive a file. Detect file type."*) simply had zero
implementation.

**Fix:** `extraction/file_dispatch.py` (new) — detects the file extension and dispatches to the 3
file-based adapters (csv/xlsx/pdf; db/api are invoked directly by a caller holding a live
connection/fetch callback, not file-type dispatched). 16 new tests across the dispatcher and the
adapters it wires up.

Detail: `PENDING_ACTIONS.md` #38.

### A single bad row could silently break DB writes for the rest of an entire file
**Found:** 2026-08-28, live-DB testing while building the "Validate values" step. **Status:** ✅ Fixed, regression-tested.

A row whose value Postgres genuinely can't store — reproduced directly with a NUL byte in a cell,
`psycopg2.errors.UntranslatableCharacter`, a hard Postgres/JSONB limitation with no application-level
fix that preserves the raw value — left `ingestion_pipeline.py`'s database connection permanently
transaction-aborted. Every later statement on that same connection then failed too
(`psycopg2.errors.InFailedSqlTransaction`): every subsequent row's writes, and the final job-count
update, all failed with a confusing, unrelated-looking error — for any file where the bad row wasn't
the very last one. This directly contradicted the module's own documented guarantee, in its own
docstring: *"one bad row must not sink the whole file."*

**Fix:** every database write in `ingestion_pipeline.py` now runs inside a `SAVEPOINT`, rolled back
to (not the whole transaction) on failure — the standard PostgreSQL pattern for exactly this
situation. Verified with a live-DB test: a NUL-byte row followed by a good row — the good row still
processes correctly, the transaction commits cleanly, job counts land correctly for both rows.

Detail: `PENDING_ACTIONS.md` #39.

---

## 🟡 Medium (a clean `git merge` silently dropped real content)

### Merging `main` into #16 lost a module docstring — with zero conflict markers
**Found:** 2026-08-27, while rebasing #16/#17 against a moving `main` (PR triage pass). **Status:** ✅ Fixed.

`git merge origin/main` reported one real conflict in `extraction/data_access.py` (resolved correctly).
A *separate*, non-conflicting hunk in the same file — the module docstring, a few lines above — was
auto-merged by silently taking `main`'s side, which had dropped that docstring in one of its own
direct-to-`main` edits. Git's merge algorithm considered this clean (no overlapping changed lines), but
real content was still lost. The only way this was caught: diffing the branch's pre-merge and
post-merge state of the file directly, rather than trusting "the merge succeeded with no conflicts" to
mean nothing changed unexpectedly.

**Why this matters beyond the one file**: "no conflict markers" is not the same guarantee as "nothing
was silently altered." Any merge that resolves a real conflict in a file also auto-merges every other
hunk in that file using the same three-way logic, and none of those get a human's eyes by default.

Detail: `PENDING_ACTIONS.md` #36 (renumbered from #34 — PR #14 independently landed content at #34/#35 first).

---

## 🟡 Medium (test-only bugs — product code was fine, the tests lied about coverage)

These didn't affect production behavior, but they meant "tests pass" wasn't actually verifying what it
claimed to until the live-DB run caught them.

- **`test_extractor.py`** was never updated when `extract_entities()`'s signature changed (still called
  it with the old `known_product_names`/`known_competitor_names` kwargs) — silently testing nothing
  real. Rewritten with mocks matching the actual signature.
- **`extract_discount()`** dropped the `%` suffix from `normalized_value` — a real, if minor, pre-existing
  bug, unrelated to the schema fork, caught while verifying the extraction rework. Fixed.
- **`test_sentiment_integration_db.py`/`test_mpi_integration_db.py`**'s review-seeding helpers never set
  `reviews.source_platform` (`NOT NULL`, unrelated to this rework — always was). Every seeded review
  insert would fail. Fixed.
- **`test_pricing_integration_db.py`**'s competitor-price fixture inserted a fresh `global_competitors`
  row on every call instead of reusing one for the same `(tenant_id, competitor_name)` — any test
  seeding more than one price for the same competitor hit `uq_competitor_private` and failed. Fixed to
  look up-or-insert, matching how a real repeat observation would actually behave.

Detail: `PENDING_ACTIONS.md` #29(other), #30.

---

## 🟢 Checked and confirmed safe (deep edge-case pass, 2026-08-27 — no fix needed, now has permanent regression coverage)

Verified directly against a live database rather than assumed correct by inspection:

- **Cross-tenant leakage, worst realistic case**: two tenants independently tracking the *same* shared
  `GLOBAL`-visibility competitor, each with their own price observations — `pricing/`'s join chain
  (`competitor_prices` → `competitor_product_mappings` → `tenant_competitors` → `global_competitors`)
  stays correctly tenant-scoped. New permanent test:
  `test_load_competitor_prices_stays_tenant_scoped_for_a_shared_global_competitor`.
- **`sentiment/`'s and `mpi/`'s data-access queries** — reviewed directly for the same class of leak;
  both already correctly `tenant_id`-scoped on every join.
- **`chk_evidence_shape`**, **`chk_review_subject_consistency`**, and **`uq_competitor_private`**
  (correctly *allows* the same competitor name across different tenants, only same-tenant duplicates
  collide) — all behave exactly as designed.
- **MPI's volume-floor comparison guard**, exactly at the floor (not just above/below) — comparable, as
  intended (`<` not `<=`).
- **`apply_margin_guardrail()` at `cost=0`** — no-ops correctly, never produces a nonsensical zero floor.
- **`_representative_name()`'s JSONB fallback** for a product name missing the `"en"` key — falls back
  to any populated language correctly.
- **`extraction/catalog_cache.py` against a real Redis container** (every prior test used a `_FakeRedis`
  stand-in) — full cache-aside cycle (TTL, cache hit avoiding a re-query, `invalidate()`) confirmed
  correct, including Arabic-script names round-tripping through JSON.

Detail: `PENDING_ACTIONS.md` #33, `AI_PROGRESS.md`'s 2026-08-27 "Deep edge-case pass" entry.

---

## ⚪ Open — structural gap, needs an owner decision (not an AI/ML-track fix)

### `forecasting/` cannot run against `Final_schema.sql` at all — no `transactions` table exists
**Found:** deep edge-case pass, 2026-08-27 (forecasting was explicitly out of scope for the rework
itself, so this was only discovered when its tests were actually run). **Status:** 🔴 Open, needs a decision.

`Final_schema.sql` has no `transactions` table in any of its 26 `CREATE TABLE` statements.
`forecasting/data_access.py::load_daily_demand()` reads from it directly. This isn't a mechanical
rename fix — the closest structural analog, `invoices`/`invoice_items`, has no per-line
`transaction_date` (only invoice-level `issue_date`) and no POS/online `sale_source` distinction, which
is a real data-model difference `forecasting/` currently depends on.

**Needs a decision**: extend `Final_schema.sql` with a `transactions` table (matching this rework's
"extend, don't reduce" pattern used everywhere else), or deliberately rework `forecasting/` onto
`invoices`/`invoice_items` instead. Not decided unilaterally here since `forecasting/` was explicitly
excluded from this rework by prior instruction, and picking the data source is a real architecture
call, not a bug fix.

**Addendum, found 2026-08-27 while triaging open PRs**: `Final_schema.sql` also has no `model_versions`
table (`forecasting/evidence.py` writes to it) — a second, independent structural gap, compounding
rather than duplicating the `transactions` one above. Whatever gets decided for `transactions` should
cover `model_versions` too.

Detail: `PENDING_ACTIONS.md` #31.

---

## How to update this file

- New finding: add a row to the severity tier that fits, newest-first within the tier. Link to the
  relevant `PENDING_ACTIONS.md` item number and/or `AI_PROGRESS.md` entry for full detail — don't
  duplicate the full reasoning here, this file is the scannable summary.
- Resolving something: update its **Status** line in place (`🔴 Open` → `✅ Fixed ...`), don't delete
  the entry — the record of what was wrong matters even after it's fixed.
- If severity turns out to have been over- or under-stated, say so in the entry rather than silently
  moving it — same reasoning as `PENDING_ACTIONS.md`'s own precedent.
