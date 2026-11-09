# KEEL task register

The single shared record of who is doing what, what is verified, and what is next. Each session updates **its own
rows** and adds dated entries; nobody rewrites another session's rows. Evidence means a command that was actually run
(PASS / FAIL / BLOCKED), never an assumption.

## Ownership (assigned by the owner, 2026-11-09)

| Session | Owns | Production deploys |
|---|---|---|
| **Session 1** `session_01BF1evm6jhiwguiiZVnAHWT` | Overture mirror implementation, memory profiling and optimization, their deployment and deploy verification | **Deployment owner** (one deployer at a time) |
| **Session 2** `session_01BF1evkf4NUTzeuRAHoYgjH`, continued by `session_01BF1evjasZyYcJBjuxhn6uJ` | CI-equivalent isolated test environment, IDOR/security testing (incl. platform-admin gate hardening), real-data discovery testing, PR upkeep #103-#106, independent read-only production verification (email, uploads, images, billing pages) | Never deploys; verifies after each deploy |
| **Session 3** `session_01BF1evmDAewuKdMJtmdqLoe` | Credential rotation readiness: zero-downtime JWT rotation (`JWT_SECRET_PREVIOUS`), rotation runbook in `docs/SECURITY_CREDENTIAL_ROTATION.md` | Never deploys; hands Render steps to Session 1 |
| **Session 4** `session_01BF1evmdriDxRgtMrx7UH5w` | Production file storage (free, no payment method), end-to-end upload/download/image persistence | Never deploys; hands config to Session 1 |

## Production state

| When (UTC) | What | Evidence |
|---|---|---|
| 2026-11-09 04:02 | Session 1 deployed `99c213c` (prod branch `claude/vibrant-albattani-j2ksq5`) to Render `ceopro-ai-new`; previous live deploy `dep-dbnaubrl550s73emn1u0` (`700cb9d`) is the rollback target | Render deploy `dep-dbokbr8u01pc73fhtemg` = live |
| 2026-11-09 ~04:10 | Session 2 independent verification of that deploy | PASS: `/health` 200; `/health/ready` DB + Redis ok; `/health/processor` 200 `overture: unsafe` (404 before = old code); Chrome smoke on keelai.net 28/28 screens clean in EN 1440 px, AR 390 px, dark; backend `src/` on the exact `99c213c` tree, fresh PG17 + Redis: **5,016 passed, 0 failed** |
| 2026-11-09 04:22 | Session 2 successor read-only check | PASS: `/health/ready` DB + Redis ok; `/health/processor` `overture: unsafe` (same as verified deploy); Render live deploy still `dep-dbokbr8u01pc73fhtemg` (`99c213c`) |
| 2026-11-09 04:46 | Session 2 successor read-only check | Transient: `/health/ready` and `/health/processor` timed out twice (20 s) from the sandbox; within a minute `/health` 200 (4.4 s, then 0.3-0.5 s), `/health/ready` DB + Redis ok, `keelai.net` 200. Render events: no `server_failed`, restart or OOM since the 04:07 deploy (last OOM Nov 7, 512 Mi, before the bounded-memory fix). Reported to Session 1 |
| — | Frontend `keel-web` live = `375055c` (Nov 7); `main` is 5 migrations ahead of production (`20261123`–`20261129`, incl. billing) | Deploying `main` needs a backup-verified migration rollout; not started |

## Session 2 — completed (2026-11-08/09)

