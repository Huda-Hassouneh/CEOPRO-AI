> Current fresh-clone startup: [root developer commands](../../docs/LOCAL_DEVELOPMENT.md). The guide below describes the earlier specialist/WSL workflow and historical evidence; its fixed ports and recorded migration counts are not the new default.

# Reusable KEEL local verification environment

This harness is for synthetic local verification only. It is not the normal KEEL development stack and never points at a shared or production database. Migrations 1-103 are applied only to the dedicated `keel_verification` database in the `keel-verification-postgres` container.

## First use / start

From this directory in PowerShell:

```powershell
.\Initialize.ps1
.\Install-Python.ps1   # first use only; installs focused Python/test dependencies, no model weights
.\Reset-Database.ps1   # fresh test data and the current migration chain
```

`Initialize.ps1` creates synthetic credentials outside Git in `%LOCALAPPDATA%\KEEL\verification\compose.env`, restricts that file to the current user and SYSTEM, creates/reuses one Python virtual environment there, and starts the persistent PostgreSQL 17/pgvector and Redis 7.4.11 containers. It also starts the optional MinIO service from the existing locally available `keel-minio-rag:local` image. Secrets are loaded into the calling PowerShell process only and are never printed. The Docker volumes and venv persist between tasks.

The database is intentionally separate from development services. Redis is volatile; tests should use unique keys or flush only the dedicated Redis service. MinIO tests should use a per-test bucket/prefix; the named MinIO volume persists.

## Common commands

```powershell
.\Initialize.ps1                         # start/reuse services and venv; process-scoped env
.\Reset-Database.ps1                    # drop/recreate only keel_verification and reapply migrations
.\Test-Backend.ps1 src/market_scraper/tests/test_competitor_enrichment.py
.\Test-Backend.ps1 src/ai/tests/test_rls_integration_db.py
.\Test-Frontend.ps1                     # Node tests, ESLint, Vite build
.\Serve-Backend.ps1                     # run full FastAPI against the dedicated test DB/Redis/MinIO
.\Serve-Frontend.ps1                    # run Vite on 127.0.0.1:5178 (strict port)
.\Prepare-BrowserFixture.ps1            # synthetic verified owner plus product, competitor and price
.\Test-Browser.ps1                      # authenticated Chromium, English desktop + Arabic mobile RTL
.\Test-Browser.ps1 -IncludeNotifications # persisted failed-import notification, deduplication, read/dismiss/history and tenant isolation
.\Test-Browser.ps1 -IncludeDataImport   # also runs the existing CSV import -> canonical -> Dashboard journey
.\Test-Browser.ps1 -IncludeProducts     # Owner CRUD/stock, staff direct-API denial, cross-tenant product denial
.\Test-HandoffBrowser.ps1                # Shopify/Woo form validation + Marketing capability/RTL, no provider calls
.\Test-MigrationUpgrade.ps1             # populated disposable upgrade 1-102 -> 103, rerun check
.\Stop.ps1                              # stop containers, preserve volumes and venv
```

The authenticated Pricing Recommendations and Market Perception browser contracts can run against the already-started FastAPI/Vite services with Chromium and the synthetic fixture in `%LOCALAPPDATA%\KEEL\verification\competitor-browser-fixture.json`. Their scripts are `frontend/tests/browser/pricing-recommendations.mjs` and `frontend/tests/browser/market-perception.mjs`; set `APP_URL`, `API_URL`, `CHROMIUM_PATH`, `E2E_EMAIL`, `E2E_PASSWORD`, `E2E_PRODUCT_MARKER`, and `E2E_LOCALE` from that fixture. They write only synthetic recommendation/review evidence in `keel_verification`.

Run `Initialize.ps1` and `Install-Python.ps1` once per workstation. `Reset-Database.ps1` resets only the dedicated `keel_verification` database and reapplies all 103 current migrations; use it when test data must start clean. `Test-MigrationUpgrade.ps1` creates a uniquely named temporary database inside the task-owned container, populates it after migration 102, applies migration 103, checks retained tenant/plan/product records and idempotency, then drops only its generated database. Browser fixture JSON (including its synthetic login password) is stored outside the repository with current-user-only ACLs. The backend/frontend servers run in separate PowerShell terminals and stop with Ctrl+C. Use only the `DATABASE_URL`/`AI_TEST_DATABASE_URL` injected by the scripts. Never substitute a developer `.env` URL.

## Phase 7 browser coverage

The platform Owner/Admin browser lifecycle/search is exercised by backend/scripts/auth_browser_verification.py. It requires the local test-only SMTP dependency (aiosmtpd, installed by Install-Python.ps1) and a separate localhost BILLING_TEST_DATABASE_URL named keel_billing_test or keel_billing_test_<suffix>; its validator refuses the shared keel_verification database. It starts its own current-source API and Vite processes and uses synthetic identities and a local SMTP capture.

Test-HandoffBrowser.ps1 checks Shopify/Woo form validation and reads the authenticated Marketing options API in English/Arabic RTL. It does not submit credentials or call providers. Full store connect/sync and image gallery generation require approved test-provider configuration and are not certified by this smoke.

## Scope

The Python venv intentionally does not install `torch`, `transformers`, sentence-transformers, or download model weights. Install a model runtime only for a task that explicitly requires it and after checking free disk space. Node dependencies and the Chromium browser are reused from the repository/user Playwright installation; this harness does not install another browser copy.
