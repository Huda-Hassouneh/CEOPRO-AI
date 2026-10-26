# KEEL React frontend

React 19, Vite 8, React Router, TanStack Query and Zustand. The browser talks only to Python through feature API adapters and `src/shared/lib/httpClient.js`.

## Development

From the repository root: `dev.ps1 setup`, then `dev.ps1 up` (Unix: `bash dev.sh`). The launcher uses `VITE_API_BASE_URL=/api` and the existing Vite proxy with an exact backend target. Do not point the new UI at an older API because its health endpoint returns 200.

Within this directory, normal scripts remain:

```text
npm run dev
npm test
npm run lint
npm run build
npm run test:browser
```

Direct `npm run dev` needs your intended `VITE_API_BASE_URL` / `KEEL_API_PROXY_TARGET` environment; it does not inherit launcher configuration automatically. Avoid a second server on the same port.

## Structure and conventions

Feature folders under `src/` own pages/components, hooks and API adapters. Routing and layouts preserve customer/onboarding and Platform Owner boundaries. Authentication state follows the existing Python session contracts; server authorization remains mandatory even when a route guard hides a page.

Feature availability comes from actual entitlements/capabilities, not hardcoded plan assumptions. Loading, empty, unavailable and error states must be truthful. Never use production mock records to conceal a missing API.

Design tokens/materials live in `src/styles/apex-theme.css` and `src/styles/keel-glass.css`. Preserve original migrated React components and interaction patterns; avoid redesigning a feature during API adaptation.

Translations are `src/assets/locales/en.json` and `ar.json`. Preserve UTF-8, key parity, accessible labels and RTL direction. Check Arabic on narrow screens after layout changes.

## Tests

Root `dev.ps1 test --suite frontend` runs Node component/contract tests, ESLint and the production build. Browser scripts under `tests/browser/` need an installed Chromium, explicit runtime URLs and authorized synthetic accounts. Some tests mutate business/quote data; read their scope before execution.

No privileged test account or fabricated financial data is injected by startup. Use Mailpit for real local signup OTP. See [local debugging](../docs/LOCAL_DEVELOPMENT.md) and [integration limitations](../docs/INTEGRATIONS.md).
