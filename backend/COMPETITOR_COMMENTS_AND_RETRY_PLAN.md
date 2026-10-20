# Competitor comments "0%" and invisible Retry reasons — root causes and fix plan

Status: built 2026-10-19 (sections 4-6 are the as-built record). Extends
`COMPETITOR_DATA_COMPLETENESS_PLAN.md` (the ledger, facets and Retry endpoints this relies on).
All API changes are **additive** (new optional fields / query params); no existing field changes meaning
except the REVIEWS/COMMENTS row split in R1, which is called out below.

## 1. Reported problems

1. In Competitors, the comments part always reads **0%** (the completeness pill/meter never moves, and the
   comments panel is always empty).
2. **Retry** says "nothing could be collected, reasons are shown below" but the owner cannot see the reason.

## 2. Root causes (verified in code)

| # | Cause | Evidence | Effect |
|---|-------|----------|--------|
| R1 | **COMMENTS has no "data wins" rule.** REVIEWS and NEWS report `SUCCEEDED` when rows exist, whatever the ledger says; COMMENTS reads the ledger only. Worse, REVIEWS counts *every* competitor review row, so YouTube comments are counted as "Google reviews". | `load_data_completeness` (`review_counts` has no platform filter; no COMMENTS branch) | Comments that exist still show "Blocked / 0%"; Google reviews show "collected" when only YouTube comments exist. |
| R2 | **COMMENTS is YouTube-only and setup-gated.** It needs `YOUTUBE_API_KEY` *and* `EXTERNAL_COMMENTS_APPROVAL_REFERENCE`; it is deliberately outside `ROUTINE_FACETS` (100 quota units/search), so nothing but a manual per-competitor Retry ever runs it. | `_comments_outcome`; `ROUTINE_FACETS` | Until an operator sets two env vars the facet is permanently `BLOCKED`, i.e. 0% — and the owner is shown a Retry that cannot help. |
| R3 | **The reason is collected but not shown.** `reason_detail` (the specific sentence, e.g. "YOUTUBE_API_KEY is not set") is only in a `title=` tooltip — invisible on touch and to keyboards. The compact list row (`CompetitorDataChips`) shows no reason at all. The Retry response carries a per-facet reason for every facet; the UI keeps only the one-word outcome and throws the rest away. | `DataCompleteness.jsx`, `useRetryNotice` | "The reasons are shown below" points at nothing. |
| R4 | **No distinction between "retry will help" and "someone else must act".** `can_retry` is true for operator-blocked facets, so Retry is offered where it can never succeed. | `_facet(... can_retry=...)` | Owners press Retry repeatedly; no one is told it is a setup matter for the administrator. |
| R5 | **The empty-comments hint is stale.** It promises "Retry above collects Google reviews" and "social comments need a connected provider", neither of which describes the COMMENTS facet. | `competitorData.comments.emptyHint` | Misleading; and no reason is shown where the user is looking. |
| R6 | **Comments are a wall of text, not a decision aid.** No sentiment filter, no per-sentiment counts, nothing marks which comments matter (many people agreeing). | `CompetitorComments.jsx`, `competitor_comments.py` | Not "ready to act on". |

## 3. Options considered

- *Fake a non-zero score / hide COMMENTS when blocked* — rejected: hides the truth and the owner's only lever.
- *Add COMMENTS to the routine sweep* — rejected: spends YouTube quota for every competitor on every sweep (existing test pins this).
- *Chosen:* make the facet honest (data wins), make every reason visible with **who can fix it**, and turn the comment list into a prioritised, filterable action list.

## 4. Backend design (as built)

**4.1 Platform split (R1).** `load_data_completeness` counts REVIEWS from `source_platform = 'Google Places'` and
COMMENTS from every other platform (YouTube today, social tomorrow). Either facet shows `SUCCEEDED` with its row
count when rows exist (data wins over a stale ledger), otherwise the ledger row, otherwise `PENDING`.

**4.2 `next_step` on every facet and every Retry outcome (R4).** New additive field, one of:

