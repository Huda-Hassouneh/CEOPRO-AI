# Frontend

React/Vite application for merchant and platform workspaces. `src/app/` contains application setup/routes; `src/features/` groups domain screens and API hooks; `src/shared/` contains reusable UI, configuration, API helpers and translations. Existing design tokens/components should be reused for new pages.

Authentication uses the Node API and existing session handling. Permission/entitlement-aware navigation is presentation, not a substitute for backend authorization. Merchant flows include onboarding, data connections, products, competitor review, analytics, forecasts, pricing, documents/RAG, business recommendations and Smart Alerts. Platform routes require verified staff access.

State is split across feature hooks, React query/cache utilities and shared stores (including Zustand). Follow the existing feature's API/state pattern before adding another cache. API configuration is public `VITE_API_BASE_URL`; all VITE values enter the client bundle. VITE_WS_URL is an optional client endpoint; this repository does not start a corresponding Node WebSocket server. Preview/mock auth/UI modes are isolated development tools and must remain disabled for normal integration/production testing.

English and Arabic dictionaries are under `src/assets/locales/` (with feature-local dictionaries where present). Use dictionary keys for visible text, preserve interpolation placeholders and test both locales/RTL. The recently completed Connect Data translations remain in this handoff.

```powershell
# From frontend:
npm.cmd ci
npm.cmd run dev
npm.cmd run verify:i18n
npm.cmd run test:i18n:render
npm.cmd run test:connected-data-sources
npm.cmd run test:sales-import
npm.cmd run build
```

Vite uses port 5173; configure Node CORS to the actual origin. Restart Vite after env edits. Production build emits `dist/`; serve it over HTTPS with an SPA route fallback and the intended API origin. Browser integration/E2E suites live in backend as well; they require running services, seeded test identities where specified and sometimes external providers. A successful static translation/build check does not establish live service availability.
