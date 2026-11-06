# KEEL — Technical Status and Verified Results (2026-11-06)

## 1. Architecture (VERIFIED from the repository)
- `backend/`: FastAPI API, AI modules (`backend/src/ai/…`, including `rag/`), workers, migrations (forward-only),
  billing (Stripe, signed webhooks, idempotent handling), and RLS-enforced Postgres access with separate runtime
  roles: `ceopro_app`, `ceopro_billing_setup`, `ceopro_billing_webhook` and `ceopro_credit_accounting`.
- `frontend/`: React/Vite, KEEL glass design system (`frontend/src/styles/keel-glass.css`), EN/AR RTL.
- `render.yaml`: Blueprint with `keel-ai-staging`, `keel-frontend-staging` and `keel-redis-staging` (workers are
  commented out). Production actually runs on separately created services `ceopro-ai-new` and `keel-web`
  (REPORTED).
- Detailed docs: `docs/ARCHITECTURE.md`, `docs/FEATURES.md`, `docs/DATABASE.md`, `docs/WORKERS.md`,
  `docs/SUBSCRIPTIONS_AND_CREDITS.md`, `docs/TRIAL_DOWNGRADE_INTEGRITY_FIX.md`,
  `docs/CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md` and `STAGING_DEPLOYMENT.md`.

## 2. Git state (VERIFIED at about 20:40 UTC)
- `origin/main` = `33e2d22c41267fc4df48e70d859abc0d798ec18b`.
- Recent main history:
  `33e2d22` handover + eval harness ← `b8aa514` speed/social/research plan ← `16fd8f5` large sales import fix ←
  `341049e` setup country fix ← `ef305db`/`f1bf0ee` image tests ← `ed5aad0` VELORA demo profile ← `dd632af` Brevo
  port 2525 docs ← `05665f0` truthful email-delivery reporting ← `d921681` production deploy fixes merge ←
  `fc99ae1`/`7962305`/`a5b95f6`/`6c9f481` assistant accuracy ← `d1a6eeb` marketing ← `98c0c53` keelai.net setup docs
  ← `b21322f` migrations without superuser.
- Production branch `origin/claude/vibrant-albattani-j2ksq5` = `337561a`. It is 4 commits ahead of main (all
  merges) and is missing `b8aa514` and `33e2d22`, which are docs only.
- This session's branch `claude/bold-davinci-wy7hdw`: fast-forwarded to `33e2d22`, plus this handover commit.
- The remote has 100+ other branches (feature, session, reconcile). Nothing was deleted or force-pushed.
- In this checkout: no stashes, and no uncommitted work other than this handover. The ignored files
  `backend/.env` and `frontend/.env` exist and were **not** committed.

## 3. Test and evaluation results (all REPORTED by the sessions that ran them; not re-run here)
| Area | Result | Source |
|---|---|---|
| RAG tests on main `33e2d22` | 251 passed | Model accuracy session |
| Jordanian final sealed set (91) | **84/91 = 92.3%** (CI 85.0–96.2), **below the 95% target: FAIL against the goal** | `docs/HANDOVER_RAG_JORDANIAN_2026-11-06.md` |
| Sealed v3, all dialects (136) | 132/136 = 97.1% | same |
| Jordanian dev / validation | 95.8% / 95.0% | same |
| Local LLM reader latency | 7–15 s per call on CPU, so it is left off (`RAG_LLM_UNDERSTANDING` unset) | same |
| Assistant non-model latency | greetings 0.00 s; simple business questions 0.12 s median | `docs/ASSISTANT_SPEED_SOCIAL_RESEARCH_PLAN.md` |
| Full backend suite (Oct 31) | 4,518 pass, 35 environment-only fails; frontend 236 pass | RAG retention session |
| Backend (Oct 28) | 3,673 passed at `0030408` | Full audit session |
| Email signup (production) | PASS: Brevo log shows delivery 1 s after the request, at 18:35 UTC | Model accuracy session |
| Login and password reset in production | **NOT TESTED** | — |
| Production answer quality and latency with Groq | **BLOCKED** (key rejected in dev) | — |
| Embeddings with Hugging Face | **BLOCKED** (401) | — |
| Forecast accuracy benchmark | Added in `6c9f481` (see `docs/AI_MODEL_ACCURACY.md`) | — |

## 4. AI areas
- **RAG / assistant**: rules-first understanding (`understanding.py`), exact business records, BM25 + embeddings,
  then one Groq call (`openai/gpt-oss-20b`) with a citation check. Without a model it runs in evidence mode.
- **Arabic dialects**: Jordanian is at 92.3% on the final set; other dialects were measured on sealed v3 (97.1%).
- **Social conversation**: greetings and introductions get fixed replies with no model call. Upgrades are in the
  unapproved plan.
- **External research**: `research/research.py`. Queries are stripped of private figures, sources are cited and
  budgets apply. Tavily and others depend on configured keys.
- **Forecasting**: a benchmark exists. The next "forecasting phase" waits for the owner's decision.
- **Marketing images**: `d1a6eeb`, `ef305db` and `f1bf0ee`; "image-generation port" waits for a decision.

## 5. Financial integrity and reporting
- Rules (`AGENTS.md`): Stripe signed webhooks, payment-gated access, the trial/downgrade integrity fix, and credits
  kept separate from provider costs. Billing reconciliation merged in PR #82 (`aaa725e`), with the approved launch
  catalog prices (`b930714`).
- No Stripe LIVE operation was performed by any session reviewed here (REPORTED). The Stripe Test Clock stays off
  by default.

## 6. Infrastructure (REPORTED, 2026-11-06)
| Service | Status |
|---|---|
| Render | `ceopro-ai-new` (API, `api.keelai.net`) and `keel-web` (site) are live. 5 other services on the account were not touched (some belong to 360-Radar). |
| Neon Postgres | Production DB. Migrations now run without a superuser (`b21322f`). Take a Neon backup branch before any migration. |
| Redis | `keel-redis-staging` in the Blueprint; production Redis details unverified |
| Cloudflare | DNS for `keelai.net`. Records point at the `*-staging.onrender.com` hosts (risk; see pending task 4). Read token works. |
| Brevo | Free plan, SMTP relay on port 2525, sender `support@keelai.net`; domain authenticated |
| Hugging Face | Token rejected (401) |
| Groq | Key rejected in dev; production status unverified |
| Domains | `keelai.net`, `www.keelai.net` and `api.keelai.net` return 200 |
