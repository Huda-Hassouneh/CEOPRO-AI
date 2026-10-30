# RAG Assistant 503 resolution

Date: 2026-10-28. Checkout: `E:\KEEL START\CEOPRO-AI`, branch `integration/keel-full-migration`; starting revision `65034f883c84228fc446aeaeef5315a55247d74b`.

## Root cause

The configured Groq key and `openai/gpt-oss-20b` model access were valid (model-list HTTP 200). The request was refused **before generation** because both token-cost records in `provider_cost_schedules` were unverified/NULL. The API log at 09:32:34 reported `COST_NOT_CONFIGURED (no confirmed input_token price for groq/openai/gpt-oss-20b)`.

The credits guard correctly prevented unpriced spending. The RAG adapter incorrectly classified that refusal as missing model configuration, producing the misleading administrator/provider message seen for `hello`. This was not a Vite proxy or CORS failure, and not a missing Groq key.

Configuration has two existing authorities:

- Provider credentials/model selection: environment configuration, loaded locally from private `.dev/integrations.env`; restart the API after changing it. Groq uses `GROQ_API_KEY` and optional `GROQ_MODEL`.
- Verified provider costs: database-backed schedules, changed through the existing authenticated Platform Owner `scripts.billing_admin set-price` command. `COST_NOT_CONFIGURED` is a refusal code, not an environment variable. Custom quote rates are a different authority.

The owner explicitly approved USD 0.075/million input tokens and USD 0.30/million output tokens, matching the [official model page](https://console.groq.com/docs/model/openai/gpt-oss-20b). The owner ran the private interactive helper using a genuine Platform Owner login. Both rows and the corresponding authenticated audit records were verified. Existing cost-finality, failure-charging and safety-margin settings were preserved. No secret or authenticated session is stored in this report.

## Scoped corrections

| Files | Change |
|---|---|
| `backend/src/ai/rag/llm_client.py`, `advisor.py` | Distinguish missing verified prices from missing credentials; retain the existing evidence-only fallback when evidence exists. |
| `backend/src/ai/routers/rag.py` | Return the shared safe structured pricing refusal with the persisted session ID when no answer can be generated; retain plan-reservation release. |
| `backend/src/ai/rag/faiss_index.py` | Construct an empty semantic index without importing optional FAISS; lexical retrieval still works when no vectors are present. Nonempty semantic indexing remains unchanged. |
| Frontend `knowledgeBaseApi.js`, `references.js`, English/Arabic locales | Display accurate pricing guidance for failed generation and evidence-only answers; preserve the UI layout and history. |
| Four backend test files and two frontend test files | Cover refusal classification, no provider invocation/charge, retained question, released allowance, cross-tenant history denial and empty semantic-index behavior. |

No migrations, permission grants, billing rules, provider substitution, AI model mathematics or production defaults changed. No large ML packages were installed.

## Verification

| Check | Result / evidence |
|---|---|
| Isolated backend regressions | **PASS: 236 passed, 5 skipped.** Skips are the explicit opt-in real embedding-model tests; they require a large model download and are not counted as passed. Covers RAG router/advisor/provider integration, failed-chat recovery, citations, document access, credits, usage and restricted-role RLS. |
| Disposable database | **PASS:** 146 migrations, pgvector, restricted password login and 120 FORCE RLS tables. No schema change was introduced. |
| Tooling checks in backend wrapper | **PASS:** 52 tests. |
| Frontend | **PASS:** 229 tests, zero failures/skips; ESLint and production build passed. |
| Real customer browser | **PASS:** four submitted questions, four HTTP 200 responses with `answer_mode=ai`; no mocked provider responses. `hello` produced an uncited cautious response; the three business-document questions returned citations. |
| English delivery facts | **PASS:** JOD 2 delivery, JOD 30 free-delivery threshold and 14:00 cutoff match `company-and-delivery.md`. |
| Arabic | **PASS:** Arabic delivery follow-up and a bilingual returns question received Arabic answers. Returns facts match `returns-and-stock.md`: 7 days with receipt and 48-hour damage reporting. This is bounded acceptance, not exhaustive cross-language recall certification. |
| Sources/history | **PASS:** every returned document title/excerpt matches that tenant's stored chunk. Eight persisted messages reload; citation panels work at English desktop 1366px and Arabic mobile/RTL 390px. Read-only follow-up checks made no extra generation requests. |
| Accounting | **PASS:** five consumed provider ledger entries for four questions (the greeting used the existing answer-repair pass), unique idempotency keys, 0.1322 AI Credits consumed, zero reserved. Balance agrees with ledger credits; USD 0.001321 metered aggregate agrees at the existing per-settlement six-decimal precision. This is KEEL metering, not a provider-invoice certification. |
| Failure/security | **PASS, isolated tests:** missing/unpriced provider, 401 provider failure, budget denial, no price/no provider call/no charge, persisted question, refunded plan allowance, cross-tenant session 404, document/role isolation and existing credits/RLS regressions. The real demo Tenant Owner also receives the expected `/platform/me` 403. |
| Phase 1 preservation | **PASS:** identical before/after fingerprints for products, inventory, invoices/items, transactions, RAG metadata/chunks, forecasts, competitors/prices, subscriptions/payments/trial and plan assignment. Only normal chat, usage and approved AI-credit consumption were added. |

Private local evidence (not tracked): `.dev/evidence/rag-503/`; backend run `.dev/evidence/tests/deccae268537/`. A database backup and full restore comparison of 139 tables passed before rate configuration. Credentials, tokens, private fixtures, backups and response files are excluded from Git.

## Runtime and remaining limitations

The verified owned API alone was restarted with the fix. The frontend remains `http://127.0.0.1:5173`, API `http://127.0.0.1:8000`; eight existing worker processes were preserved. No Stripe operation was performed.

- `sentence_transformers` is unavailable: semantic embeddings and cross-encoder reranking are not verified. Existing keyword retrieval and fallback ranking supported the demonstrated document answers. Enabling the optional models is a separate, explicitly approved installation; it is not required to resolve this 503.
- Groq returned temporary HTTP 429 responses during the run. Existing bounded retry recovered. Future rate limits, provider outages, depleted credits or missing cost configuration must still produce truthful errors/fallbacks.
- Cached input retains the existing conservative input-price fallback; this change configures only the two expressly approved rates. No new discount or pricing policy was introduced.
- RAG chat currently uses ordinary JSON responses, not SSE streaming. History and references were verified against the implemented contract.
- No further Platform Owner configuration is required for this demonstrated model in this local database. Other providers/models still need independently verified costs and appropriate credentials.

**Verdict: PASS for the reported 503 remediation and the bounded real RAG workflow.** This is not certification of every RAG language, model or external dependency.
