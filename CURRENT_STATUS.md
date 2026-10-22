# KEEL - current status

Last updated 2026-10-08. Earlier session logs are in `docs/archive/`.

## Finished and verified

Everything below runs on real data through the real API; nothing is mocked
or simulated.

- **Product:** Command Center, Products and Sales (with product detail),
  Demand forecasts, Pricing, Competitors (discovery, tracking, leaderboard,
  trends, search area, sources to review), Marketing campaign builder,
  Assistant (company data and documents, with sources), Reports (CSV/JSON
  export of the full period, printable PDF in English or Arabic, paginated
  sales report), Data & Documents (uploads, database and
  API connectors, reviews), Alerts, Settings (profile, company, team,
  notifications, preferences, security, data export, company deletion),
  Billing (plans, usage, Stripe checkout), sign-up, sign-in, password reset,
  invitations, company setup wizard, several companies per sign-in, legal
  pages and a real 404 page.
- **Brand and design:** the product is KEEL everywhere a customer can see it.
  The glass design system (`frontend/src/styles/keel-glass.css` on the tokens
  in `apex-theme.css`) covers every screen, light and dark, English and
  Arabic (right to left), desktop and mobile.
- **Competitor discovery:** OpenStreetMap (no key needed), Google Places,
  web search (Google Programmable Search or SearXNG) and Apify; merged,
  de-duplicated, scored for relevance and confidence, with provenance per
  source. Competitors' own websites are read (robots.txt respected) for
  business type, description and social profiles. Discovery re-runs on its
  own every 7 days for companies that use it.
- **Competitor comments:** public YouTube comments (with likes) and Google
  reviews about each tracked competitor, filtered for noise, grouped into
  themes (service, waiting time, price, quality...), with sentiment, "an
  opportunity / a strength to match" markers, a link to the original and
  "noted / acted on" marks. Comments are kept 30 days and refreshed weekly by
  the enrichment worker within a daily YouTube search budget; a competitor
  whose recent comments turn mostly negative raises an alert. Where something
  is missing the screen says why and who can fix it (needs
  `YOUTUBE_API_KEY` and `EXTERNAL_COMMENTS_APPROVAL_REFERENCE`; see
  `backend/COMPETITOR_COMMENTS_AND_RETRY_PLAN.md`).
- **Sessions:** a sign-in stays alive while it's being used - the app
  renews its 2-hour access token in the background (`POST /auth/refresh`),
  an untouched tab signs out after 2 hours, and every sign-in ends after
  7 days at most (`JWT_EXPIRE_MINUTES`, `SESSION_MAX_HOURS`).
- **Email confirmation:** sign-up sends a 6-digit code; once email delivery
  is configured, the app can't be used until the address is confirmed
  (`REQUIRE_EMAIL_VERIFICATION=auto`). Accepting an invitation or resetting
  a password also confirms it.
- **Notifications:** each person chooses which alert groups (stock,
  pricing, market, data, billing) show in the app's alert bell and which go
  into an email summary, sent daily or weekly at 07:00 company time when
  there is something new, only to verified addresses (Settings ->
  Notifications; `NOTIFICATION_DIGEST_ENABLED`, `NOTIFICATION_DIGEST_HOUR`).
- **Rate limits:** every API request counts against a per-minute budget -
  600 per signed-in company, 120 per anonymous address (429 with
  Retry-After beyond that) - on top of the sign-in and assistant limits.
- **Isolation:** every company's data is separated by Postgres row-level
  security through a restricted database role; cross-company tests pass.
- **Automatic checks on every pull request** (`.github/workflows/pr-checks.yml`):
  backend tests with a live database and Redis, frontend lint, unit tests
  and build, and the browser smoke test of every screen in English desktop,
  Arabic mobile and dark mode against a freshly set-up company.
- **Running it:** `./keel setup`, `./keel start`, `./keel seed`, `./keel test`
  locally or in a Codespace (`RUNNING_LOCALLY.md`).

- **AI provider fallback and marketing image gallery (2026-10-22):** `LLM_PROVIDERS` lets the assistant and
  campaign writing fall back to the next configured model (for example Groq, then a local llama-server);
  Marketing images come in five formats (1:1, 4:5, 9:16, 16:9, 1.91:1), can come from a self-hosted image
  server, and every image is kept in the campaign's gallery to attach, label, download or delete. See
  `docs/AI_MODEL_MARKETING_IMPLEMENTATION.md`.

## Verification (latest run)

| Check | Result |
|---|---|
| Backend tests, including live-database tests | 2096 passed, 34 skipped (need external services), 0 failed |
| Frontend unit tests (including English/Arabic translation consistency) | 58 passed, 0 failed |
| Lint (frontend) | clean |
| Production build | passes; initial JavaScript 375 kB (116 kB gzipped) |
| Browser smoke test, every screen (English desktop, Arabic mobile, dark) | 26/26 clean in each |
| Button audit: every visible button on 11 screens | no dead buttons |
| New customer end to end (sign-up → setup → every screen) | no errors; empty states on every screen |
| Mobile Arabic and dark mode screenshots of every main screen | reviewed |
| Accessibility audit (axe-core, WCAG 2.1 AA), every screen, English desktop / Arabic mobile / dark | 0 findings |
| Load test (`backend/scripts/load_test.py`): one API process, pool of 10, 7 demo companies, 90 s each | 35 users: 0 errors, 57 req/s, slowest endpoint p95 0.65 s · 70 users: 1 error in 6,900, p95 1.2 s · 140 users: saturated, p95 about 6 s |

