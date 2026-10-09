# CEOPRO frontend — UI testing mode

Use this mode to inspect the visual frontend without logging in or subscribing to specific features. It **does not** create an authenticated session, weaken PostgreSQL RLS, change tenant entitlements, or authorize protected backend requests.

## Run locally (Windows PowerShell)

From the extracted frontend directory:

```powershell
npm ci
npm run dev:ui-test
```

Open the Vite URL printed in the console (normally `http://localhost:5173`). Use the dark **UI TESTING** navigation bar at the bottom to open customer pages, billing, Platform Admin and onboarding. All frontend feature gates and sidebar locks are disabled in this mode. The Platform Admin screens use the repository's fictional local preview adapter; the plan catalog also uses **fictional, explicitly labelled preview prices** (not authoritative Stripe pricing). Common backend-driven pages now use **local fictional fixtures**, not protected HTTP calls: dashboard KPIs and charts; forecasting overview, list and product details; market intelligence, competitors and competitor details; data connections; RAG document list and clearly simulated chat; a sample billing subscription and usage; and platform-admin preview. The previously blurred market trend/opportunities/leaderboard previews are visible in UI testing mode. Some unfinished placeholder pages or actions can still be blank or unavailable; this does **not** implement missing production features.

This mode redirects all shared Axios GET requests to explicit local fixtures, without network access. Missing fixtures fail with `UI_TESTING_FIXTURE_MISSING` instead of silently accessing the backend. This mode is **read-only** for HTTP mutations through the shared Axios client. Payments, imports and changes cannot be submitted from this preview, and other API clients may still receive 401/403 from the server. To test real data, mutations, tenant isolation or end-to-end workflows, use the standard authenticated development mode with the real test database and entitlement fixtures.

## Standard development / production

`npm run dev` uses the existing environment (usually `.env`); testing mode defaults to `false` unless enabled explicitly. `npm run dev:ui-test` sets the flag via `.env.ui-testing`. The implementation also requires `import.meta.env.DEV === true`: in a production `npm run build`, the preview bypass is disabled regardless of an environment variable.

Turn off testing by closing the UI testing Vite process and launching `npm run dev` with `VITE_ENABLE_UI_TESTING_MODE=false` in your `.env` (or remove that variable). Local preview does not affect server-side authentication or RLS.

## Scope and changes

- `src/shared/config/uiTestingMode.js`: single dev-only flag
- `src/app/router/{ProtectedRoute,RoleGuard,OnboardingGuard}.jsx`: local visual navigation
- `src/features/billing/components/{FeatureGate,FeatureRouteGuard}.jsx` and `hooks/useEntitlements.js`: no frontend entitlement locks
- `src/shared/components/layout/Sidebar.jsx`: show all menu items
- `src/features/platform-admin/api/{platformAdminApi,platformBillingApi}.js`: local preview admin data instead of auth-protected API calls
- `src/features/billing/api/{billingApi,uiTestingBillingData}.js`: local fictional plans for visual comparisons
- `src/shared/lib/httpClient.js` + `src/shared/preview/uiPreviewApi.js`: route GETs to local sample responses, block all backend mutations and reject unknown preview routes
- `src/shared/components/layout/UiTestingToolbar.jsx`: labelled quick navigation

**Not a security bypass:** Backend endpoints, Stripe, and Prisma permissions stay unchanged. Never deploy the Vite dev server as your production frontend.

## What testing mode does not mean

The sample data are fictional: they do not represent real company sales, forecasts, subscriptions, Stripe prices, AI answers, RLS behavior, or import status. Their "verified" status fields are fixture UI examples, **not verification of real data**. Do not use this mode for backend/AI integration or permission E2E tests. Unimplemented placeholder screens remain unimplemented rather than claiming production capability.

## Checks performed in the editing environment

- `npm run test:ui-preview`: 12 passed (including 7 fixture and safety checks)
- Combined focused suites: 24 passed
- `npm run verify:entitlements`: passed
- `npm run verify:subscription`: passed
- All modified JavaScript/JSX files passed a TypeScript syntax-parser check.
- Full `npm run build` and live browser checks were **not run**, because the NPM dependencies needed for Vite are absent in the editing environment. Run `npm ci`, `npm run build` and a browser smoke check on your machine before merging.
- The separate existing `tests/auth-email-verification.test.mjs` suite showed two assertions failing. The tested email-verification files were not changed in this patch.
