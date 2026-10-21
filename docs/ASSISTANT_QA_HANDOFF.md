# Assistant (RAG) - QA handoff, 2026-10-21

Start here in a new session. What is finished, and what is open, is tracked in
`backend/PENDING_ACTIONS.md`, section "Assistant: evidence mode, AI credits and
local QA" (done rows D1-D6, pending rows #124-#134). This file is the how-to.

## The problem and the fix, in one paragraph

Every assistant question failed with a 503 because no `groq` price existed in
`provider_cost_schedules`, and `billing/credits.py` refuses any model call
without a confirmed price. The refusal (`BudgetError`) is not an `LLMError`, so
`rag/advisor.py` never fell back to its evidence-only answer. PR #74 maps the
server-side refusals (`COST_NOT_CONFIGURED`, `PROVIDER_DISABLED`,
`PROVIDER_CAP_REACHED`) to the errors the advisor already handles. A company's
own plan or credit limit (`BUDGET_EXHAUSTED`, `SUBSCRIPTION_INACTIVE`) still
stops the question with a 402.

For the assistant to write real answers, three things must all be true:
1. `GROQ_API_KEY` is set (`backend/.env` locally; by hand on Render).
2. A Groq price is recorded for `input_token` and `output_token`
   (`python -m scripts.billing_admin set-price ...`, see PENDING_ACTIONS #125).
3. The company has a plan (signup gives a trial), or `UNASSIGNED_PLAN_ACCESS=default` for local development only.

## Rebuild the local environment

The Postgres (`v-pg`), Redis (`v-redis`) and MinIO (`v-minio`) containers are
the CI-style stack; their test credentials are the ones in
`.github/workflows/pr-checks.yml`. The Python in your shell may be conda's and
lack packages: use a virtualenv.

```bash
cd backend
python3.11 -m venv ~/keel-venv && ~/keel-venv/bin/pip install -r src/ai/requirements.txt pytest
cp -n .env.example .env       # then edit .env: see "Local .env" below
```

Local `.env` values that matter (never commit this file; it is gitignored):
`DATABASE_URL`, `APP_DB_PASSWORD`, `MINIO_ROOT_PASSWORD` matching the containers,
`JWT_SECRET` (`openssl rand -hex 32`), `CREDENTIAL_VAULT_MASTER_KEY`
(`python -m scripts.vault_key generate`), `UNASSIGNED_PLAN_ACCESS=default`
(development only), and `GROQ_API_KEY`.

**Set the key by editing `backend/.env` in an editor.** Do not paste it into a
chat. The one-line `read -rs` prompt only works in a real interactive
terminal, not in a tool that runs one command at a time.

Check the configuration and the provider (neither prints the key):

```bash
cd backend && set -a && . ./.env && set +a
~/keel-venv/bin/python -m scripts.check_config
~/keel-venv/bin/python -m scripts.llm_provider_check                   # key + price + model list
~/keel-venv/bin/python -m scripts.llm_provider_check --tenant <id>     # plus one real metered answer
```

Record the price (input and output, once each; take the figures from Groq's
model docs or an invoice, never guess; use real values, not `<...>` placeholders,
which zsh reads as redirects):

```bash
~/keel-venv/bin/python -m scripts.billing_admin set-price --budget ai --provider groq \
  --operation 'openai/gpt-oss-20b' --unit input_token --usd-per-million <price> \
  --source '<where the price comes from>' --verified-on <YYYY-MM-DD> --by '<name>' --reason '<why>'
```

## Run the stack and a test company

```bash
cd backend && set -a && . ./.env && set +a && export PYTHONPATH=.
~/keel-venv/bin/uvicorn src.ai.main:app --host 127.0.0.1 --port 8000 &
~/keel-venv/bin/python -m scripts.ci_smoke_account --api http://localhost:8000 --email qa.rag@example.com --password '<a test password>'
cd ../frontend && VITE_API_BASE_URL=http://localhost:8000 npx vite --host 127.0.0.1 --port 5173 &
```

The assistant page is `/ai-advisor/chat`. Sign-up gives every new company a
trial plan.

## Re-run the checks

| Check | Command | Expected |
|---|---|---|
| Backend suite with the live database | `cd backend && export DATABASE_URL=... AI_TEST_DATABASE_URL=... SCRAPER_DATABASE_URL=... APP_DB_PASSWORD=... && python -m pytest src/ -q` (values as in `pr-checks.yml`) | 3,434 passed, 61 skipped, 0 failed (as of PR #74) |
| Assistant scenario matrix | `python -m scripts.assistant_qa_matrix --api http://localhost:8000 --email qa.rag@example.com --password '...' --other-email qa.other@example.com` | mode `ai` for A-D and H2; 404 for E and H; 422 for F, F2; 401 for G; "leaks a key: False"; "sees the first company's data: False" |
| Documents, embeddings, Arabic retrieval, isolation | `python -m scripts.rag_e2e_check --api http://localhost:8000 --email qa.rag@example.com --password '...'` | `PASS`, 4/4 Arabic questions cite their English document first |

## Failure scenarios (change server state, restore afterwards)

Run each against the API with the test company, ask one question, and restore.
Expected result in brackets (this is the behaviour PR #74 guarantees).

1. **Price removed** (the original bug): `UPDATE provider_cost_schedules SET unit_cost_usd = NULL WHERE provider = 'groq';` -> [200, `answer_mode: evidence`, `answer_writing: not_configured`]. Restore both rows (`input_token` 0.000000075, `output_token` 0.0000003, or the confirmed prices).
2. **Company credits exhausted**: `admin.adjust_credits(conn, tenant_id=..., budget_kind="ai", credits_delta=<plan limit>, ...)` -> [402 `BUDGET_EXHAUSTED` with the renewal date]. Reverse with the negative delta.
3. **Invalid key**: start a second API on another port with `GROQ_API_KEY=gsk_invalid...` -> [200 evidence, `provider_unavailable`].
4. **No key**: second API with `GROQ_API_KEY` unset -> [200 evidence, `not_configured`].
5. **No plan**: second API with `UNASSIGNED_PLAN_ACCESS=none`; delete the test company's row in `tenant_plan_assignments` (keep a copy, restore it) -> [402 `SUBSCRIPTION_INACTIVE`].

## Known gotchas

- Run the backend suite with the CI environment from `pr-checks.yml` only (`env -i ...`), not with `backend/.env` sourced: the dev file makes about 280 tests fail (429 rate limits, extra keys).
- Groq's free tier allows 200,000 tokens per day; a full QA session can use it up. The 429 shows as evidence mode with `provider_busy`.
- zsh treats `<name>` as a redirect: placeholders in copied commands must be replaced by real values, including the angle brackets.
- The `ruff` default ruleset reports about 120 findings on these files; the repo has no ruff configuration and CI does not run it. Check `--select F` only.
- The ledger status after a settled call is `consumed`, not `settled`.
- `KEEL_TEST_DISABLE_METERING=1` (set by `conftest.py`) bypasses credits in most tests; the credits integration tests delete it on purpose.
- This session's Python virtualenv and helper scripts lived in a temporary scratchpad and are gone; rebuild as above.