## Needs an account or key (not code)

These features are built and tested; each starts working as soon as its
setting is filled in (`backend/.env` locally, the Render dashboard on
staging). Values are never committed.

| Feature | Setting | Without it |
|---|---|---|
| Online payments | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Billing shows plans and usage; checkout says payments aren't switched on |
| Emails (sign-up codes, password reset, invitations, alert summaries) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS` (a verified sender) | Codes are written to the backend log |
| AI assistant and marketing copy | `GROQ_API_KEY` | The assistant says it is unavailable |
| Error tracking (crash reports for the API, workers and browser app) | `SENTRY_DSN` (API and workers), `VITE_SENTRY_DSN` (frontend build) | Errors only go to the server logs |
| Uptime alerts | an uptime monitor account pointed at `/health/ready` | No one is alerted when the service is down |
| More competitor sources | `GOOGLE_PLACES_API_KEY`, `GOOGLE_CUSTOM_SEARCH_API_KEY` + `GOOGLE_CUSTOM_SEARCH_CX`, `APIFY_API_TOKEN`, or `SEARXNG_INSTANCE_URL` | OpenStreetMap only |
| Paid AI and data providers (Groq, Google, Apify, Hugging Face, search APIs) | A confirmed price per provider, recorded with `python -m scripts.billing_admin set-price` (not an environment setting) | The call is refused ("not set up"): no paid call runs without a price to charge Data or AI Credits against. See `docs/SUBSCRIPTIONS_AND_CREDITS.md` |

## Decisions pending

- **Subscription budgets:** Standard / Plus / Pro / Custom with Data and AI
  Credits are in place (`docs/SUBSCRIPTIONS_AND_CREDITS.md`). The credit
  budgets come from a cost model whose processing-fee, split and
  infrastructure figures are planning assumptions to replace with real
  numbers; provider prices must be confirmed before paid features run.

- **Logo colours:** the approved symbol (hull, keel and bulb) and the
  Cormorant Garamond wordmark are in the app, favicon, app icons and link
  preview, in the blue & purple palette that matches the app. To use gray &
  silver instead, change the `--keel-logo-*` tokens in
  `frontend/src/styles/apex-theme.css` and the colours in
  `frontend/public/favicon.svg`, then run `node scripts/render-icons.mjs`.
  Emails are plain text and carry no logo.
- **Background workers on staging:** `render.yaml` now runs all five
  market workers as one service (`keel-workers-staging`), which needs a
  paid Render plan (standard, 2 GB). See STAGING_DEPLOYMENT.md.
- **Render services** were renamed to `keel-*` in `render.yaml`; the next
  Blueprint sync creates them as new services, and the old `ceopro-*`
  services can then be removed.

## Known limits

- **Checked live from the development environment (2026-10-09):** the Groq
  assistant (`scripts/live_llm_verification.py` passes; real answers on
  the demo data in English and Jordanian Arabic match the database), and
  uploads through an S3-compatible store (CSV import and PDF document).
- **Not yet checked live** (the sandbox blocks these hosts, so they are
  covered only by tests built on the services' real response formats):
  OpenStreetMap, Google Places and search, Apify, reading competitor
  websites, Stripe, SMTP, real MinIO / Cloudflare R2, downloading the
  sentiment, embedding and reranking models from Hugging Face (the code
  was run against small locally built models on the current library
  versions), and building the Docker images. Each needs one run on
  staging.
- **Checked on real models in CI (2026-10-17, `rag-runtime-check.yml`):**
  embedding and re-ranking models download and load from Hugging Face;
  semantic retrieval finds an English document for an Arabic question
  with no shared word (keyword search finds nothing); memory per setting
  is in STAGING_DEPLOYMENT.md. Apify's Google Maps actor was run once
  through the real discovery pipeline into a test database (one place,
  parsed and stored, run recorded as ok) - not yet on staging.
- `keel-ai-staging` (512 MB free plan) runs semantic search with a static
  multilingual embedding model inside the ai process
  (`RAG_EMBEDDING_BACKEND=static`; no torch, no external embedding
  service). Verified in CI against the running API
  (`rag-runtime-check.yml`, job `app-e2e`): PDF upload, stored vectors,
  Arabic questions citing the right English document, company records,
  tenant isolation, and peak memory 359 MB. Not yet verified on Render
  itself (this sandbox can't reach Render). Accuracy is below the
  transformer models; `onnx` on a 2 GB plan is better. With
  `RAG_EMBEDDING_BACKEND=none`, documents are found by keyword search only.
- A free Groq key limits how many assistant questions can be answered per
  minute across all companies: under load, answers wait for the limit
  (seen as 9-16 s replies).
- A follow-up question that doesn't name the product ("what is its
  price?") is sometimes answered with "not in the data" (1 of 3 live
  runs), because the earlier turn's product isn't always found again.
