# KEEL task register

The single shared record of who is doing what, what is verified, and what is next. Each session updates **its own
rows** and adds dated entries; nobody rewrites another session's rows. Evidence means a command that was actually run
(PASS / FAIL / BLOCKED), never an assumption.

## Ownership (assigned by the owner, 2026-11-09)

| Session | Owns | Production deploys |
|---|---|---|
| **Session 1** `session_01BF1evm6jhiwguiiZVnAHWT` | Overture mirror implementation, memory profiling and optimization, their deployment and deploy verification | **Deployment owner** (one deployer at a time) |
| **Session 2** `session_01BF1evkf4NUTzeuRAHoYgjH` and its successors | CI-equivalent isolated test environment, IDOR/security testing, real-data discovery testing, independent read-only production verification | Never deploys; verifies after each deploy |

## Production state

| When (UTC) | What | Evidence |
|---|---|---|
| 2026-11-09 04:02 | Session 1 deployed `99c213c` (prod branch `claude/vibrant-albattani-j2ksq5`) to Render `ceopro-ai-new`; previous live deploy `dep-dbnaubrl550s73emn1u0` (`700cb9d`) is the rollback target | Render deploy `dep-dbokbr8u01pc73fhtemg` = live |
| 2026-11-09 ~04:10 | Session 2 independent verification of that deploy | PASS: `/health` 200; `/health/ready` DB + Redis ok; `/health/processor` 200 `overture: unsafe` (404 before = old code); Chrome smoke on keelai.net 28/28 screens clean in EN 1440 px, AR 390 px, dark; backend `src/` on the exact `99c213c` tree, fresh PG17 + Redis: **5,016 passed, 0 failed** |
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

## Blockers that need the owner

1. **Merging** - both sessions' merges are refused by the session permission check ("merge without review"). Merge green PRs yourself, or allow merges.
2. **Plaintext production secrets in cloud environments** - `Default` and `ceopro-ai` environments hold `DATABASE_URL`, `APP_DB_PASSWORD`, `POSTGRES_PASSWORD`, `JWT_SECRET`, `REDIS_URL`, `GROQ_API_KEY`, `BREVO_API_KEY` as plain environment variables readable by every agent process. Recommended: rotate them (JWT secret, DB password, Brevo and Groq keys) and keep only network secrets (proxy-injected) in agent environments.
3. **Credentials pasted in chat** (KEEL login, a Gmail password) - change both.
4. **Commercial decisions** - #93-#95 (card-required trials, catalogue limits).

## Next steps — Session 2 successor

1. After #104 merges: rebase #105 if needed; keep CI green.
2. Extend the IDOR sweep to campaigns, documents, invitations and import batches with data (needs AI and object storage locally: MinIO cannot be built in this sandbox - DNS-less docker build).
3. After each Session 1 deploy: repeat the read-only production verification above and record it here.
4. Real-data discovery for a second business type (e.g. pharmacy or bakery) to check the relevance rules beyond cafés.
