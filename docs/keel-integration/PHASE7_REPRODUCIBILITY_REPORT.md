# Phase 7 reproducibility and browser verification report

**Run date:** 2026-10-23
**Starting revision:** 032d200e27937df12d339c5a3e2edbd1a728f600 on integration/keel-full-migration
**Migration chain:** 103 files
**Scope:** reproducibility/docs plus the three browser gaps carried from Phase 6. No business logic or migrations changed.

## Commands and evidence

The persistent verification environment in tools/keel-verification was reused. C: had 24.33 GB free before starting. PostgreSQL 17/pgvector, Redis and MinIO containers were already running and healthy.

1. Initialize.ps1 reused the existing containers and virtual environment. Prepare-BrowserFixture.ps1 seeded its synthetic tenant and credentials outside Git. A first attempt to prepare the fixture before FastAPI was running failed with connection refused; the correct current-source API was then started with Serve-Backend.ps1 and Vite with Serve-Frontend.ps1.
2. Test-Browser.ps1 completed its competitor and Market Intelligence smoke in English desktop and Arabic mobile RTL. These were supporting checks; broader feature journeys and full Phase 6 counts are in PHASE6_INTEGRATED_ACCEPTANCE_REPORT.md.
3. The existing backend/scripts/auth_browser_verification.py initially could not import aiosmtpd. The reusable Install-Python.ps1 now declares aiosmtpd>=1.4,<2; version 1.4.6 was installed into the existing local verification venv. Its safety validator rejected keel_verification and a nonconforming DB name, as designed. A task-owned local DB was created, all 103 tracked migrations applied, and it was named keel_billing_test_phase7 to meet the explicit test-target allowlist. The harness ran its own current-source FastAPI/Vite and local SMTP capture.
4. Platform/authenticated browser result: **26 passed, 0 failed, 0 skipped**. Evidence included signup/session, tenant-owner platform denial, workspace operations, Owner invitation, Admin acceptance and owner-only controls, invitation replay/expiry, operator directory, later-page company/user search, filtered counts, company detail and Arabic RTL.
5. Test-HandoffBrowser.ps1 ran against current persistent FastAPI/Vite and synthetic tenant: **9 assertions passed in 3 scenarios**. Shopify invalid host was rejected and valid myshopify domain enabled OAuth; Woo required credentials and accepted only format-shaped synthetic values; Marketing read authenticated /marketing/options and rendered at 390px Arabic RTL without overflow. It did not submit store credentials or trigger providers.
6. The new browser harness passed targeted ESLint and Node syntax validation. Full UI suite/build was not rerun because frontend production code and dependencies were unchanged.
7. The task-owned keel_billing_test_phase7 database was created solely for the platform run and removed after completion. Persistent verification containers, keel_verification DB, venv, Node packages, Chromium and volumes were retained.

The platform test used DATABASE_URL and BILLING_TEST_DATABASE_URL pointing to the dedicated disposable DB. No credentials were written or printed. External provider keys remained unset.

## Three browser gaps

| Phase 6 gap | Phase 7 result |
|---|---|
| Platform operator browser management | **PASS.** Full platform Owner/Admin lifecycle, invitation, directory search/pagination, role separation and Arabic RTL ran as above. |
| Shopify/Woo frontend connections | **PARTIAL.** Browser verified forms and client validation. OAuth/store API connection, sync, staging review and promotion were not run because no authorized test merchant/OAuth app credentials were configured. |
| Marketing image gallery | **PARTIAL.** Authenticated page, live options API and Arabic mobile layout were checked. Full campaign/image generation and gallery lifecycle were not run because no configured authorized text/image provider was available. No keyless external image call was made. |

## Configuration and fresh-clone findings

backend/.env.example already contains backend application, DB/role, Redis, MinIO, auth, CORS/email, billing, provider, model, image, worker and operations settings. frontend/.env.example contains VITE_API_BASE_URL, optional Spline/Sentry settings, and optional VITE_SUPPORT_EMAIL/VITE_SENTRY_RELEASE. The templates were completed with code-backed Shopify OAuth and frontend support/release variables; no credentials or app behavior were changed. Provider settings remain optional and follow existing service disable/unavailable behavior.

A full fresh clone with a newly installed venv and Docker images was **not run**. A clean tracked-source export at the final commit verified 17 required guide/script/template paths, all root README links, and absence of ignored backend/.env and frontend/.env files. The reusable scripts were used without duplicating existing services. Fresh-source dependency provisioning should still be completed by a teammate on their target machine. Full local setup is WSL Bash through ./keel setup; PowerShell focused verification uses tools/keel-verification scripts.

## Git and release boundary

At verification start, worktree was clean at 032d200e27937df12d339c5a3e2edbd1a728f600. Local origin/main points to already-merged 041f9f24a6a32d8d03d934a3f89b6b3734eecadb; Phase 7 did not fetch newer main. No Node, teammate-main or Phase 1A worktree changes occurred. No migration 104+, push, PR, merge or deployment occurred.

Phase 6 local integration acceptance remains PASS for exercised workflows/fixtures. Production readiness remains BLOCKED/CONDITIONAL on owner decisions and live-provider certification; this is not release approval.
