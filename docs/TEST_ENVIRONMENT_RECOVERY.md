# Recover KEEL development and test environments

Start here after a Windows reboot, in a new terminal, or in a new developer/AI session. The repository is sufficient to rebuild the **local environments**; private credentials, model weights and historical external-provider resources are not source code.

Use the checked-out branch/HEAD as the authority. Do not restore old temporary scripts, Docker names, API PIDs or port numbers from a conversation. Baseline for this improvement: `1763216c25c1f59cae3e8ab5da5dc4d1f6deb66b`.

## 1. Prerequisites

- Git, 64-bit CPython 3.11 or 3.12, Node 22.12+ (Node 24 LTS recommended), npm.
- Docker Desktop running **Linux containers** in an authorized local context. Remote contexts are refused; tooling never switches your global context.
- Several GB of free disk/RAM, internet for initial Python/npm installs, images and the pinned MinIO source build. Preserve intentional proxies; a refusing proxy must be resolved through the authorized host/network workflow, never bypassed.
- Chrome/Chromium for browser tests. The runner detects common Windows Chrome installations. Alternatively put `CHROMIUM_PATH=C:\path with spaces\chrome.exe` in private `.dev/integrations.env` after setup. This file is literal data, not a PowerShell script.
- For real OCR tests: Tesseract with English/Arabic language packs, a Unicode font, and the executable on PATH. GitHub's workflow installs Tesseract and DejaVu on Ubuntu. Missing prerequisites are skips, not successful OCR tests.

Do not use the original Node backend, Prisma, production DSNs or personal absolute source paths to initialize the unified app.

## 2. First setup and everyday reboot recovery

Open PowerShell in the repository root:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
.\dev.ps1 setup
.\dev.ps1 up
.\dev.ps1 status
```

`setup` preserves existing configuration/secrets and is safe to repeat. On a previously configured checkout you normally only need to start Docker Desktop, then run `up`. `up` verifies ownership, runs pending forward migrations, checks restricted database login/RLS, and waits for real API/worker/frontend readiness. It does not reuse an unrelated listener.

The default starts all eight supported workers. Use `up --mode core` for forecast, image and commerce connector workers only. Change mode while down. Source changes on an already running checkout require `restart`.

```powershell
.\dev.ps1 doctor
.\dev.ps1 logs --tail 80
.\dev.ps1 restart
.\dev.ps1 down
```

Default frontend/API ports are 5173/8000, but occupied ports are skipped during initial setup. **Use the URLs printed by `up` or ports shown by `doctor`**, not historical 5198/8018, 5204/8024 or 5210/8030 addresses. Root/frontend/backend `.env` files and inherited provider keys are ignored by the isolated launcher. Do not overwrite `backend/.env.example`.

On Linux/macOS the same commands use `bash dev.sh`; those platforms need their own execution verification. Windows PowerShell 5.1 is supported. If policy blocks scripts, follow your organization's approved execution-policy procedure; the equivalent direct command is `python tools/dev/dev.py setup`, then `.dev/venv/Scripts/python.exe tools/dev/dev.py up` on Windows. Do not weaken machine-wide policy.

## 3. What survives a reboot

| State | Location | Recovery |
|---|---|---|
| Checkout/project identity, selected ports and generated local secrets | Private ignored `.dev/config.json` | Keep it with this checkout. `setup` generates it once; never copy it into another checkout. |
| Optional integration settings | Private ignored `.dev/integrations.env` | Load through the launcher; never dot-source, commit or print it. |
| Declared dependencies | `tools/dev/requirements.txt`, both backend manifests, frontend lockfile | `setup`; `setup --models` adds full backend/model libraries. No temporary overlay is required. |
| Normal PostgreSQL/Redis/MinIO data | Labeled checkout-specific Docker volumes | `up` reconnects them. `down` does not delete volumes. |
| Migration state | `schema_migrations` in each DB | Forward runner resumes; no reset or historical migration rewrite. |
| Process identity and source revision | `.dev/processes.json` | Processes must be relaunched. Old pre-boot PIDs are never killed even if Windows reused their numbers. Same-boot identity mismatches are refused. |
| Test DB inventory and results | `.dev/test-databases.json`, `.dev/evidence/tests/<run-id>/` | Inspect locally; test commands create a new DB each time. |
| Test Redis/object data | Test-only tmpfs containers | Intentionally disposable. Each new run starts empty test services. |

Back up private local configuration and any valuable local data through your normal secure backup process. Git alone cannot restore a lost password for an existing volume. Losing `.dev/config.json` is not permission to adopt or reset its old cluster: preserve the volumes and investigate ownership first. A new clone creates a new independent project.

## 4. Recreate isolated tests

Every command below uses the same `dev.ps1` interface. They do not require old API/frontend processes or temporary environment JSON files.

```powershell
# First time, or after dependency manifests change:
.\dev.ps1 setup --models

