# KEEL — Complete Handover (2026-11-06)

Written by the "KEEL project knowledge preservation" Claude Code session (`session_019obuSftHsrnkKVcCxdj96u`)
in the last 30 minutes before the owner's paid access ended. Read this first, then the four companion files:

| File | Purpose |
|---|---|
| `KEEL_ALL_SESSIONS_WORK_INVENTORY.md` | Every Claude Code session found, what it did, where its work lives |
| `KEEL_PENDING_TASKS_AND_BLOCKERS.md` | Every open task, its dependency and the exact next action |
| `KEEL_TECHNICAL_STATUS_AND_VERIFIED_RESULTS.md` | Architecture, Git state, test/evaluation results, infrastructure |
| `KEEL_DECISIONS_AND_AUTHORIZATIONS.md` | Decisions, approvals, explicit non-approvals, safety rules |

## Evidence levels used throughout

- **VERIFIED**: checked by this session against Git or the repository on 2026-11-06 (commit hashes, branch
  state, file contents).
- **REPORTED**: stated in another session's final message. Not re-checked here. Treat as a claim.
- **ASSUMED / UNKNOWN**: inferred, or nobody could check it.

## 1. What KEEL is

A multi-tenant, AI-powered SaaS for business intelligence and commerce operations. It has 15 features: Dashboard,
Products, Inventory, Data Connections/Document Extraction, Demand Prediction, Competitors, Market Intelligence/Customer
Perception, Pricing Recommendations, RAG Assistant, Smart Alerts, Marketing Images, Billing/Subscriptions,
Shopify/WooCommerce, Reports/Exports and Platform Administration. Repository: `Huda-Hassouneh/CEOPRO-AI`.
The internal name CEOPRO-AI still appears in code. Customers see KEEL.

- Backend: Python/FastAPI (`backend/`), workers, PostgreSQL with FORCE RLS, Redis.
- Frontend: React/Vite (`frontend/`), English and Arabic (RTL), light and dark.
- Python is the only authority for auth, Stripe billing, entitlements, pricing and credits.
- Rules for coding agents: `AGENTS.md`. The rules on tenant isolation, billing integrity, Stripe Test Clock and
  never committing secrets are mandatory.

## 2. Current state in one page (VERIFIED unless marked)

- **`origin/main` = `33e2d22`** ("Docs: handover of the assistant understanding and Jordanian round…").
  Latest assistant handover: `docs/HANDOVER_RAG_JORDANIAN_2026-11-06.md`.
- **Production deploy branch = `claude/vibrant-albattani-j2ksq5`** (REPORTED by two sessions; the branch exists on
  the remote). Its tip `337561a` is main up to `16fd8f5` plus merge commits. It does **not** yet contain `b8aa514`
  and `33e2d22`, which are docs only. The "KEEL demo account setup" session said it was merging them and would
  push and deploy. That was still in progress at 20:36 UTC.
- **Production domains** (REPORTED, 20:20 UTC): `keelai.net`, `www.keelai.net` and `https://api.keelai.net/health`
  return 200. The API runs on the Render service `ceopro-ai-new` and the website on `keel-web`.
  **Risk:** Cloudflare DNS still points at the `*-staging.onrender.com` hostnames, which may belong to 360-Radar.
  Repointing them is waiting for the owner's approval.
- **Email** (REPORTED): Brevo SMTP on port **2525** works end to end, sending from `support@keelai.net`. Render's free
  plan blocks ports 25, 465 and 587. The `keelai.net` domain is authenticated in Brevo (DKIM and DMARC pass).
- **Assistant / RAG** (REPORTED, recorded on main): the Jordanian final set scored **84/91 = 92.3%**, below the 95%
  target. The all-dialect sealed set scored 97.1%. The speed/social-conversation/research plan has been written but
  is not approved: `docs/ASSISTANT_SPEED_SOCIAL_RESEARCH_PLAN.md`.
- **VELORA demo** (VERIFIED code): commit `ed5aad0` adds an opt-in `--only velora` synthetic profile in
  `backend/scripts/demo_companies/`. Whether the demo account exists in production is UNKNOWN; see the pending
  tasks file.
