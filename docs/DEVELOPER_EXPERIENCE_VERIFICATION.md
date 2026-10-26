# Developer experience verification

## Result

**Windows developer workflow verified.** The root command starts an isolated local KEEL runtime, checks real dependencies/readiness, and stops only its owned resources. Application business logic is unchanged.

Verified implementation revision: **8cce0e39241d11734a5d6ad3637d6fb4ab13d759**. The documentation closure commit adds this report; the final delivery HEAD is available with `git rev-parse integration/keel-full-migration`.

## Supported and exercised environment

| Environment | Result |
|---|---|
| Windows NT 10.0.26200, Windows PowerShell 5.1.26100.9711 | PASSED |
| CPython 3.12.7, 64-bit | PASSED |
| Node 24.22.0 / npm 11.19.1 | PASSED |
| Docker Engine 29.8.0 / Compose 5.5.1, local desktop-linux context | PASSED |
| Git Bash syntax checks for dev.sh and keel | PASSED (host context) |
| Linux/macOS runtime | UNRUN; shared Bash/Python entry point provided |
| Python 3.11 runtime | UNRUN in this task; accepted version matches the existing Python container baseline |
| Optional heavy model install / model-weight downloads | UNRUN |
| Real Stripe / Shopify / WooCommerce / hosted AI acceptance | UNRUN in this task; no need to repeat unchanged business acceptance |

The initial sandbox could not access Docker's named pipe or Git Bash's signal pipe. Authorized host execution was used; no system proxy, global Docker context or organizational restriction was changed.

## Fresh-checkout method

A committed-source archive was extracted into **%TEMP%/KEEL/Fresh Clone With Spaces**, then attached to independent shallow Git metadata fetched from the local committed branch. Later corrections were transferred only from committed snapshots. The final application checkout was clean apart from ignored generated test configuration/evidence.

This checkout initially had **no venv, node_modules, .env, seed records or running app**. Setup created a new venv and installed declared/constrained packages, then ran npm ci. Existing developer/verification venvs, API 8024, frontend 5204 and previously seeded databases were not used as fresh-clone evidence.

Docker's normal image/build cache and the host's installed Git/Python/Node/Chrome were prerequisites. MinIO was built using the existing pinned source Dockerfile. No machine-specific application path or personal credentials are present in the launcher.

## Actual checks

| Check | Result / evidence |
|---|---|
| Root help and prerequisite checks | PASSED; incompatible Python/Node and unavailable Docker have actionable failures |
| Initial setup | PASSED after correcting pip extras constraints and PowerShell stderr handling |
| Repeated setup | PASSED; generated config/secrets hash unchanged; dependency fingerprints reused |
| Infrastructure-only initialization | PASSED via infra; dedicated PostgreSQL/Redis/MinIO/Mailpit |
| Fresh migrations | PASSED: 137/137, existing Python runner |
| Repeat migrations | PASSED: zero newly applied |
| Native DB test command | PASSED: separate generated test DB, fresh/repeat migration chain |
| Existing PostgreSQL RLS tests | **18 passed, zero failed/skipped** |
| Restricted login | PASSED: ceopro_app, no superuser/BYPASSRLS/createdb/createrole |
| Security flags | PASSED: 120 FORCE RLS tables; three exact source-declared owner-bypass exceptions retain policies and separate ownership |
| Full startup | PASSED: FastAPI, Vite, all eight selected workers, four infrastructure services |
| Core startup | PASSED: FastAPI, Vite, forecast/images/connectors and infrastructure |
| Worker evidence | Redis consumer registration, fresh image-worker heartbeat, native initialization/successful maintenance logs and price metrics |
| API readiness | PASSED: /health/ready, restricted DB and dedicated Redis |
| Frontend/backend target | PASSED: real Vite /api proxy to the configured Python API |
| CORS | PASSED: exact printed frontend origin |
| Storage credentials | PASSED: authenticated local MinIO list-buckets read |
| SMTP | PASSED: real local SMTP NOOP returns 250; no email/account created |
| Repeated up | PASSED: identical owned process ledger; no duplicate processes |
| Restart | PASSED: safe stop/start, data retained and readiness re-established |
| Logs/tail/follow | PASSED against actual API requests |
| Down | PASSED: all recorded owned processes stopped, ledger empty, containers stopped, volumes retained |
| Occupied-port failure | PASSED: an unowned test listener was refused and preserved; startup did not claim readiness |
| Legacy .env isolation | PASSED: synthetic wrong-endpoint/probe .env files were ignored and preserved; Vite client did not contain the probe |
| Synthetic fixture command | PASSED twice: 20-row file created, then preserved; no DB records/paid rights created |
| Tooling regression suite | **28 passed, zero failed/skipped on Windows** |
| Frontend suite | **201 passed, zero failed/skipped** |
| Frontend lint / production build | PASSED |
| npm audit after compatible Vite patch | Zero reported vulnerabilities |
| Browser | PASSED: actual Chrome EN/AR login/signup pages, mobile RTL, public plans 200, readiness proxy 200, owner API 401 and protected-route login redirect; zero page errors |
| Environment reference / Bash syntax | PASSED; source inventory current, shell parsing succeeds |

