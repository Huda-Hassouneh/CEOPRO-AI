# KEEL frontend

React + Vite + TanStack Query. Talks only to the KEEL backend API (`VITE_API_BASE_URL`).

- Run everything from the repository root with `./keel start` (see `RUNNING_LOCALLY.md`).
- Frontend only: `npm run dev`, `npm run build`, `npm test`, `npx eslint src tests`.
- Browser smoke test across every screen: `E2E_EMAIL=… E2E_PASSWORD=… node tests/browser/smoke.mjs`.
- Design system: `src/styles/apex-theme.css` (tokens, light and dark) and `src/styles/keel-glass.css` (the glass material).
- Translations: `src/assets/locales/en.json` and `ar.json` (Arabic is right-to-left).
