# KEEL: current status

**Last updated:** 2026-10-07
**Code on `main`:** commit `cf4683f`, the merge of PR #15 ("First-customer readiness: full acceptance pass fixes")
**Work in progress:** branch `uat/first-customer-readiness`. Any open pull request from that branch holds the newest changes, and this file is updated with each of them.
**How to run it yourself:** see `RUNNING_LOCALLY.md`

This file is the single place to see what is finished, what remains and what
is limited. It says plainly when something could not be verified.

---

## Verified on `main` (`cf4683f`)

Tested against a real stack (Postgres + pgvector with row-level security,
Redis, MinIO, and the real Groq LLM). The tests used seven seeded demo
companies with 18 months of data, plus throwaway companies in the US (USD),
Japan (JPY) and Kuwait (KWD). Testing covered the API and a real browser, in
Arabic and English, on desktop and phone.

| Area | State |
|---|---|
| Sign-up, sign-in, team, settings | Works. Password rules are enforced by the server. Reset and verification codes are tied to the account. Wrong codes and failed sign-ins are rate-limited. |
| Company isolation | Verified: every ID-based endpoint returns 404 when one company tries to read or change another company's data. |
| Products | Sold by unit, weight, length, volume or time; services have no stock; prices use each currency's own decimals. |
| Sales imports | Real-world CSV and Excel exports work: legacy encodings, `;` separators, Excel dates, Arabic and French headers. Imports record what customers actually paid and skip rows already imported. A 140,000-row Excel file imports in about 2 minutes. |
| Dashboard | Revenue, units and the daily trend match independently computed ground truth (the demo verifier reports 0 failing checks). |
| Forecasting | "Demand over the next 30 days" per product, including slow and intermittent sellers, with restock and reduce advice. |
| Pricing | Recommendations come from competitor prices from the last 30 days, with price-change and margin guardrails. The explanation is shown in the interface language. |
| Competitors | Add or track competitors, record their prices, and view the tier, profile, activity timeline and price comparison. |
| Customer reviews | CSV and Excel import with sentiment analysis. The model agrees with the star rating about 93% of the time. |
| AI assistant (RAG) | Answers from the company's uploaded documents and live business data (sales, top products, competitors, forecasts) in Arabic, English or French, keeps the conversation context, and never shows another company's data. |
| Marketing | Campaign text generation works. Background removal (rembg) works on a real product photo when enabled. |
| Security | Office "zip bombs" are rejected, broken files are rejected with a clear message, disguised file types are blocked, provider errors are never shown to users, and API security headers are set. |
| Mobile and RTL | No sideways scrolling on 390 px phones; Arabic layout is right-to-left throughout. |
| Tests | Backend: 1821 passed. Frontend: 43 passed. The production build succeeds. CI is green. |

---

## In progress (next pull request)

1. **Assistant as a product guide.** It should explain how to do things in
   KEEL ("how do I add a product / upload sales / create a campaign"),
   based only on the screens and buttons that actually exist.
2. **Assistant as a business analyst.** It should answer growth, decline,
   restock, competitor overlap, market and public-activity questions from the
   company's data and KEEL's calculations, and say where each answer comes
   from.
3. **Research fallback.** When internal data can't answer, it should run a
   clearly labelled, sourced web search, or say plainly that search is
   unavailable.
4. **Subscription usage, kept separate from technical limits.**
   - Measure usage per company: AI questions, searches, documents and storage.
   - Let each plan set those limits.
   - A provider's rate limit must never turn the assistant off for everyone.
   - The 20 MB per-document limit stays as a technical safety limit only.
5. **Arabic product names.** Show a product's Arabic name in the Arabic
   interface when one exists. Today the English name is shown.
6. **AI image generation.** Verify the full workflow and confirm that one
   company can never see another company's campaign images.
7. **Social and competitor public activity.** Provide a reproducible way to
   verify it, and state its limits clearly.
8. **Visual consistency.** Review every screen (desktop and phone, Arabic and
   English) for consistent spacing, typography, buttons, cards, tables and the
   empty, loading and error states.

---

## Known limitations

