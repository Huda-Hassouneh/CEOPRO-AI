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

## Session 3 — credential rotation (2026-11-09)

| Item | Branch / PR | Status | Evidence |
|---|---|---|---|
| `JWT_SECRET` rotation overlap: sign with `JWT_SECRET` only, verify current then `JWT_SECRET_PREVIOUS`; `exp`, revocation, credential_version unchanged; rate limiter + config_check aware | `fix/jwt-key-rotation-overlap` [#107](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/107) | PR open at `1bd52e4`, **awaiting Session 2 re-review (PASS), CI, owner merge + deploy approval** | CI green on `75614b0` (Session 2) |
| Session 2 review finding (High): an old-key token forged with a far-future `auth_time` was renewed into a new-key session that outlived the rotation | #107 `a8eb106` | **fixed** | reproduced first (refresh 200, accepted after removing the previous key, negative age); now previous-key tokens are never renewed (401) and future `auth_time` is refused; local fresh PG16 + Redis: `test_jwt_key_rotation.py` 26 passed, the 4 regression tests fail on `75614b0`; full `src/` 5,225 passed, 75 skipped, 1 failed (PG≥17 assertion; sandbox has PG16) |
| Rotation runbook per secret (JWT A/B, Neon owner, `ceopro_app`, Upstash, Brevo, Groq, Render API key): actor, continuity, verification, rollback | #107, `docs/SECURITY_CREDENTIAL_ROTATION.md` | written; **not executed** | — |
| Owner decision (~10:55 UTC, relayed by Sessions 1/2) | — | **decided: hard JWT rotation, no overlap** | runbook step 1 updated at #107 head `1bd52e4`; overlap kept only for future routine rotations. #107 not deployable until Session 2 records PASS here and the owner approves the deploy |

Next: owner removes the variables from the `Default` agent environment; Session 2 re-reviews #107; rotation (hard JWT rotation and steps 2-6, none of which need #107) runs with Session 1 once the owner schedules it.

## Session 4 — production file storage (2026-11-09)

| Item | Branch / PR | Status | Evidence |
|---|---|---|---|
| Free storage choice: **Backblaze B2** (10 GB, no card, all B2 caps $0); Supabase (pauses after a week idle, 1 GB) and Postgres storage (fills the production DB) rejected; R2/Render disk need payment | `docs/OBJECT_STORAGE_FREE_TIER.md` in [#115](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/115) | decided | provider pages via web search (direct fetch blocked by session network); unverified: whether a no-card account is hard-blocked at 10 GB - not relied on |
| Storage adapter: single private bucket (`MINIO_BUCKET`), 25 MiB/file, 9 GB ceiling, 507 full / 503 unavailable, https where deployed, 5 s timeouts, `/health/storage`, image ETag/304, EN/AR "storage full" | `feat/free-object-storage` [#115](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/115) | PR open, **awaiting CI + owner merge** | local CI layout (PG16+pgvector, Redis 7, MinIO built from the pinned source, local URLs only): `src/` 5,267 passed, 23 skipped, 1 failed = PG>=17 assertion (same on `main`); frontend 282/282 |
| **Cross-tenant bug fixed**: every company's assistant summary shared object `_generated/<slot>.txt` (B's write could be embedded in A's index; deleting one company deleted all summaries) -> `_generated/<tenant_id>/<slot>.txt` | same PR | fixed | new two-company regression test; production never had storage, so no production object affected |
| Local end-to-end (real API, 2 synthetic companies, single-bucket mode) | same PR | PASS | upload -> download (byte-identical) -> anonymous 403 -> retry re-read -> assistant receives the text (model = labelled local mock); B isolated; image stored, served, 304, B 404, survives restart; ceiling -> 507; endpoint down -> 503, readiness unaffected |
| Production setup | — | **needs owner** | owner creates B2 account + $0 caps + private bucket + bucket-scoped key (doc §3, keys only in Render); then Session 1 deploys, Session 2 verifies (doc §4) |

## Session 1 — Overture, memory, deployments (2026-11-08/09)

Session `session_01BF1evm6jhiwguiiZVnAHWT`. Only Session 1 deploys. Local = this cloud container; production = Render read-only checks.

| Item | Branch / PR | Status | Evidence |
|---|---|---|---|
| Crashed scan locked "Refresh scan" (run stuck `running`) | [#96](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/96) | MERGED, **DEPLOYED** (in `99c213c`) | 7 tests (3 fail before); production `/health/processor` route present |
| Overture never in the API + admission control (one slot, bounded wait, no charge when busy) | [#97](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/97) | MERGED, **DEPLOYED** | production `/health/processor` → `overture: unsafe` |
| Team-invitation email failure returned 500 for a saved invitation | [#98](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/98) | MERGED, **DEPLOYED** | 6 tests through the real sender |
| Platform-owner portal Arabic garbled (289 strings) | [#99](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/99) | MERGED, not deployed (keel-web still `375055c`) | integrity test; 282/282 frontend |
| Overture reader memory-bounded (Dubai 1,002 → 279 MB, identical) | [#100](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/100) | MERGED, not deployed | real-data benchmark, 5 tests |
| Migration owner keeps no restricted-role membership (Neon) + #81's integration test | [#101](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/101) | MERGED, not deployed; #81 CLOSED superseded | 5/5 on a dedicated cluster (4/5 before) |
| Emails in the reader's language with real expiry | [#102](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/102) | MERGED, not deployed | 19 tests; CI caught 2 MinIO-only doubles, fixed |
| **Compact Overture mirror** (cell packs, stdlib reader, no pyarrow in API; monthly workflow publishing a public pre-release) | `feat/overture-compact-mirror` [#116](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/116) | PR open, CI running | real release `2026-10-21.0`, 24 cells (20°W–60°E, 10°N–40°N), **4,577,681 places, every tile verified, 0 problems**; Amman 5 km 13.7 s/564 MB → 0.5–0.7 s/+5–16 MB, Dubai 15 km 15.2 s/1,002 MB → 1.6 s/+6–25 MB, candidates identical; full `src/` fresh DB 5,205 passed / 80 skipped / 0 failed |
| Load test, local API (35 users × 60 s) | — | measured | normal 62.7 req/s 0 errors; Overture *inside* the API: −15% throughput, p95 5–10×, +125 MB; API never running it: +47 MB |
| Production read-only check 10:50 UTC | — | PASS | `/health` 200; `/health/ready` DB 26 ms, Redis 88 ms; `/health/processor` `overture: unsafe`; memory 215–277 MB (6 h); deploys since Nov 7: only `99c213c`; keel-web untouched |

**Session 1 deploy queue** (owner instruction 10:5x: no new deployment until told):
1. Overture mirror: merge #116 → publish the release (workflow or upload of the verified packs) → set `OVERTURE_MIRROR_URL` on `ceopro-ai-new` → deploy → verify `/health/processor` and a real scan.
2. `main` (5 migrations, rehearsed clean on a Neon-like non-superuser cluster): needs a production DB backup/branch first.
3. #115 storage: after the owner's B2 account + merge (Session 4 handover, doc §4).
4. #107 JWT rotation: **not before** the High finding above is fixed, re-reviewed and merged.
5. keel-web: deploy `main` for #99 / #103.

## Session 2 successor — completed (2026-11-09)

Session `session_01BF1evjasZyYcJBjuxhn6uJ`. Branches pushed after the owner's go-ahead; PRs follow. Merges stay with the
owner (agent merges are refused by the permission check).

| Item | Branch | Status | Evidence |
|---|---|---|---|
| CI-equivalent stack incl. object storage | — | PASS | PG17 ×2 + Redis 7 (Docker) and **MinIO built natively** from CI's pinned source with the host's Go 1.24 (`go install github.com/minio/minio@v0.0.0-20260212201848-7aac2a2c5b7c`) - removes the "MinIO cannot be built here" blocker |
| Backend suites on `main` + #104 + #105 (merge-preview) | — | PASS | fresh clusters, MinIO up: `src/` 5,269 passed, 0 failed, 23 skipped; `tests/` 546 passed. (A first run without MinIO: 27 failed + 6 errors, all MinIO-backed; the 7 files then 69 passed) |
| Real-data discovery, 2nd business type: a pharmacy | `feat/discovery-health-trades` [#113](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/113) (on #105) | PASS, CI on `60959ea`: gitleaks + frontend green, backend/browser/images running (10:56) | `docs/REAL_DATA_DISCOVERY_TEST_2026-11-08.md` § pharmacy: other health trades listed 30 → 4, among the 10 auto-tracked 4 → 0, real pharmacies removed 0, self excluded; café re-run: 0 removed, 0 relationship changes, 2 mistyped cafés recovered. Root causes: 2-level health paths scored 0.5 (= competing bar); map type always beat the name inside a domain; Arabic article/letter forms never matched. Unit tests 858 + 564 passed; full `src/` on main+#104+#105+this: 5,269 passed, 0 failed |
| IDOR sweep extended (object storage, campaigns, documents, import batches, notifications, data-source sub-routes, catalog, quotes) | `test/idor-sweep-extension` [#112](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/112) | PASS, CI green | `docs/SECURITY_MULTI_TENANT_TEST.md` § 2026-11-09: `attack.py` 401 req ×2 dirs, `idor_extended.py` (new, the 43 id routes never named) 57 req ×2 dirs, 0 findings / 0 oracle diffs / 0 changed victim rows; RLS matrix 115 tables `FAILS: []`; xref 0 cross-tenant refs / 6,553 ids |
| **Finding (Low):** `POST /competitors/{other company's id}/enrich` → 500 / connection reset | `fix/enrich-foreign-competitor-404` [#111](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/111) | FIXED, CI green | Receipt authorization refused correctly but was unmapped; now 404 like data-status. New test fails before (2/2) / passes after; competitor + receipt tests 139 passed; harness re-run 0 server errors. No data exposed |
| Platform routes: Tenant Owner got 422 with the admin schema (Low) | `fix/platform-router-gate` [#114](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/114) | FIXED, CI green | router-level gate before body validation: 403 on all 60 gated routes, 401 anonymous, invitations still public; 42/120 new checks fail without it; `src/` 5,252 passed 0 failed; `tests/` 666 passed + 3 pre-existing `main` failures fixed by #104 |
| Read-only production check 09:46 UTC | — | PASS | `/health/ready` DB + Redis ok; `/health/processor` `overture: unsafe`; backend `99c213c`, keel-web `375055c`; no Render failure events since 04:07 |
| Owner decision: same industry with no products/specialty → DIRECT | #113 (commits `4bc98b1`, `60959ea`) | PASS | default only when the owner gave no products and no specialty words in the business type (AI words don't count); a default DIRECT still has to pass the segment filter. Real data: pharmacy 0→191 DIRECT, café 0→450, stored lists and auto-tracked ten identical. Unit 859 passed, frontend 282/282, full `src/` 5,276 passed 0 failed, `tests/` 546 passed |
| Review of #107 (JWT rotation overlap), requested by Session 3 | — | FAIL (High finding) | verified on the branch with a throwaway test: an old-key token forged with `auth_time` in the future renews to a new-key token (200), survives removal of `JWT_SECRET_PREVIOUS`, never hits `SESSION_MAX_HOURS` (negative age) and renews again (200). Fixes proposed to Session 3 and owner: reject future `auth_time`/`iat`; no renewal of previous-key tokens; hard rotation (no overlap) for this publicly exposed key. Core decode logic otherwise correct; CI green |
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

### Remaining blockers (Session 2 successor, 2026-11-09 ~11:15 UTC)

| Blocker | Waiting on |
|---|---|
| #107 deployable | Session 3's final head (no overlap, owner decision) → my independent re-review recorded PASS here |
| #116 deployable | fix for the decompression finding → my re-review after CI is green |
| Production storage checks | Session 1 deploying #115 (owner: no deployments until separately approved); then only health + unsigned-access 403 checks |
| Backup verification before main's 5 migrations | owner-approved secure read-only access method; until then I request and use no production database credentials |
| Merges of #103-#106, #111-#114 | owner (agent merges refused by the permission check) |

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
5. **Production file storage** - `MINIO_ENDPOINT` unset in production (reported by Session 1): customer uploads and stored marketing images unavailable. Owned by Session 4: fix in [#115](https://github.com/Huda-Hassouneh/CEOPRO-AI/pull/115); the owner creates a free Backblaze B2 account (no card) per `docs/OBJECT_STORAGE_FREE_TIER.md` §3; keys go into the Render dashboard, never chat.

## Next steps — Session 2 successor

1. After #104 merges: rebase #105 if needed; keep CI green.
2. Extend the IDOR sweep to campaigns, documents, invitations and import batches with data (needs AI and object storage locally: MinIO cannot be built in this sandbox - DNS-less docker build).
3. After each Session 1 deploy: repeat the read-only production verification above and record it here.
4. Real-data discovery for a second business type (e.g. pharmacy or bakery) to check the relevance rules beyond cafés.