| Item | Branch / PR | Status | Evidence |
|---|---|---|---|
| Arabic store-connection screen was English; `{date}` placeholders rendered literally | `fix/arabic-store-connection` [#103](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/103) | CI green, **awaiting merge** | 2 new locale tests fail before / pass after; frontend 286/286 |
| Tests could reach hosted DB/Redis from ambient env; `backend/tests/` never ran in CI (a stale auth test + 3 email doubles broken by #102); `dev.sh --reuse-python` broken on Linux | `fix/test-safety-and-linux-dev` [#104](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/104) | CI green, **awaiting merge** | guard aborts on hosted `REDIS_URL`; `tests/` 546 passed; `src/` 5,185 passed |
| Discovery: name-vs-map-type relevance, Arabic café vocabulary, branch merging, adaptive radius / owner-radius suggestion (EN/AR UI) | `feat/discovery-adaptive-radius` [#105](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/105) | CI green, **awaiting merge** | real Overture data, `docs/REAL_DATA_DISCOVERY_TEST_2026-11-08.md`: off-domain listings 2→0, duplicate brand 1→0; Chrome EN/AR verified; `src/` 5,185 passed |
| Cross-tenant (IDOR) sweep, local API, 2 tenants | — | PASS | 151 cross-tenant requests over every id-bearing route (GET/POST/PUT/PATCH/DELETE): 0 succeeded |
| Platform admin routes as a Tenant Owner | — | PASS with low-severity note | all denied by handler + DB (42501); request bodies are validated before the platform check (schema disclosure only; production hides OpenAPI). A router-level gate needs 27 tests' mocks reworked - deferred |
| Production read-only smoke before the deploy | — | PASS | 28/28 in each of 3 variants |
| Older PRs reviewed | #93/#94/#95/#63 | needs owner | #93-#95 change trial/payment policy and plan catalogue (commercial decisions); parent #86 is merged, each conflicts with `main` in `pr-checks.yml` (+ catalogue for #95). #63 is stale (base `KEEL_Test`, CI red) |

## Security containment

| When (UTC) | What | Evidence |
|---|---|---|
| 2026-11-09 04:30 | Removed plaintext `APP_DB_PASSWORD`, `BREVO_API_KEY`, `DATABASE_URL`, `GROQ_API_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `REDIS_URL`, `RENDER_API_KEY` from agent environment `ceopro-ai` (Render access remains via the proxy-injected network secret) | `update_environment` result `updated: true`. Production unchanged. **Not a substitute for rotation** (values were readable): see Session 3. The `Default` environment still holds them; only the owner can remove them there |

## Session 3 — credential rotation (2026-11-09) — CLOSED (handover)

| Item | Where | Status | Evidence |
|---|---|---|---|
| Zero-downtime-capable `JWT_SECRET` rotation: sign with `JWT_SECRET` only; verify current, then optional `JWT_SECRET_PREVIOUS`; `exp` required; revocation/credential_version unchanged; rate limiter + config_check aware | **`main` `b3ae37b`** (squash of PR #107 head `6e4590d`, rebased on `d26b96c`) | **done, on main; not deployed** | see rows below |
| Review finding 1 (High): old-key token with future `auth_time` renewed into a lasting new-key session | `b3ae37b` | fixed | future `auth_time` (>60 s) refused for any key; `/auth/refresh` refuses previous-key tokens |
| Review finding 2 (High): `/auth/workspaces/switch` (same tenant) and `/auth/workspaces` re-issued old-key sessions | `b3ae37b` | fixed | `security.get_current_key_context` on refresh, workspace switch/create, `settings/security/change-password`; a route-walk test pins exactly these 4 and fails if a new token-issuing route skips it. Login, email verify, invitation accept (incl. platform invitations) issue tokens from password/code/invite token, not a session |
| Independent security re-review (Session 2) | PR #107 `6e4590d` | **PASS** | probes: old-key token on all 4 routes -> 401, no token, no DB connection; future `auth_time` refused; current-key refresh/switch 200; old-key 401 after removing PREVIOUS. Fresh PG17+Redis+MinIO: `src/` 5,283 passed, 0 failed |
| CI | PR #107 head `6e4590d` | **green** | PR Checks (backend, frontend, browser-smoke), Docker images (pr + push), Secret scan: all success. CI on `main` `b3ae37b` started by the push; not observed by this session |
| Local tests on the exact `main` tree `b3ae37b` | sandbox, fresh PG16 + Redis, local URLs only | PASS* | rotation/auth/security/settings suites 788 passed; full `src/` 5,244 passed, 78 skipped, 1 failed* = `test_connected_source_capacity_integration_db` asserts PG>=17 (sandbox has PG16; passes on PG17 in Session 2's run and CI) |
| Runbook | `docs/SECURITY_CREDENTIAL_ROTATION.md` on `main` | written; **not executed** | per secret: actor, continuity, verification, rollback. JWT step = owner decision (~10:55 UTC): **hard rotation, no overlap** (new `JWT_SECRET` only; never restore the old value). Also Neon owner, `ceopro_app` (+ other scoped role passwords), Upstash, Brevo, Groq (+ GitHub Actions secret), Render API key |
| PR #107 | GitHub | superseded by `b3ae37b` (closed) | — |

**Remaining (owner / Session 1), nothing blocked on code:**
1. Owner removes the plaintext variables from the `Default` agent environment (only the owner can).
2. Owner schedules the rotation with Session 1; Session 1 deploys only with the owner's separate approval; Session 2 verifies each step (runbook "Standard verification"). The hard JWT rotation needs no code; deploying `b3ae37b` only matters for future overlap rotations.
3. Session 1's inventory of which KEEL services hold each variable is deferred until the rotation is scheduled (the Render env-vars API returns values).
4. Confirm CI on `main` `b3ae37b` is green.

## Session 4 — production file storage (2026-11-09) — CLOSED, handed over

| Item | Where | Status | Evidence |
|---|---|---|---|
| Free storage choice: **Backblaze B2**, region **US West** (API runs in Render Oregon); Supabase (pauses idle projects, 1 GB) and Postgres storage (would fill the production DB) rejected; R2 / Render disk need payment | `docs/OBJECT_STORAGE_FREE_TIER.md` | decided | provider pages via web search (direct fetch blocked); not found: an explicit "no automatic paid conversion" statement, so the design relies on $0 caps + KEEL's 9 GB ceiling + no card on file |
| Code: storage adapter (single private bucket via `MINIO_BUCKET`, 25 MiB/file, 9 GB ceiling, 507 full / 503 unavailable, https where deployed, 5 s / 60 s timeouts, `/health/storage`, image ETag/304, EN/AR "storage full"); a failed/capped usage listing never refuses uploads | **`main` @ `d26b96c`** (squash of PR #115, same tree as `55f72c6`) | **merged to main** | PR #115 head `55f72c6`: all CI checks green (backend, frontend, browser-smoke, images, gitleaks). `main` push run at handover: secret scan green; PR Checks + Docker images were still running (same tree as the green PR run) |
| **Cross-tenant fix**: all companies' assistant summaries shared one object `_generated/<slot>.txt` -> `_generated/<tenant_id>/<slot>.txt`; import PDFs -> `uploads/<tenant_id>/<job_id>.pdf` | same commit | merged | two-company regression test; production never had storage, so no production object was affected |
| Local verification | — | PASS | local CI layout (PG16+pgvector, Redis 7, MinIO built from the pinned source): `src/` 5,267 passed, 1 failed = PG>=17 version assertion (same on old `main`); frontend 282/282; end-to-end on a real API with 2 synthetic companies (upload, download, anonymous 403, assistant retrieval with a labelled local mock model, tenant isolation, image persistence across restart, 507 when full, 503 when unreachable) |
| Independent review (Session 2) | — | PASS, no security issue | 2 availability findings fixed (`4b26c9e`, `55f72c6` on the PR branch; included in `d26b96c`) |
| B2 account | owner | done | US West, email verified, no payment method, all 4 daily caps $0 (owner's report) |
| Private bucket + bucket-scoped key | owner, B2 website | **OPEN** | API setup with the master key failed: B2 returned 401 `bad_auth_token` for the secure-form credential on every attempt (values never seen by any session). Steps: doc §3 steps 3-5 |
| Render `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` on `ceopro-ai-new` | owner, at Session 1's "storage window open" | **OPEN, held** | nothing changed on Render (only names read). Owner rule: no production setting change or deploy without explicit approval |
| Deploy of `d26b96c` (or later) | Session 1 | **OPEN** | only after owner approval and the bucket checks below; no migrations |
| Production verification | Session 2 (read-only) | **OPEN** | `/health/storage` = ok single_bucket; unsigned GET of bucket and object -> 403; other steps only with owner approval |

**Next steps (in order):**
1. **Owner, in the B2 website:**
   - Generate a new master key once, which revokes the one entered in the form.
   - Create the bucket: Private, encryption on, Object Lock off, lifecycle "keep only the last version", no CORS.
   - Create a key: only that bucket, Read and Write.
   - Give Session 2 the bucket name and endpoint host. Neither is secret.
2. **Owner:** delete the failed "Backblaze B2 master key (temporary, setup only)" network secret from the `ceopro-ai` agent environment.
3. **Owner:** approve the deploy. Session 1 then opens the window, the owner pastes the four values into Render, and Session 1 deploys and checks `/health/storage`.
4. **Session 2:** the read-only checks above.
5. **Follow-ups, not done:**
   - Measuring stored bytes from PostgreSQL instead of bucket listings needs a privileged cross-tenant read: a migration plus a role review.
   - A per-company daily image-read budget, because B2's 2,500 free downloads a day are shared by all companies.
   - Close or delete the obsolete branch `feat/free-object-storage`.

## Session 1 — Overture, memory, deployments (2026-11-08/09) — CLOSED (handover)

Session `session_01BF1evm6jhiwguiiZVnAHWT`. Local = cloud container; production = Render read-only checks. No production deploy, setting change or migration since the 04:02 UTC deploy below.

| Item | Branch / PR | Status | Evidence |
|---|---|---|---|
| Crashed scan locked "Refresh scan" (run stuck `running`) | [#96](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/96) | MERGED, **DEPLOYED** (in `99c213c`) | 7 tests (3 fail before) |
| Overture never in the API + admission control (one slot, bounded wait, no charge when busy) | [#97](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/97) | MERGED, **DEPLOYED** | production `/health/processor` → `overture: unsafe` |
| Team-invitation email failure returned 500 | [#98](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/98) | MERGED, **DEPLOYED** | 6 tests |
| Platform-owner portal Arabic garbled | [#99](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/99) | MERGED, not deployed (keel-web `375055c`) | integrity test |
| Overture reader memory-bounded (Dubai 1,002 → 279 MB) | [#100](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/100) | MERGED, not deployed | real-data benchmark, 5 tests |
| Migration owner keeps no restricted-role membership (Neon) | [#101](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/101) | MERGED, not deployed; #81 closed superseded | 5/5 on dedicated cluster |
| Emails in the reader's language with real expiry | [#102](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/102) | MERGED, not deployed | 19 tests |
| **Compact Overture mirror** (cell packs; stdlib range-request reader, no pyarrow in the API; inflated/line/tile caps; per-tile sha256 required from format 2; monthly workflow publishing a public pre-release) | [#116](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/116) head `c0ef4d9f` | **MERGED to main (`40e5d7b`)**, not published, not deployed; inert until `OVERTURE_MIRROR_URL` is set | CI on `c0ef4d9f` 6/6 green (backend, frontend, browser-smoke, gitleaks, images ×2); Session 2 security re-review: inflation finding FIXED (398 KB tile +1 MB, refused), format-2 tile without hash refused; overture tests 49 passed; full `src/` on the merge with main `b3ae37b` (fresh DB, 165 migrations): 5,257 passed / 90 skipped / 1 failed on a reused DB; the failed test (`test_standard_plan_creation_contract.py`, singleton-row duplicate from the first run) passes 9/9 on a fresh DB; real release `2026-10-21.0`, 24 cells, 4,577,681 places, verify 0 problems; Amman 5 km 0.6–0.9 s/+12 MB cold, Dubai 15 km 1.9 s/+7 MB, candidates identical to direct Overture |
| Load test, local API (35 users × 60 s) | — | measured | normal 62.7 req/s 0 errors; Overture inside API −15% throughput, p95 5–10×, +125 MB |

**Production at handover (read-only):** `ceopro-ai-new` live = `99c213c` (deploy `dep-dbokbr8u01pc73fhtemg`, rollback `700cb9d`); keel-web `375055c`; `/health` 200, `/health/ready` DB + Redis ok. Only the two KEEL Render services were ever read or changed; 360-Radar and other services untouched.

### Remaining — each needs the owner's explicit approval (nothing blocked on code)

1. **Production DB backup + migration rehearsal** before deploying `main` (now 5+ migrations): Neon branches `restore-point-<date>` and `rehearsal-<date>` (owner, console) → restore test (identical `schema_migrations` and row counts for companies, tenant_users, billing_subscriptions, products, credit ledger; Session 2 independently) → `scripts/apply_migrations.py` from `main` against `rehearsal` only ("Applied N", rerun "Applied 0", FORCE RLS and restricted roles unchanged) → owner approval → deploy `main` → startup log + `/health/ready` + independent verification. Restore path: point `DATABASE_URL` at `restore-point` and redeploy `99c213c`.
2. **Overture mirror go-live:** run workflow `overture-mirror.yml` (or upload the verified packs) to publish pre-release `overture-mirror-2026-10-21.0` → run `backend/scripts/overture_mirror/verify.py` on the downloaded assets → set `OVERTURE_MIRROR_URL` on `ceopro-ai-new` → deploy → `/health/processor` shows `mirror`, one real scan in Amman/Dubai. Note: the monthly cron (`41 2 3 * *`) on main publishes a new pre-release automatically; disable the workflow if publishing should wait.
3. **#115 storage** (on main `d26b96c`): B2 bucket + `MINIO_*` values on Render, then deploy (Session 4 handover above).
4. **#107 JWT rotation** (on main `b3ae37b`): per Session 3 handover; hard rotation needs no code.
5. **keel-web:** deploy `main` for #99/#103.
6. Longer term: D2 credit periods (3 open owner decisions), F2 failed-campaign reason (needs a migration), VELORA demo-data inventory (needs approved access), test hygiene T1, free-plan wake latency (accepted).

## Session 2 successor — completed (2026-11-09)

Session `session_01BF1evjasZyYcJBjuxhn6uJ`. Branches pushed after the owner's go-ahead; PRs follow. Merges stay with the
owner (agent merges are refused by the permission check).

| Item | Branch | Status | Evidence |
|---|---|---|---|
| CI-equivalent stack incl. object storage | — | PASS | PG17 ×2 + Redis 7 (Docker) and **MinIO built natively** from CI's pinned source with the host's Go 1.24 (`go install github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c`) - removes the "MinIO cannot be built here" blocker |
| Backend suites on `main` + #104 + #105 (merge-preview) | — | PASS | fresh clusters, MinIO up: `src/` 5,269 passed, 0 failed, 23 skipped; `tests/` 546 passed. (A first run without MinIO: 27 failed + 6 errors, all MinIO-backed; the 7 files then 69 passed) |
| Real-data discovery, 2nd business type: a pharmacy | `feat/discovery-health-trades` [#113](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/113) (on #105) | PASS, CI green on `60959ea` (all 6 jobs, 11:07) | `docs/REAL_DATA_DISCOVERY_TEST_2026-11-08.md` § pharmacy: other health trades listed 30 → 4, among the 10 auto-tracked 4 → 0, real pharmacies removed 0, self excluded; café re-run: 0 removed, 0 relationship changes, 2 mistyped cafés recovered. Root causes: 2-level health paths scored 0.5 (= competing bar); map type always beat the name inside a domain; Arabic article/letter forms never matched. Unit tests 858 + 564 passed; full `src/` on main+#104+#105+this: 5,269 passed, 0 failed |
| IDOR sweep extended (object storage, campaigns, documents, import batches, notifications, data-source sub-routes, catalog, quotes) | `test/idor-sweep-extension` [#112](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/112) | PASS, CI green | `docs/SECURITY_MULTI_TENANT_TEST.md` § 2026-11-09: `attack.py` 401 req ×2 dirs, `idor_extended.py` (new, the 43 id routes never named) 57 req ×2 dirs, 0 findings / 0 oracle diffs / 0 changed victim rows; RLS matrix 115 tables `FAILS: []`; xref 0 cross-tenant refs / 6,553 ids |
| **Finding (Low):** `POST /competitors/{other company's id}/enrich` → 500 / connection reset | `fix/enrich-foreign-competitor-404` [#111](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/111) | FIXED, CI green | Receipt authorization refused correctly but was unmapped; now 404 like data-status. New test fails before (2/2) / passes after; competitor + receipt tests 139 passed; harness re-run 0 server errors. No data exposed |
| Platform routes: Tenant Owner got 422 with the admin schema (Low) | `fix/platform-router-gate` [#114](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/114) | FIXED, CI green | router-level gate before body validation: 403 on all 60 gated routes, 401 anonymous, invitations still public; 42/120 new checks fail without it; `src/` 5,252 passed 0 failed; `tests/` 666 passed + 3 pre-existing `main` failures fixed by #104 |
| Read-only production check 09:46 UTC | — | PASS | `/health/ready` DB + Redis ok; `/health/processor` `overture: unsafe`; backend `99c213c`, keel-web `375055c`; no Render failure events since 04:07 |
| Owner decision: same industry with no products/specialty → DIRECT | #113 (commits `4bc98b1`, `60959ea`) | PASS | default only when the owner gave no products and no specialty words in the business type (AI words don't count); a default DIRECT still has to pass the segment filter. Real data: pharmacy 0→191 DIRECT, café 0→450, stored lists and auto-tracked ten identical. Unit 859 passed, frontend 282/282, full `src/` 5,276 passed 0 failed, `tests/` 546 passed |
| Review of #107 (JWT rotation overlap), requested by Session 3 | — | FAIL (High finding) | verified on the branch with a throwaway test: an old-key token forged with `auth_time` in the future renews to a new-key token (200), survives removal of `JWT_SECRET_PREVIOUS`, never hits `SESSION_MAX_HOURS` (negative age) and renews again (200). Fixes proposed to Session 3 and owner: reject future `auth_time`/`iat`; no renewal of previous-key tokens; hard rotation (no overlap) for this publicly exposed key. Core decode logic otherwise correct; CI green |
| Re-review of #107 at `a8eb106` (Session 3's fix) | — | FAIL (High: one remaining path), reported to owner + Session 3 | throwaway tests on `a8eb106`: future `auth_time` refused for both keys (401), refresh of an old-key token 401, Session 3's suite 26 passed. But `POST /auth/workspaces/switch` (same tenant allowed) accepts a forged old-key token → 200 with a NEW-key token, which still renews (200) after `JWT_SECRET_PREVIOUS` is removed; `POST /auth/workspaces` does the same. Proposed: one current-key-only dependency on every token-issuing route + a test enumerating them; runbook to record the owner's option A. Not a risk for the owner's chosen hard rotation (no previous key is ever set), only for the overlap feature |
| #107 at `1bd52e4` (docs-only on `a8eb106`) | — | Runbook PASS; code still FAIL (switch/create path above) | runbook step 1 records the owner's hard rotation: only a new `JWT_SECRET`, never `JWT_SECRET_PREVIOUS`, fix forward, pre-deploy tab must get 401. **The hard rotation needs no code change, so the incident rotation does not depend on #107**; #107 only matters for future overlap rotations |
| Production storage checks (#115) | — | BLOCKED | waiting for Session 1 to deploy #115; 09:59 `/health/storage` 404, live `99c213c`. Owner approved only the read-only checks (health, unsigned bucket/object GET = 403); no accounts, uploads, image generation or paid calls without explicit approval |
| Review of #116 (Overture mirror reader), requested by Session 1 | — | FAIL (Medium, availability), reported to owner + Session 1 | on head `c44d7277`, throwaway probe (mock transport, one tile, no newline): 50 KB compressed → peak RSS +137 MB, 199 KB → +475 MB, 398 KB → +867 MB, all `status ok`; the guard caps only compressed size (8 MB), so one tampered or misserved tile can OOM the 512 MB API. Fix proposed: cap decompressed bytes and line length per tile (+ optional per-tile sha256). Workflow itself OK (dispatch/schedule only, inputs via env). Full review after CI is green |
| Harness false positive (`discovery_runs` changed) | `test/idor-sweep-extension` | FIXED | the attacker's own run (correctly scoped to itself) was still running when the reverse pass snapshotted; `attack.py` now waits for in-flight runs; re-run 0 findings |

### Open questions for the owner (Session 2 successor)

Decided by the owner (2026-11-09 ~10:55 UTC):
1. **#107: no overlap.** The exposed old signing key must stop being accepted at once; re-login is acceptable.
   Relayed to Session 3 with the runbook/verification changes this implies (the pre-deploy tab must now get 401).
   Session 2 successor re-reviews the final head (including the forged-renewal probe) before recommending deployment.
2. **Pharmacies by name only stay `INDIRECT`** (the 39 typed "health care" etc.) unless reliable category evidence
   confirms them. Already the behaviour of #113; no change.

### Status board — Session 2 successor (2026-11-09 15:25 UTC)

Legend: **VERIFIED** = run or read by this session, with the evidence named; **REPORTED** = another session's claim,
not re-run here; **PENDING** = not yet checkable.

| Item | Head | State | Evidence | Owner / next action |
|---|---|---|---|---|
| #107 JWT rotation | `6e4590d4` | **VERIFIED PASS**: security re-review + CI 6/6 green (15:28) | My throwaway probes on this head: old-key token on refresh, workspaces/switch, workspaces (create), change-password → 401, no token, no DB connection; future `auth_time` → 401 for both keys; current-key refresh/switch 200; old-key token 401 after `JWT_SECRET_PREVIOUS` removal. My grep: those 4 are the only session-based token issuers (login, email verify, both invitation accepts use password/code/token). Fresh PG17: `test_jwt_key_rotation.py` 31 passed; `src/` 5,283 passed 0 failed; `tests/` 543 passed + 3 pre-existing `main` failures (fixed by #104) | Session 3: none. Owner: approval/merge. Note: the owner's hard rotation needs no code change |
| #107 runbook | `6e4590d4` | VERIFIED | step 1 = owner's hard rotation (no `JWT_SECRET_PREVIOUS`, fix forward, pre-deploy tab must get 401) | — |
| #116 Overture mirror | `c0ef4d9f` | Inflation finding **VERIFIED FIXED**; CI running at 15:39 (final PASS waits on it) | my probe: 50/199/398 KB tiles → +137/+475/+867 MB on `c44d7277`; +0/+1/+1 MB on `823cf8be`, larger ones refused; on `c0ef4d9f` 398 KB → +1 MB refused, and a format-2 tile without a sha256 → refused (hash now required from format 2). `test_market_discovery_overture.py` 49 passed locally. Correction: my earlier `verify.py` note (missing `continue`) was wrong; the crash risk was the `entry[:3]` unpack before the shape check, now fixed (REPORTED by Session 1, matches the code) | owner: merge/publish decision after CI |
| #115 B2 storage, code | `55f72c6d` | Security review **VERIFIED: no vulnerability**; availability finding **VERIFIED FIXED** (CI on `55f72c6d` at 15:39: 4/6 green, 2 `images` running) | on `785002c6` my fake-Minio probe gave 507 "storage full" after a capped listing; on `4b26c9e1` and `55f72c6d` the same probe → upload accepted; `test_object_storage` + `test_config_check` 33 passed locally (real MinIO) on both. Listing interval 600 → 3600 s; doc corrected (ceil(objects/1000) Class C per listing). The minor re-list-on-every-write point is fixed in `55f72c6d` | Session 4: none; owner: bucket settings + deploy approval |
| #115 bucket settings A1-A7 | — | PENDING (owner confirms in B2 console; REPORTED via Session 4 when done) | private bucket, SSE-B2, keep-last-version lifecycle, no Object Lock, no CORS, one-bucket R/W key without list-all, $0 caps + alerts | Owner + Session 4 |
| #115 external checks | — | PENDING | unsigned bucket listing / object GET → 403; `/health/storage` after deploy. Needs endpoint host + bucket name only (never keys) and an approved deploy | Session 4 → me |
| Production, read-only | `99c213c` API, `375055c` web | VERIFIED 15:13 | `/health/ready` DB 31 ms, Redis 114 ms; `/health/processor` `overture: unsafe`; `/health/storage` 404 (#115 not deployed); first request 23.5 s = free-plan wake-up (no Render failure/restart/OOM event since 04:07) | — |
| #111-#114 | `3156173`, `5abfb91`, `60959ea`, `f546237` | CI green on each head (VERIFIED via GitHub checks); 0 review threads/comments | — | Owner: merge decision |
| Backup before main's 5 migrations | — | PENDING | owner requires a restore test + migration test on a separate copy; no production DB credentials requested or used until the owner approves a secure read-only method | Session 1 plan + owner |

### Remaining blockers (Session 2 successor, 2026-11-09 ~11:15 UTC)

| Blocker | Waiting on |
|---|---|
| #107 deployable | review PASS + CI green at `6e4590d4`; only the owner's approval remains. (Not needed for the hard rotation itself) |
| #116 deployable | MERGED to main `40e5d7b` (CI 6/6 green on `c0ef4d9f`, fix verified) → owner's decision on publishing the mirror release and deploying |
| #115 deployable | CI green on `55f72c6d`; owner confirming bucket settings A1-A7 (REPORTED via Session 4); my external 403 checks (needs endpoint host + bucket name); owner's explicit deploy approval |
| Backup verification before main's 5 migrations | owner-approved secure read-only access method; until then I request and use no production database credentials |
| Merges of #103-#106, #111-#114 | owner (agent merges refused by the permission check) |

### FINAL HANDOVER — Session 2 successor (2026-11-09 ~16:10 UTC) — CLOSED

**Submitted work:** PR [#125](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/125), branch `release/session2-work`, head
`c3095941` (author/committer Huda). It carries the content of #105, #113, #111, #112 and #114 as five commits
(`146229c5`, `d68f9a4e`, `e0e91949`, `bc58fd2b`, `8a039580`), plus a merge of `main` `b3ae37b9` (`173751fa`) and a
regenerated `docs/reference/ENVIRONMENT_INVENTORY.md` (`c3095941`).

**Why not on `main`:** a direct push to `main` was refused by the session permission check ("merge without
review"), and a force-update of the branch was refused too. Neither was worked around. **Owner action:** review and
merge #125, then close #105, #111, #112, #113 and #114 as superseded by #125. Their branches carry tool trailers;
#125 does not.

**Verification (VERIFIED on a tree byte-identical to `c3095941`):**
- Environment: fresh PG17 + Redis 7 + MinIO (built from CI's pinned source).
- `backend src/`: 5,322 passed, 0 failed, 23 skipped.
- `backend tests/`: 666 passed, 3 failed. The 3 failures (`tests/keel_integration/test_auth_phase1a.py`: signup and
  durable-send-limit email doubles) fail identically on `main` `b3ae37b9`; they are fixed by #104; CI runs `src/` only.
- frontend: 282/282.
- `tools/dev/environment_inventory.py --check`: matches.
- CI on #125: running at handover. Each source PR was CI-green on its own head; the owner must confirm #125's
  CI before merging.

**What the work does:**
- Discovery: adaptive radius, relevance fixes (map type vs name, health trades separated, Arabic folding).
- Discovery: same industry is DIRECT when the owner gave no products/specialty (owner decision). Real-data
  results are in `docs/REAL_DATA_DISCOVERY_TEST_2026-11-08.md`.
- `POST /competitors/{id}/enrich` answers 404 (not 500) for a competitor the company does not track.
- `/platform` routes check the platform role before body validation (403, never the admin schema).
- Security harness: current sign-up, `enrich_state.py`, `idor_extended.py`, no false finding from in-flight runs.
  Results are in `docs/SECURITY_MULTI_TENANT_TEST.md`.

**Reviews done for other sessions (VERIFIED):**
- #107 / `main` `b3ae37b9`: security re-review PASS at `6e4590d4` (all 4 token-issuing routes refuse old-key
  sessions; future `auth_time` refused), CI 6/6 green.
- #115 / `main` `d26b96c2`: no vulnerability; the listing-cap availability finding was verified fixed at `55f72c6d`.
- #116 at `c0ef4d9f`: decompression finding verified fixed (398 KB tile +867 MB → +1 MB); CI 6/6 green
  (checked ~16:15 UTC) → review PASS.

**Not done / open (owner):**
- Merge #125 (and #103, #104, #106, which stay open as they were).
- #116: review PASS + CI green on `c0ef4d9f`; owner decides on the merge and on publishing the mirror release.
- #115 is on `main` but not deployed. Before deploying:
  - the owner confirms the B2 bucket settings A1-A7 (private, SSE-B2, keep-last-version, no Object Lock, no CORS,
    a one-bucket key, $0 caps);
  - external checks: unsigned bucket listing and object GET return 403, then `/health/storage`.
- Backup before the 5 migrations: a restore test plus a migration test on a separate copy (Neon branch). This needs
  a secure read-only access method approved by the owner; no production credentials were requested or used.
- Production: read-only throughout; last check 15:13 UTC healthy (API `99c213c`, web `375055c`). No deploys,
  migrations, configuration or data changes were made.

## Next steps — Session 2 successor (updated 2026-11-09)

1. Keep #111-#114 and #103-#106 green; merges are blocked for agents by the permission check, the owner merges.
   **Open gap (owner: Session 1):** `MINIO_ENDPOINT` is not configured in production, so uploads and stored marketing
   images are unavailable. Verify read-only once Session 1 configures it.
2. Keep #103-#106 green; #103 and #105 are 5 commits behind `main` but merge cleanly (checked with `git merge-tree`).
3. After each Session 1 deploy: repeat the read-only production verification.
4. Custom-offer quotes with a real quote (needs the platform-admin pricing flow on the throwaway stack).
5. Real-data discovery for a third type (bakery or supermarket), now that health trades are separated.

## Blockers that need the owner

1. **Merging** - both sessions' merges are refused by the session permission check ("merge without review"). Merge green PRs yourself, or allow merges.
2. **Plaintext production secrets in cloud environments** - removed from `ceopro-ai` (04:30); the `Default` environment still holds `DATABASE_URL`, `APP_DB_PASSWORD`, `POSTGRES_PASSWORD`, `JWT_SECRET`, `REDIS_URL`, `GROQ_API_KEY`, `BREVO_API_KEY` as plain environment variables readable by every agent process. Recommended: rotate them (JWT secret, DB password, Brevo and Groq keys) and keep only network secrets (proxy-injected) in agent environments.
3. **Credentials pasted in chat** (KEEL login, a Gmail password) - change both.
4. **Commercial decisions** - #93-#95 (card-required trials, catalogue limits).
5. **Production file storage** - `MINIO_ENDPOINT` unset in production (reported by Session 1): customer uploads and stored marketing images unavailable. Code on `main` (`d26b96c`). Remaining: the owner creates the private bucket and scoped key (`docs/OBJECT_STORAGE_FREE_TIER.md` §3), then sets the Render values at Session 1's storage window and approves the deploy.

## Next steps — Session 2 successor

1. After #104 merges: rebase #105 if needed; keep CI green.
2. Extend the IDOR sweep to campaigns, documents, invitations and import batches with data (needs AI and object storage locally: MinIO cannot be built in this sandbox - DNS-less docker build).
3. After each Session 1 deploy: repeat the read-only production verification above and record it here.
4. Real-data discovery for a second business type (e.g. pharmacy or bakery) to check the relevance rules beyond cafés.