- **Outbound internet is blocked in the development sandbox used so far.**
  Competitor discovery (Google Places, web search or SearXNG), social
  cross-checks, AI image generation and web-search fallback could not be
  verified end to end there. These features need their provider keys, or
  SearXNG, configured on a deployment with internet access. When they are not
  configured, the app says "not configured" instead of failing.
- **AI capacity is set by the Groq account.** A free Groq key allows about
  8,000 tokens per minute, roughly two assistant questions per minute across
  all customers. When the limit is reached, the assistant waits or tells the
  user how long to wait; it doesn't fail silently.
- **Sentiment and Levantine Arabic.** The sentiment model mislabels some
  Levantine-dialect complaints as positive. `backend/src/ai/sentiment/finetune.py`
  exists to improve this with labelled data.
- **Background removal is off by default.** Enable it with
  `MARKETING_BACKGROUND_REMOVAL_PROVIDER=rembg`; the model takes about 200 MB
  of memory.

---

## History

| Commit / PR | What it delivered |
|---|---|
| `cf4683f` (PR #15) | Full first-customer acceptance pass: security, imports, forecasting, pricing, assistant, competitors, mobile, Arabic, demo companies |
| PR #14 | Earlier production-readiness work |

---

## KEEL session (2026-10-07): start here

**Branch:** `claude/dreamy-allen-huyq8o` (pushed; no pull request opened yet).

### What changed
- **Brand and design.** The product is called KEEL everywhere a user can see it, including the public landing page, sign-in and emails.
  - It uses one Liquid Glass design language. The tokens live in `frontend/src/styles/apex-theme.css` and the shared components in `shared/components/apex/Apex.jsx` and `styles/apex-components.css`.
- **Themes.** Light is the default. Dark is an optional, remembered choice, available from the toggle in the top bar, on the landing page and on the sign-in pages.
  - The choice is stored on the device in `localStorage.apex_theme`.
  - `index.html` applies the stored theme before first paint, so the wrong theme never flashes.
  - Stylesheets use theme tokens (`--apex-*`) instead of colour literals. Dark is a deep indigo-navy canvas, not black.
  - Chart colours are validated per theme (`shared/components/charts/chartTheme.js`).
- **Navigation.** A floating glass top bar (`shared/components/layout/TopNav.jsx`) replaces the left sidebar.
  - The top row holds the brand, search and actions. All 9 destinations sit on a centred tab rail below, with a sliding indicator.
  - Search opens a command palette (Ctrl/⌘K) covering products, competitors and pages.
  - Settings, Billing and Logout are in the profile menu.
  - On screens up to 900 px wide, a menu button opens a glass sheet.
- **Glass material** (`styles/apex-glass.css`, loaded last). The interface is built like a physical glass object lit from the top-left:
  - **Canvas:** a silver studio gradient with blurred coloured light sources.
  - **Plane:** one large, nearly clear glass sheet carrying each page. Its material sits on pseudo layers, so fixed dialogs are never trapped.
  - **Slabs:** the cards.
  - **Controls:** thick glossy pills.
  - **Coloured glass:** primary actions.
  - **Overlays:** denser frost, for readability.
  - **Optics shared by every layer:** a backdrop blur with saturation, a bright rim that catches light top-left and bottom-right, an iridescent edge, inner glow, a darker inner edge for thickness, a specular sheen, and a shadow cast down-right that is tinted for coloured glass.
  - The dark theme changes only the `--lg-*` tokens.
  - This was iterated against the reference image with side-by-side screenshots.
- **Motion** (`styles/apex-motion.css`). Every screen enters with a short staggered rise, metric numbers count up, and charts draw in.
  - Glass cards respond to hover with depth and a light sweep, and buttons lift and press.
  - Modals and menus scale in, and the landing hero and sign-in pages have slow aurora light.
  - All of it is disabled under `prefers-reduced-motion`.
- **Fixes found during verification:**
  - A stylesheet rule forced every link to left-to-right in Arabic (`a[href]`); it now only applies to external URLs.
  - Tapping the current page in the mobile menu left the menu open.
  - In dark mode, selected toggles had white text on a pale fill.
  - Toasts and badges used the old colours.
  - Reports showed 4-decimal quantities.

### Verified in a real browser (Chromium, demo company Zaytouna)
- All 9 tabs navigate and highlight correctly, in English and Arabic.
- The mobile menu works at 390 px, with no horizontal overflow.
- The search palette returns products and competitors and opens them.
- The profile menu items work.
- The theme toggle persists across reloads.
- Every screen was reviewed in light and dark.
- The 43 frontend unit tests pass, and the production build passes.

### Still open / not verified
- **Live AI answers** (assistant, marketing copy and images) need `GROQ_API_KEY` plus network access to `api.groq.com` and `huggingface.co`. Neither was available here.
  - The assistant reports "not configured" honestly and falls back to keyword retrieval.
- **Windows-only browser test.** `frontend/tests/settings-browser.mjs` is hard-wired to Windows Edge paths. Its sidebar assertion was updated for the top bar but it was not run here.
- **Terms and Privacy.** The links on sign-up point to `#terms` / `#privacy`; no legal pages exist yet.

---

## HANDOFF (2026-10-06, updated after the second session)

**Branch:** `uat/first-customer-readiness`
**Pull request:** #16 (draft), "Product completion: status/run guide, product assistant, usage plans, UI consistency"
**Base:** `main` @ `cf4683f` (PR #15 merged). Everything below is on the branch, nothing on `main` yet.
**Latest code commit:** `7c7b93a` "Add product guide for the assistant". The commit after it only updates this file (`git log -1` shows the exact tip).
**Commits on this branch:** `049723b`, `f58a9cf`, `8015e57`, `0e79733`, `36f8453`, `7c7b93a`, plus this status update. Not merged.

### Done and verified
- `CURRENT_STATUS.md` and `RUNNING_LOCALLY.md` were checked by following the guide on a **fresh clone**:
  - `setup.sh`, the migrations, the backend and the production frontend build all worked.
  - A new user signed up through the real form and landed on the dashboard.
  - Demo company seeded with `verify` → `0 failing check(s)`.
- `.devcontainer/setup.sh` installs CPU-only PyTorch on Linux when download.pytorch.org is reachable (saves about 3.4 GB) and otherwise falls back to the default PyPI build.
- `.devcontainer/env_utils.sh` now uses `sed -i.bak`, so it works on macOS.

### Priority 6, subscription usage allowances: done and verified live (NOT merged yet)
Goal: plan allowances per company, kept completely separate from technical limits such as the 20 MB per document upload limit. A provider rate limit must never disable other companies.

**Files**
- New: `backend/src/infrastructure/database/migrations/20261007000000_add_usage_plans.sql`
  - Tables: `usage_features`, `usage_plans`, `usage_plan_limits`, `tenant_plan_assignments` (RLS) and `tenant_usage_counters` (RLS).
  - The app role is read-only on features, plans and assignments; only an operator or billing service writes them.
  - Seeded plans `standard`, `pro` and `custom`; `custom` means unlimited (NULL limits).
  - **Already applied** to the local `ceopro_platform` (test) and `ceopro_uat` databases.
- New: `backend/src/ai/core/usage.py`
  - `get_plan`, `current_usage`, `reserve` (atomic conditional upsert), `release`, `ensure_capacity`, `PlanLimitReached` (returns a 402 with `reason` / `current_usage` / `limit` / `remaining` / `reset_cycle` / `period_end` / `message`).
  - `ensure_ai_rate`: a per-company per-minute cap enforced through Redis (`AI_REQUESTS_PER_MINUTE_PER_COMPANY`, default 8).
  - `DEFAULT_PLAN_KEY` (default `pro`) applies to companies with no assignment.
- New: `backend/src/ai/routers/billing.py`, endpoint `GET /billing/subscription`, registered in `main.py`.
  - Returns the plan, status, period, `features` (in the reference project's usage shape), and `limits` / `usage` under the keys the Billing page reads.
- Modified:
  - `core/exceptions.py`: global 402 handler for `PlanLimitReached`.
  - `routers/rag.py`: reserves `rag_assistant` and commits; releases the reservation in `finally` if no answer was produced; adds the per-company rate cap.
  - `routers/products.py`: `tracked_products` capacity check on manual create. Imports are not blocked by design, so customer data is never dropped.
  - `routers/competitors.py`: `tracked_competitors` check after registering, so re-adding an existing competitor still works.
  - `routers/extraction.py`: `document_storage_mb` check for PDF uploads, and a 402 is passed through rather than becoming a 500.
  - `routers/marketing.py`:
    - `marketing_image_generation` is reserved before the provider call and released when no image is produced.
    - Raw storage and MinIO error text is no longer returned to users.
    - **Fixed an indentation bug introduced during this work** (a `raise` outside its `except` block).
- Frontend:
  - `billing/api/billingApi.js`: reads `GET /billing/subscription` and maps billing statuses: trialing→trial, active→active, everything else→failed.
  - `knowledge-base/api/knowledgeBaseApi.js` + `RagAssistantPage.jsx`: a localized message when the plan's questions are used up (402); 429/503 show a "busy, retry in N s" message.
  - `locales/en.json`, `locales/ar.json`: new keys `ragAssistant.feedback.planLimit` and `billing.management.usageLabels.webSearches` / `imageGenerations`.
- Tests:
  - New `backend/src/ai/tests/test_usage_integration_db.py`. It covers default and assigned plans, exact-limit reservations, release, 25 concurrent reservations that must not overshoot, unlimited and inactive plans, live capacity counts, and app-role isolation with no plan writes.
  - `tests/conftest.py`: stubs usage enforcement for MagicMock-connection unit tests only.

**Since the pause (all committed)**
- `0e79733`: the 4 `/rag/query` tests in `test_main.py` now assert the reserve-then-answer contract.
- `36f8453`: verified live on the UAT stack.
  - `GET /billing/subscription` works.
  - With a temporary plan allowing 2 questions, the third question got a 402 `QUOTA_EXHAUSTED` with the renewal date.
  - A failed request didn't use up any allowance, and the other company was unaffected.
  - The chat showed the plan-limit message in English and Arabic.
  - The Billing page shows the real plan and usage. It now also works for a plan that isn't in the page's catalogue, and shows "Unlimited" for unlimited allowances.
  - The temporary plan was deleted afterwards.
  - `RUNNING_LOCALLY.md` documents `DEFAULT_PLAN_KEY`, `AI_REQUESTS_PER_MINUTE_PER_COMPANY` and the SQL to assign a plan.
- `7c7b93a` (Priority 3, first part):
  - New `backend/src/ai/rag/product_guide.py`: step-by-step directions for 15 tasks (add a product, upload sales, record a sale, reviews, competitors, search scope, target markets, forecast, pricing, campaign, assistant documents, team, billing, language, dashboard), in English and Arabic.
  - New `backend/src/ai/tests/test_product_guide.py`: fails if any screen or button named in the guide is not a real label in `frontend/src/assets/locales/en.json` / `ar.json`. It also checks section selection in English and Arabic.
  - **Not yet wired into the assistant.** `build_guide_block()` still has to be added to the prompt in `rag/llm_client.py`, and the outdated `generate_platform_help_summary` has to be replaced or removed.

**Test state at `7c7b93a`**
- Backend: **1888 passed, 50 skipped, 0 failed** (with `AI_TEST_DATABASE_URL` set).
- Frontend: **43 passed, 0 failed**. The production build passed at `36f8453`; there have been no frontend changes since.

### Findings from the reference project's `backend` branch (read only; nothing was changed there)
- It is a TypeScript/Prisma billing backend. Its tables are `plans`, `features`, `plan_features`, `subscriptions` and `subscription_usage`, all keyed by the same `companies.tenant_id` UUID.
- It owns plans, limits and usage.
- It exposes `GET /subscriptions/current/usage` (uses the user's JWT). It has Stripe webhooks with signature checks and idempotency.
- There's no service-to-service endpoint and no Redis or event stream; its only outbox is the `platform_notification_outbox` table.
- KEEL's usage layer was aligned on purpose:
  - Same feature codes: `rag_assistant`, `tracked_products`, `tracked_competitors`, `document_storage_mb`, `marketing_image_generation`, plus a proposed new code `web_searches`.
  - Same `sum` / `max` aggregation types and `billing_period` / `lifetime` reset cycles.
  - Same statuses, where only `active` and `trialing` grant access.
  - Same 402 error body.
- Table names are deliberately different (`usage_*` / `tenant_*`), so the two can't collide in one database.
- Later, `usage.get_plan` and `current_usage` can read the reference project's tables or API instead without changing callers.
- **To agree with the collaborator:**
  - Shared database or API?
  - A service token for recording usage.
  - Adding `web_searches` to their feature catalogue.
- **Don't copy** their non-atomic check-then-increment, token-count charging against "queries", in-memory rate limiting, or unenforced session revocation.
- **Worth adopting later:** re-checking `tenant_users` membership on every request, and session revocation via a `session_version` in the JWT.

### Assistant work after the handoff (owner's items 1-6, in order)
- **Item 1, how-to directions:** done and verified live in English and Arabic, including in the chat screen (commit `8ef6ace`).
- **Item 2, business answers:** committed and covered by automated and database tests, but **not yet verified live with the AI provider.**
  - New `backend/src/ai/rag/business_analysis.py`, built only when a question asks for it:
    - which products are declining or growing (last 30 days vs the 30 before);
    - what to restock (forecast vs stock, the reorder level, and days of stock left at the recent sales pace);
    - a named competitor comparison (products in common, who is cheaper on each, review sentiment), with the rule for "strongest" stated.
  - The assistant is told to end data-based answers with a "Source:" line naming what it used: your own records, KEEL's calculations and competitor tracking, your documents, or external research.
  - Checked against the demo company's real data, so the blocks are correct. But every live question returned a rate-limit error: the Groq free tier allows 200,000 tokens per rolling 24 hours, today's testing used about 196,000, and each question costs about 5,500.
  - **Pending:** ask these questions live once capacity returns:
    - "Which of my products are declining?"
    - "Which products do I need to restock?"
    - "Who is my strongest competitor and why?"
    - "How do my prices compare with my competitors?"
    - "ما هي المنتجات التي تتراجع مبيعاتها؟"
    - "What is your delivery policy?" (should answer from documents)
    - "What are my competitors' sales volumes?" (should say this isn't available)

### Not finished yet (from the owner's priority list)
- **Priority 3/4/5: product assistant.**
  - The product guide module exists (see `7c7b93a` above). It still has to be wired into the prompt and live-tested in English and Arabic.
  - The existing `rag/structured_summaries.py::generate_platform_help_summary` is outdated: it says "7-day forecast" and "no frontend exists".
  - Business-question context should be chosen by topic (sales, restock, competitors, market, social) rather than always included, because Groq's free tier allows 8,000 tokens per minute.
  - A sourced web-research fallback should use `rag/web_fallback.py`, metered by `web_searches`, with every answer labelled as company data, KEEL calculation, integration, or external research.
- **Priority 2:**
  - Arabic product names, which are English-first today (the name is chosen in SQL in many modules).
  - Full image-generation workflow with a provider.
  - Campaign-image isolation: verified for read, remove-background and generate (404 across companies); recheck after this change.
  - A reproducible verification path for social features (outbound access is blocked in the sandbox).
- **Priority 7:** a visual consistency pass over every screen.
- **Final acceptance**, merge, verify `main`, and the 10-point final report.

### Resume in this order
1. Run the checks:
   ```bash
   cd backend && set -a && . ./.env && set +a
   export AI_TEST_DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/ceopro_platform"
   python -m pytest -q src/
   cd ../frontend && node --test tests/*.test.mjs && npm run build
   ```
2. Apply the migration anywhere it hasn't run: `python scripts/apply_migrations.py`.
3. Wire `product_guide.build_guide_block(question, language)` into the assistant prompt (`rag/llm_client.py`), then live-test questions such as "How do I add a product?" and "كيف أغير الأسواق المستهدفة؟".
4. Continue with Priority 4/5 (business answers chosen by topic; a sourced, metered research fallback), then Priority 2, Priority 7 and final acceptance. Don't merge until the owner says so.

### Must NOT be changed
- Don't rename or merge the KEEL `usage_*` / `tenant_*` tables into the reference project's table names. They must stay distinct.
- Don't let the app role write `tenant_plan_assignments`.
- Don't count a question that wasn't answered; keep reserve-then-release.
- Don't remove technical upload limits; they are separate from plan allowances.
- Don't modify the reference project's repository from KEEL work.