The three existing non-FORCE exceptions are entitlement_version_state, entitlement_catalog_version and image_generation_jobs. Their original SQL remains unchanged; see DATABASE.md. No security flag was weakened to make startup pass.

## Defects found and resolved

- Original manifests contain an extras-bearing requirement unsuitable as a pip constraint. Tooling derives plain-name constraints from the unchanged source manifests.
- Windows PowerShell 5.1 native stderr could terminate setup under redirection. Native diagnostics are merged/readable and actual exit status is preserved.
- A later exit-code initialization shadowed the native result. Real executable success/failure regression tests now prevent recurrence.
- Windows venv launcher PIDs differ from their runtime child PIDs. Readiness validates current owned descendants' registration/heartbeat.
- A universal FORCE assertion disagreed with the source schema. It now verifies the exact original exceptions, their policies/owners and all other forced tables.
- Fresh npm audit reported the old pinned Vite release. Only the compatible Vite pin/lockfile was updated (8.3.5); audit then reported zero.
- One frontend file failed during the initial unconstrained parallel run and passed alone. All 201 existing assertions passed with file concurrency bounded to two; none were removed.
- The legacy seven-company/18-month fixture generator hit MemoryError on this constrained host. The default seed command now produces at most 20 rows from an existing synthetic fixture; the original generator was not changed.
- Vite normally reads frontend/.env independently. A launcher-only envDir gate prevents accidental old API/provider configuration while preserving ordinary manual Vite behavior.

## Commands and documentation

Use the [root README](../README.md), [local command guide](LOCAL_DEVELOPMENT.md) and [documentation index](README.md).

Commands implemented: setup, up, down, restart, status, logs, doctor, infra, migrate, db-status, db-check, seed and test. Test suites: tooling (default), frontend, database and optional read-only browser. Modes: core/full; full is default.

New shared tooling is in tools/dev; dev.ps1 and dev.sh are thin root wrappers. The existing local keel entry point delegates to the same implementation. Codespaces compatibility and specialist verification evidence are retained.

Current guides cover architecture, backend/frontend, database, workers, integrations, environment variables, troubleshooting and contribution. Historical backend Phase 1 guidance was preserved under docs/archive and labeled; older local/Phase 7 guides now point to the current startup instructions.

## Evidence location and cleanup

Private raw logs, screenshots, native JUnit and JSON checks are retained under the fresh checkout's **.dev/** directory. Useful names:

- frontend-final.log, rls-tests.xml, database-checks.log
- setup-final-verified.log, infra-final-verified.log, migrate-final-verified.log
- core-final-verified.log, full-final-verified.log, restart-final-verified.log
- browser-final-verified.log, status-final-verified.log, down-final-verified.log
- evidence/browser-smoke.json, evidence/infrastructure-protocol-checks.json, evidence/lifecycle-checks.json

No raw private runtime configuration/evidence is committed. The smoke runtime was stopped after testing. Its generated venv was removed after verification to reclaim this host's limited disk; configuration, ownership records, frontend dependencies and evidence are retained. Rerun setup before reusing that disposable checkout.

## Preservation and remaining limitations

- No backend/src, backend/scripts or frontend/src business implementation changed.
- Original Node/React repositories, AI mathematics/workers, financial policy, billing/credits, merchant behavior and applied migrations were preserved.
- The protected integration backend/.env.example SHA256 remains **6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28**.
- No push, protected-main merge, deployment, LIVE Stripe operation or protected DB/service operation occurred.
- No default owner credentials, subscriptions, verified provider prices or merchant connections are generated.
- Seed produces import files; loading uses normal authenticated review/confirmation. It does not silently populate a tenant or bypass entitlements.
- Model libraries/weights, OCR binaries, scraper browser binaries, local inference servers and hosted credentials are explicit feature prerequisites. Missing providers remain unavailable.
- Build retains a bundle-size warning and an ineffective dynamic-import warning. No UI redesign or model rewrite was introduced to suppress them.
- Commercial/privacy/real-provider release gates from the existing integration acceptance remain unchanged; this task certifies developer startup, not production readiness.
