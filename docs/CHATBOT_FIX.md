# Chatbot fix: the assistant only cited evidence, never wrote an answer

Investigated 2026-10-31 against `origin/main` (the branch Render deploys), on a local throwaway stack. Fix on
branch `fix/chatbot`.

## Symptom

The AI assistant returned a list of retrieved evidence ("The assistant's writing service is unavailable right
now, so here is the evidence KEEL found…") instead of a written, model-composed answer — even where
`GROQ_API_KEY` is set and valid (Render, Codespaces, GitHub secrets).

## Root cause (a deployment-data bug, not a missing key)

The assistant meters every model call through the billing layer. Migration
`20261028000000_seed_unpriced_groq_rows.sql` seeds the price of the default model `groq / openai/gpt-oss-20b`
as **NULL**, by design ("don't call a paid API at an unknown cost"). The billing gate
(`backend/src/ai/billing/credits.py::_cost`) raises `COST_NOT_CONFIGURED` on any NULL unit price **before** the
model is ever called, and the advisor (`backend/src/ai/rag/advisor.py`) then degrades to "evidence mode".

So on any deployment that ran migrations but never had an operator run `scripts/billing_admin set-price`, the
assistant **never calls the model at all**, regardless of the API key. The key is not the blocker — the NULL
price is. (The same pattern now also affects the newer vision/menu models, seeded NULL by
`20261118000000`.)

This is separate from, and upstream of, any key problem: the gate refuses the call before authentication.

## Fix

`backend/src/infrastructure/database/migrations/20261119000000_set_groq_gpt_oss_20b_price.sql` sets Groq's
published list price for `openai/gpt-oss-20b` — input **$0.075 / 1M**, output **$0.30 / 1M**, cached input
**$0.037 / 1M** (source: `console.groq.com/docs/model/openai/gpt-oss-20b`, verified 2026-11-19), stored per
token. The gate then allows the call and bills it accurately. Idempotent, reversible
(`rollback/20261119000000_…down.sql`), and an operator can change the rate anytime with
`python -m scripts.billing_admin set-price --budget ai --provider groq --operation openai/gpt-oss-20b --unit input_token --usd-per-million <rate>`.
No app restart is needed — the price is read per request.

## Test evidence (local throwaway stack, pre-main running code, identical gate + provider logic)

**1. Reproduced the bug and proved the fix removes the blocker** (Groq provider, company "MT Alpha"):

| State | `answer_mode` | Server log |
|---|---|---|
| Groq price NULL (as shipped) | `evidence` | `refused by the server's billing setup: COST_NOT_CONFIGURED (no confirmed input_token price for groq/openai/gpt-oss-20b)` |
| After the migration (price set) | `evidence` | `LLM provider (…/chat/completions) returned 401: Invalid API Key` |

The error **moves** from "pricing not configured" to "the model API rejected the key". The gate is no longer
the blocker; the request now actually reaches Groq. In this sandbox the injected Groq credential is a
non-`gsk_` placeholder, so Groq returns 401 and the call still can't complete here — but that is a sandbox
credential limitation, not the code or the user's real keys.

**2. Proved the full pipeline composes a real model-backed answer** (local OpenAI-compatible stand-in model on
the identical `/v1/chat/completions` code path, `GROQ_API_KEY` unset, Groq price set):

- Four questions — English, Arabic, a multi-source question, and a follow-up in the same session — all returned
  **`answer_mode=ai`** (a real provider round-trip, composed and citation-verified), not evidence mode.
- The exact prompt sent to the model (captured) contained company Alpha's own SQL + RAG evidence: its products,
  its `market pricing` and `sales history` summaries, its 30-day sales records, and its confidential document
  `alpha_confidential_pricing.pdf` (markers `Alpha Signature`, `ALPHA-SECRET`, minimum price `17.35`, supplier
  `Harar`).
- **No other company's confidential data** was in the prompt: none of company B's secret markers
  (`BETA-SECRET`, `Sidamo`, `JUNIPER`, supplier cost `5.03`, `Omar Khalil`) appeared. (`Beta Dark Roast 1kg`
  is a product Alpha itself owns, created in an earlier isolation test; both companies have their own row.)

The stand-in model is **not** a real LLM; it exists only to exercise the production pipeline (retrieval →
prompt assembly → HTTP model call → response parsing → citation verification → composed answer) when no real
model credential is available. It proves the code path works end to end; it does not prove Groq's answer
quality.

## What is verified vs. what still needs a valid key

- **Verified here:** the NULL-price gate was the blocker; the migration removes it; the request reaches the
  model API after the fix; the full compose-and-verify pipeline works end to end and delivers the correct
  company's SQL+RAG evidence with no cross-tenant leakage; English, Arabic, follow-up and multi-source
  questions all route through the model path.
- **Not verifiable in this sandbox (no working model credential here):** an actual Groq-generated answer. This
  must be confirmed on Render/Codespaces, where `GROQ_API_KEY` is valid, by asking the assistant a question and
  seeing a written answer (`answer_mode` = `ai`). The code reads the correct variable names (`GROQ_API_KEY`,
  `GROQ_MODEL` default `openai/gpt-oss-20b`, `GROQ_TIMEOUT_SECONDS` default 20s); the model id is a current,
  supported Groq model.
- **Web research (Tavily):** the assistant's optional public-research step reads `TAVILY_API_KEY` (correct
  name). It is only for public market info, not for company-specific SQL/RAG answers, so it does not cause the
  evidence-mode symptom. If research specifically is not working in a deployment, confirm `TAVILY_API_KEY`
  reaches that service's environment.