| value | meaning | UI |
|-------|---------|----|
| `none` | collected, or nothing can be done (no website, robots, not applicable) | no button |
| `retry` | retrying may find something (nothing found yet, not attempted) | Retry |
| `wait` | provider/site hiccup or quota; the sweep retries automatically | "retries automatically" |
| `owner` | the owner can fix it (e.g. review the site's terms) | existing action button |
| `admin` | service setup: a key/approval is missing or rejected | "Ask your administrator", Retry hidden |

Derived in one place (`next_step_for`) from `status` + `reason_code`; unknown codes default to `retry`.

**4.3 Comments as a decision aid (R6).** `GET /competitors/{id}/reviews` gains:
- optional `sentiment=positive|negative|neutral` filter (422 on anything else);
- `summary.sentiment` = `{positive, negative, neutral, not_analysed}` over all visible comments;
- per comment `signal`: `opportunity` (negative, and ≥ `SIGNAL_MIN_AGREEING` people agree — customers are unhappy
  with the competitor: a chance to stand out) or `threat` (positive with the same backing — what you compete against).
  Deterministic from stored sentiment and likes; nothing generated.

## 5. Frontend design (as built)

- `DataCompleteness`: every facet row shows the reason **and its detail as visible text**, plus a next-step line
  (admin / wait / owner). Retry is per facet where `next_step = retry`; it is hidden for `admin`/`none`.
- After a Retry, the notice lists **each facet's outcome and reason** (from the response) instead of "see below".
- `CompetitorDataChips` (list row): a "Why?" disclosure lists the missing facets with reasons and next step.
- `CompetitorComments`: when empty, shows the live COMMENTS reason (via `data-status`) with the right next step and a
  COMMENTS-only Retry; when present, a sentiment filter with counts and `opportunity` / `threat` markers.
- Strings: en + ar; stale `emptyHint` replaced.

## 6. Contract and compatibility check

| Surface | Change | Compatible |
|---------|--------|------------|
| `GET /competitors/{id}/data-status`, `GET /competitor-data/overview` | facets gain `next_step` | additive |
| `POST /competitors/{id}/enrich` | each result gains `next_step` (not on `THROTTLED`) | additive |
| `GET /competitors/{id}/reviews` | `sentiment` query param; `summary.sentiment`; per-comment `signal` | additive |
| REVIEWS facet count | now Google-Places rows only (was all competitor reviews) | **behaviour fix** — YouTube comments no longer inflate it |
| `ROUTINE_FACETS`, quota behaviour | unchanged | yes |
| Migrations | none | yes |

## 7. Tests

Backend unit: `next_step_for` table; every Retry result carries `next_step`; `/reviews` rejects a bad `sentiment`
and forwards a good one; `signal` rule; sentiment counts. Frontend: `competitorData.test.mjs` for the retry-outcome
reasons helper and `nextStepKey`. DB-backed completeness tests cover the platform split where a database is available.

## 8. Operator note (not code)

The COMMENTS facet stays `BLOCKED` until the service has `YOUTUBE_API_KEY` and
`EXTERNAL_COMMENTS_APPROVAL_REFERENCE` (see `KEYS_AND_ACCOUNTS_NEEDED.md`). The UI now says so plainly and routes it
to the administrator instead of offering a Retry that cannot work.

## 9. Follow-up (2026-10-19, after review)

| Gap | Fix |
|-----|-----|
| Plain Retry ran facets that cannot succeed (e.g. a YouTube search with no key) | Retry runs only facets whose `next_step` is `retry`; the panel Retry hides when none qualify |
| Score held down by service setup, unexplained | `needs_setup` (additive) lists those facets; the panel says Retry will not raise the score |
| No link to the original comment | Migration `20261025000000_add_review_source_url.sql` (nullable, http(s) only); stored from the collector; `url` per comment; "Open original" link |
| Replies had no opportunity/strength marker | Shown on replies too (counts remain top-level comments) |
| Comments never analysed after a missed event | A COMMENTS retry re-requests sentiment analysis when any stored comment has none |
| No render checks, DB tests unrun | `frontend/tests/competitorRender.test.mjs` renders the real screens; DB tests run against a throwaway Postgres with all migrations applied (17 + related pass) |

Still open: a live YouTube run once keys exist (parsing is tolerant but unverified against the real API).

## 10. Phase 2 - keeping comments alive, clean and actionable (2026-10-19)

Verified in code before planning: YouTube comments are stored with `retention_days = 30` and `enforce_comment_retention()`
deletes them; COMMENTS is outside `ROUTINE_FACETS` (100 YouTube quota units a search), so nothing re-collects it. A
competitor with comments today is empty again in a month. Alerts are derived live from data (`ai/alerts.py`, nothing
stored), the worker sweep is hourly (`enrichment_worker.run_sweep`), queue modes are `due | force | prices`.

| # | Problem | Design | Contract impact |
|---|---------|--------|-----------------|
| P1 | Comments vanish after 30 days, never refreshed | New queue mode `comments`. A daily sweep step enqueues it for tenants that have a competitor whose COMMENTS succeeded more than `COMMENTS_REFRESH_DAYS` (7) ago (SECURITY DEFINER lookup function, same pattern as `list_tenants_with_due_enrichment`). The job refreshes the oldest first, each search reserving from a global **daily search budget** (Redis counter, `YOUTUBE_DAILY_SEARCH_BUDGET`, default 40 searches = 4,000 of the free 10,000 units). Budget spent = stop, resume tomorrow. | none; new queue mode, new DB function |
| P2 | Noise: "first!", emoji, duplicates, comments about the video not the business | In the collector: drop comments with fewer than 12 letters (any script) or fewer than 3 words, drop duplicates (normalised text). On videos whose channel does not name the competitor, keep a comment only if it names the competitor or is a substantial opinion (>= 30 characters). Tunable constants, unit-tested. | none |
| P3 | Google reviews and YouTube comments mixed | `platform` filter on `GET /competitors/{id}/reviews`; UI shows platform chips when more than one source exists | additive query param |
| P4 | A list is not a decision | Deterministic **themes** (service, waiting time, price, quality, cleanliness, staff, delivery, availability; English + Arabic keyword lists): `summary.themes` = mentions, negative, positive, best example; `theme` filter. UI: "What customers talk about" chips sorted by complaints. No generated text. | additive field + query param |
| P5 | Advice with no follow-through | Per-comment **action status** (`noted` / `acted_on`), who and when. Migration adds nullable columns to `reviews`; `PUT /competitors/{id}/reviews/{review_id}/action`; `action_status` filter (`open` = not yet handled) | additive columns, new endpoint |
| P6 | Owner learns of a sentiment turn by chance | Derived alert `competitor_comments_negative`: >= 5 analysed comments in the last 14 days and >= 60% negative, one alert per competitor per week; links to the competitor | additive alert kind (en + ar wording) |
| P7 | Owner cannot judge freshness | `summary.last_collected_at` and a "Collected <date>" line | additive field |

Out of scope, with reasons: Instagram/Facebook comments (paid social provider, separate facet); an in-app key form
(policy in `docs/SECRETS.md`); an operator setup page (proposed separately, awaiting a decision).

Execution order: P2 -> P7 -> P3 -> P4 -> P5 -> P1 -> P6 (each ships with tests; DB-backed ones run against a
throwaway Postgres with all migrations applied).

### 10.1 As built

All seven items are built and tested (unit, plus DB-backed tests on a throwaway Postgres with every migration applied; the
browser check ran the real components against canned responses).

- Migrations: `20261025000000_add_review_source_url.sql`, `20261026000000_add_comment_action_status.sql`,
  `20261026010000_add_comments_refresh_function.sql`.
- New settings (all optional, defaults shown): `COMMENTS_REFRESH_DAYS=7`, `COMMENTS_REFRESH_MAX_PER_RUN=10`,
  `YOUTUBE_DAILY_SEARCH_BUDGET=40`, `COMMENT_MIN_LETTERS=12`, `COMMENT_MIN_WORDS=3`, `COMMENT_OFF_CHANNEL_MIN_CHARS=30`.
- The refresh runs inside the existing enrichment worker (daily step in its hourly loop); it needs the worker running
  (`./keel workers`) and, like any collection, `YOUTUBE_API_KEY` + `EXTERNAL_COMMENTS_APPROVAL_REFERENCE`.
- The daily budget counts only scheduled searches. An owner pressing Retry is not counted, so keep the budget at
  or under ~60% of the 10,000-unit quota (40 searches = 4,000 units) to leave room for them.
- Filtering in P2 is a heuristic. It drops "first!"-style noise and duplicates, and keeps an unnamed comment on someone
  else's video only when it is a real opinion. Expect to tune the three constants once real comments are seen.
- Not covered by an automated test: one full live YouTube run (no key in the build environment).

### 10.2 Audit before commit (2026-10-20)

Fixed: held-back (quarantined) comments counted toward the COMMENTS facet; the daily sweep queued jobs when YouTube was not
configured; the "collected" date stayed at the first insert after a refresh that stored nothing new. Documented: contract
changelog entry, rollback scripts for the three migrations (run and re-applied against Postgres), env settings in
`KEYS_AND_ACCOUNTS_NEEDED.md`, a comments section in `MARKET_DATA_PRIVACY_AND_RETENTION.md`.
Known and accepted: marking a comment has no role gate (any signed-in member); themes read the 500 most-agreed comments; replies
are not covered by the sentiment counts or filters; the comment filter thresholds are untuned (PENDING_ACTIONS #114).

### 10.3 Second pass (2026-10-20)

Found: `reviews` had no index for competitor reads (only product and parent), and the alerts bell now reads it on every poll;
fixed with a partial index (plan checked with EXPLAIN on 60,000 product rows). Frontend: a stored link is opened only if it is
http(s) (defence in depth over the database check), a failed "noted / acted on" save now says so, and the empty-filter
message no longer talks about sentiment only.

### 10.4 Release readiness (2026-10-20)

Verified: static checks (pyflakes) clean on every file touched; `docker compose config` parses with the new worker and API
settings passed through; all migrations apply from empty and the four new ones roll back and re-apply; the endpoints work
end to end as the restricted app role under row-level security with two real sign-ups (own data visible and markable,
another company gets 404) - `test_competitor_comments_api_integration_db.py`; the refresh stops for the day on a rejected
key or exhausted quota. Added to `.env.example`, `docker-compose.yml` (worker and API), `CURRENT_STATUS.md`.
Deliberately not done: the two earlier migrations (`...source_url`, `...action_status`) were not rewritten to use
`NOT VALID` / `VALIDATE`, because they were already pushed; on a very large `reviews` table apply them off-peak.