- **Competition documents (three final docs, DOCX + PDF, plus a PowerPoint review): NOT in the repository.**
  The owner chose not to put them on the public GitHub repo. They exist only in session
  `session_019obuShG5b67AsXmohadjpu` ("Competition pitch documentation"): two local commits `f2b58e83` and
  `4699907d` on the unpushed branch `claude/funny-wright-wf4cmk`, folder `docs/competition/`. That session's chat
  says the files were delivered as attachments. **Download them from that session's chat now**: they disappear when
  its container is reclaimed.

## 3. How to continue (exact first steps for a new developer)

```bash
git clone https://github.com/Huda-Hassouneh/CEOPRO-AI && cd CEOPRO-AI
git checkout main && git log --oneline -5      # expect 33e2d22 at the top (or later)
```
1. Read `AGENTS.md`, `README.md`, `docs/HANDOVER_RAG_JORDANIAN_2026-11-06.md`, then the four companion files.
2. For local runs, use `dev.ps1`/`dev.sh` (`doctor`, `up`, `status`, `test`) and read the active ports from
   `status`.
3. Backend tests: `cd backend && PYTHONPATH=. pytest -q`. Some tests fail locally without `torch`,
   `huggingface_hub` or a local Postgres. Compare against main before blaming a change.
4. Before you touch production: confirm which branch Render deploys (`claude/vibrant-albattani-j2ksq5`, REPORTED),
   and that only one agent or person is changing production at a time.
5. Take the first open item in `KEEL_PENDING_TASKS_AND_BLOCKERS.md` that the owner has approved.

## 4. Session-history limits (be honest about these)

- 43 sessions are visible to this account. 2 belong to other projects (360-Radar, a solar assignment), and their
  content was not reviewed beyond the titles. For all KEEL sessions this session read the title, status and last
  summary. Full final-turn results were read for only 7 sessions; see the inventory.
- Full transcripts could not be exported from inside a cloud session. A cloud session has no `/export` command, and
  its tools return per-event JSON only. The owner can export each conversation by opening it in the Claude app

## 5. Update 20:43 UTC — report from "KEEL demo account setup" (`session_019obuSiDQdTMDxrwW7z58VV`)

Branch `claude/focused-goodall-kiwf2f` (VERIFIED on the remote) carries `d214da09`, "forecasts always regenerated
after an import". **It is NOT on main and NOT deployed.** It changes `backend/src/ai/forecasting/{generation,refresh}.py`
and `backend/src/ai/routers/extraction.py`, and adds two tests. It fixes stale forecasts (about 10% of real demand)
after back-to-back uploads. It still has to be merged with `b8aa514` and `33e2d22`.

REPORTED by that session:
- **Tests:** local backend 4,937 PASS / 1 FAIL (`test_standard_plan_creation_contract`, caused by local reused-DB
  state); frontend 267 PASS, lint and build PASS; GitHub CI on `ef305db` PASS; 29 new forecast tests PASS.
- **Production:** API `ceopro-ai-new` runs `337561a` (main `16fd8f5` content). Website `keel-web` runs `341049e`.
- **VELORA demo account:** EXISTS. It was created through normal signup with the owner's own email and verified by
  the emailed code. Company VELORA (JO/JOD), Plus trial until 2026-11-20. The temporary password was given to the
  owner in that session's chat only; change it.
  - **Onboarding** was completed in the UI.
  - **Seeded via the public API:** 28 products, 54,889 synthetic sales lines (Apr 2025 – 5 Nov 2026), 11 fictional
    "DEMO Competitor NN" with 62 prices, and 266 reviews labelled "DEMO synthetic review".
  - **Checked against ground truth:** revenue 7d 4,365.303 / 30d 22,950.648 / 90d 61,945.621 JOD, exact match.
- **Remaining:**
  - Deploy `d214da09`, then refresh VELORA's forecasts (they are currently stale and low).
  - Review sentiment shows 0/200 analysed; not investigated.
  - Not yet tested: the assistant in EN and Jordanian, reports and exports, Arabic on mobile.
  - KEEL has no expenses/purchases feature.
  - MinIO (file storage) and Tavily are not configured in production.