# Lightweight tooling safety checks:
.\dev.ps1 test

# Fresh DB + repeat migrations + existing native RLS tests:
.\dev.ps1 infra
.\dev.ps1 migrate
.\dev.ps1 test --suite database

# Full backend CI selection, with isolated DB / Redis / object storage:
.\dev.ps1 test --suite backend

# A smaller backend selection, using exactly the same isolation:
.\dev.ps1 test --suite backend --pytest-args src/ai/tests/test_ci_smoke_onboarding_integration_db.py src/ai/tests/test_invoice_rounding_integration_db.py -q

# Frontend tests (bounded concurrency), lint and production build:
.\dev.ps1 test --suite frontend

# Authenticated English desktop / Arabic mobile / dark mobile screen smoke,
# plus the existing English/Arabic assistant presentation checks:
.\dev.ps1 test --suite browser-ci

# Axe audit in those three configurations plus Arabic dark mobile:
.\dev.ps1 test --suite a11y

# pip check + unsuppressed pip-audit of this checkout's installed Python graph:
.\dev.ps1 test --suite audit
```

The backend suite needs `setup --models` because existing test collection imports the declared model libraries. Installing libraries does not automatically download weights or enable live model/provider tests. Missing dependencies fail honestly with logs; no test is substituted or disabled.

`browser-ci` and `a11y` each create a **new synthetic tenant in a fresh test DB**, verify OTP using the existing loopback-only reserved-domain CI fixture (its separate administrative setup connection performs the existing trial bootstrap), save the valid six-step onboarding choices and reuse the normal signup trial. They populate only the repository's synthetic products/competitor observations. No owner promotion, verified commercial rates, Checkout, Stripe object or paid rights are created. They start and stop their own API/frontend processes; you do not need normal `up` first. Assistant/recommendation presentation cases explicitly serve test answers; those cases are not real AI-provider acceptance.

For a non-mutating public-page smoke against your normal running dev environment, use `up`, then `test --suite browser`. It creates no customer account and differs from authenticated `browser-ci`.

### Isolation and service map

| Component | Normal development | Backend / authenticated browser test |
|---|---|---|
| PostgreSQL 17 + pgvector (Docker) | `keel_dev_<checkout-id>` | New `keel_billing_test_dev_<random-id>` in the same **owned local cluster**, never a customer/shared DB. |
| Migration/test admin | Generated `keel_dev_admin` | Can create disposable DBs and apply existing migrations; never used by test API. |
| API/worker role | Restricted `ceopro_app` | Same restricted role/password; workers receive the restricted test DB DSN. Native test fixtures may use the separate admin DSN for fixture DDL. |
| Redis (Docker) | Own persistent instance | Separate `test-redis`, tmpfs, no persistence; destructive test flushes cannot reach normal Redis. |
| MinIO (Docker, existing pinned source Dockerfile) | Own persistent storage | Separate `test-storage`, tmpfs; test bucket cleanup cannot reach normal storage. |
| Mailpit (Docker) | Normal local SMTP/inbox | Authenticated fixture captures only synthetic verification delivery through the existing CI contract; no real mail provider needed. |
| FastAPI, Vite, workers | Native `.dev/venv` Python and Node processes | Browser suites launch native API/Vite preview; backend tests invoke existing workers/fixtures as selected, not independent permanent consumers. |

The `tests` Compose profile is opt-in; normal `up` does not launch test Redis/storage. Test ports are assigned by Docker on loopback and discovered at runtime. Browser API/frontend ports are selected from free loopback ports and recorded in each private `run.json`. Exact source revision, database, status and evidence paths are recorded. A single developer-command lock prevents simultaneous test/stop/migration operations in this checkout.

The test runner excludes inherited/normal integration provider credentials and model opt-ins. Core DB/Redis/storage/URL settings are generated from ownership-checked config. Backend tests use CI's default public frontend origin; the browser runtime uses its own exact origin/CORS/proxy pair. No secret DSN is written into tracked files.

### Database lifecycle

```powershell
.\dev.ps1 db-status
.\dev.ps1 db-check
.\dev.ps1 migrate
```

These three operate on the normal checkout DB. Test suites instead create uniquely named DBs, apply `Final_schema.sql` and all forward migrations, then assert a repeat run applies nothing. Application roles, tenant context, pgvector and existing RLS protections are preserved. The existing schema has three intentional owner-run non-FORCE exceptions; see [database guide](DATABASE.md).

Test DBs are retained for diagnosis, not reused as seeds on the next run. There is deliberately no automatic DROP DATABASE/reset command. Inspect `.dev/test-databases.json` and the corresponding `run.json` before any separately reviewed manual removal; never delete by a guessed prefix alone.

## 5. CI-equivalent local verification

Run `audit`, `backend`, `frontend`, `browser-ci` and `a11y` above. The scripts use the actual [PR workflow](../.github/workflows/pr-checks.yml) contracts, but local Windows success is **not** proof that Ubuntu/Python 3.11/Node 20 GitHub jobs pass. The current local setup requires Node 22.12+ for Vite 8; hosted runtime/version resolution remains a hosted check. Full model, provider and OCR skips remain visible and must not count as passes.

Also run the existing registry/runtime dependency checks used by CI:

```powershell
.\.dev\venv\Scripts\python.exe backend/scripts/validate_application_knowledge.py
npm --prefix frontend audit --omit=dev --audit-level=high
```

The Python audit uses no advisory ignores and does not install arbitrary replacement packages. It freezes the configured checkout venv, excluding the audit tool itself, and audits with the same `--no-deps --disable-pip` flags as CI. Security data needs network access; an unavailable advisory service is a failure, not a green offline audit. Twisted's explicit tested security RC remains in the authoritative manifests; see [CI remediation evidence](CI_REPAIR.md).

## 6. Diagnose, stop and clean up safely

```powershell
.\dev.ps1 doctor
.\dev.ps1 logs --service test-api --tail 80
.\dev.ps1 logs --service test-frontend --tail 80
Get-Content .dev/test-databases.json
Get-ChildItem .dev/evidence/tests

# Stop/remove only the two disposable test containers and owned test processes:
.\dev.ps1 test-cleanup

# Stop all processes/containers owned by this checkout; retain volumes:
.\dev.ps1 down
```

Completed runs and failures after test initialization stop their owned API/frontend and test Redis/storage. A forced kill or failure during initial Docker startup can leave partial owned resources; use `test-cleanup` after inspection. `test-cleanup` additionally removes just the two disposable test containers, preserving PostgreSQL, all volumes, retained test databases, normal dev processes and evidence. It refuses foreign labels or current-boot PID identity mismatches. After a forced shutdown, run it before retrying interrupted tests. Normal `up` can still be used without any old browser process.

| Symptom | Safe response |
|---|---|
| Docker unavailable / Windows containers / remote context | Start Docker Desktop in Linux mode; inspect authorized local context. Do not change global settings blindly. |
| Port occupied | Inspect `doctor`; stop only a proven owned process or choose a free normal port while down. Never kill by port/name. Test ports are dynamically allocated. |
| DB/migration failure | Read the private migration log. Confirm correct checkout/config and image health; no reset/drop/history edit. |
| Wrong Python / missing library | Reopen terminal after installing CPython; run `setup` or `setup --models`. Do not copy another checkout's venv. |
| Browser missing | Install Chrome/Chromium or set literal `CHROMIUM_PATH`; browser checks fail, not skip. |
| CORS/API mismatch | Use printed origins; restart launcher processes. Avoid old fixed-port bookmark evidence. |
| Refusing proxy / blocked package download | Inspect proxy **names/status only**, preserve restrictions; use authorized host access. Never print embedded proxy credentials. |
| `.dev/command.lock` after crash | Inspect its PID and the lock file's age/startup context. Remove only after proving no active command owns it. Never remove an active lock. |
| Lost config / checkout moved | Preserve old volumes/secrets; do not relabel/adopt them. Use a new independent checkout or a separately reviewed recovery. |
| Optional `rembg` / Pillow conflict | Default manifests exclude rembg and require patched Pillow 13. Use a separate clean checkout/venv with default `setup`; preserve an existing opt-in rembg environment. Do not force incompatible dependencies, ignore audit results or uninstall another runtime's packages. |
| Low memory/disk | Use targeted backend selection; existing frontend concurrency is bounded. Do not delete protected data or silently skip tests. |

## 7. Optional environments and limits

- Local sentiment/embeddings/reranking: `setup --models` installs declared libraries; weights still require network/disk. Existing `AI_TEST_EMBEDDINGS`, `AI_TEST_RERANKING`, `AI_TEST_SENTIMENT` gates belong to specialist tests; the safe default runner leaves them off. See [integrations](INTEGRATIONS.md) and existing test module instructions for a separately configured provider/model acceptance run.
- Groq/Tavily/Apify and other hosted AI/search: valid authorized credentials and verified metering/pricing inputs required. No fabricated results or cost data are supplied.
- Shopify/WooCommerce: authorized test store, app/token scopes and tenant connection verification required. Controlled fixture/worker tests are reproducible locally; real-store E2E cannot be reconstructed from Git alone.
- Stripe: TEST MODE account authorization, preserved resource ledger, actual CLI authentication and a fresh listener-specific `whsec_...` are required. A listener must be restarted after reboot with explicit events and the actual webhook route; do not reuse an unrelated/stale signing secret. Use the existing billing acceptance tooling/runbooks and do not recreate old Products/Prices blindly. This task does not authorize another payment run.
- Historical completed Stripe resource IDs, raw screenshots, private run logs and temporary dependency overlays are **evidence**, not startup prerequisites. Preserve them privately when useful, but never make future tests depend on their temp directory existing.

### Existing interactive signup boundary

The existing `db.system_connection()` trial bootstrap requires an administrative setup connection. Giving the CI account fixture only `ceopro_app` reproduced `permission denied for table billing_trials`, leaving the account without a trial; the safe runner now passes the separate test-admin environment to that **fixture process only**, as established by CI. The real browser API remains restricted. No grant, billing rule or application code was changed.

A brand-new interactive signup/trial through the normal restricted-only development API was not certified here. Its system-write authority is a separate application/security concern; do not solve it by granting `ceopro_app` financial-table writes. For this task's authenticated UI testing, use the reproducible isolated browser fixture above.

## 8. Recovery inventory and verification

The previous normal dev workflow was already version controlled (`dev.ps1` / `dev.sh`, `tools/dev`, source MinIO build, migrations). Its one-time `.dev` credentials/ports are intentionally private. The CI repair additionally used `%TEMP%/KEEL/CiRepair-20261027` helper scripts, a dependency overlay, manually supplied test environment JSON, dedicated Redis 56410, API 8030/frontend 5210 and retained test DBs. **None of those machine-specific paths/ports/scripts is required by the new commands.**

Recovery now derives dependencies from manifests, credentials from setup, schema from existing migrations, services from the existing Compose generator and fixture behavior from `scripts.ci_smoke_account`. Native worker dependencies use the same isolated test DB/Redis/storage. Current source and prior evidence remain separate.

Verification results are recorded below before the local checkpoint commit. An actual Windows reboot is not simulated by claiming old processes survived; fresh `powershell.exe -NoProfile -NonInteractive` processes exercise reconstruction without old API/frontend state. Full clean dependency reinstallation and Linux/macOS/hosted execution remain distinct checks.

### Verification recorded on 2026-10-27

| Check | Result |
|---|---|
| Developer/recovery safety tests | **39 passed, zero failed/skipped**, including Windows wrapper exit codes, ownership refusal, reboot PID reuse, separate credentials, provider-key exclusion and normal-process preservation. |
| Fresh PowerShell native recovery | **46 passed, zero failed/skipped**: existing onboarding, invoice, connector worker, native RLS, workflow and actual Twisted/Scrapy checks; run `1ed45b1a1595`. An earlier 37-test run also passed. |
| Database reconstruction | New owned PG cluster and new test DBs; **138 fresh migrations and no-op repeat** passed. pgvector, restricted password login, no superuser/BYPASSRLS and **120 FORCE RLS tables** verified. |
| Authenticated browser reconstruction | **81 screen checks passed** (27 each EN desktop, AR mobile, EN dark mobile), plus EN/AR assistant presentation checks; run `2103fba2d3fc`. New API/frontend processes, exact CORS and real proxy/database reads. |
| Accessibility reconstruction | **Zero findings in all four configurations**, including AR dark mobile and six comparison dialogs each; run `e7f68d978044`. |
| Failure handling | Initial auth fixture with the restricted setup DSN failed honestly and retained evidence (`6f2fa96071db`); corrected to existing admin fixture authority, with a regression preventing admin credentials in the running API. |
| Test-only cleanup and shutdown | Passed from a fresh PowerShell process. Only owned disposable test containers removed; project PostgreSQL stopped. All normal volumes/test databases/evidence retained; owned process ledger empty. |
| Audit recovery command | **FAILED dependency consistency as intended** on the reused developer venv: optional `rembg 2.0.85` requires `Pillow<13`, but the security overlay contains Pillow 13. No exception/suppression/uninstall was applied. `pip-audit` did not execute after this prerequisite failure. Evidence: `.dev/evidence/audit/55b1d055ca24/pip-check.log`. |
| Full clean install / actual reboot / other OS | **UNRUN in this task**. No fresh full ML dependency installation, OS reboot or Linux/macOS/hosted run was claimed. Prior normal startup/CI evidence remains in its existing reports. |

These fresh `powershell.exe -NoProfile -NonInteractive` checks reused existing installed Python libraries and the prior CI security overlay through a private verification adapter, rather than reinstalling ML packages. Browser builds used this checkout's existing Vite 8.2.2 installation; a fresh documented `setup` uses the lockfile's Vite 8.3.5. This is orchestration/recovery evidence, not a new certification of a clean dependency resolution. The adapter and overlay are **not referenced by any shipped recovery command**. The temporary verification dependency marker was removed: this checkout still needs normal `setup` to create its own `.dev/venv`.

The previous 171-package zero-advisory result in `CI_REPAIR.md` is historical evidence and is not substituted for the failed current consistency check. A positive default-environment audit must be rerun after the documented clean setup. The default repository manifests exclude optional rembg; this task does not change that extra's financial/model/security policy or modify its installed environment.

Remaining manual prerequisites are installation/network access, Docker Desktop startup, Chrome, optional OCR binaries/fonts, provider authorization/credentials and model downloads. Essential local infrastructure and test fixtures are now version-controlled; fully automated real merchant/Stripe/model acceptance is not claimed. The interactive normal-development trial-bootstrap limitation above remains separate from the passing isolated fixture workflow.

Only developer tooling, its tests, the focused CI test step and documentation changed. No application source, migrations, original Node/React repository, protected runtime or production data was modified. Protected `backend/.env.example` SHA256 remains `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28`. No push, merge into main or deployment occurred.
