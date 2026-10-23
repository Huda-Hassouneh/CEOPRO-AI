# RAG Pipeline — Setup & Query Guide

End-to-end retrieval-augmented generation: document ingestion → persisted hybrid (BM25 + FAISS)
retrieval → Cross-Encoder re-ranking → context assembly → LLM reasoning (Groq-hosted by default, or
a local zero-cost `llama.cpp` server - see below). See
[`../README.md`](../README.md#rag--phase-3-groundwork-retrieval-only-spec-4-6-21) for the
module-by-module breakdown of how each stage works; this file is the practical "how do I actually
run this" guide.

## 1. Setup

```bash
pip install -r src/ai/requirements.txt
python scripts/apply_migrations.py   # needs DATABASE_URL + APP_DB_PASSWORD set
```

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` / `APP_DB_PASSWORD` | Yes | — | Postgres connection (see repo root `.env.example`) |
| `MINIO_ENDPOINT` / `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Yes, for ingestion | — | Raw document storage |
| `GROQ_API_KEY` | Yes, for `/rag/query` — unless `LOCAL_LLM_BASE_URL` is set instead | — | **You must provide this** unless using the local option below. Get one at [console.groq.com](https://console.groq.com/) |
| `GROQ_MODEL` | No | `openai/gpt-oss-20b` | Live-verified 2026-09-03 against Groq's real API with a real key after `llama-3.1-8b-instant`/`llama-3.3-70b-versatile` both started returning 404 — hosted catalogs change, re-check [the model list](https://console.groq.com/docs/models) before relying on this long-term |
| `GROQ_MAX_TOKENS` | No | `1500` | Caps response length. Was `400` until a real live-Groq verification pass (2026-09-26) found `gpt-oss-20b`'s hidden reasoning tokens are billed out of this same budget - a long RAG prompt could exhaust it entirely before the model ever emitted a visible answer (a real, observed empty `content` with `completion_tokens` pinned at the old cap). `1500` gives real headroom for both the reasoning phase and the answer that follows it. |
| `LOCAL_LLM_BASE_URL` | No | unset (uses Groq) | Set to route generation at a local `llama.cpp` server instead — see "Zero-cost local LLM option" below |
| `LOCAL_LLM_TIMEOUT_SECONDS` | No | `90` | Only applies when `LOCAL_LLM_BASE_URL` is set — local generation is genuinely slower than Groq's hosted hardware |
| `PAID_LLM_BASE_URL` / `PAID_LLM_API_KEY` / `PAID_LLM_MODEL` | No | unset (uses Groq/local) | The flexible placeholder for swapping Groq for a paid subscription vendor later — see "Swapping in a paid provider later" below |
| `RAG_EMBEDDING_MODEL` | No | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Dense retrieval embedding model |
| `RAG_RERANKER_MODEL` | No | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Multilingual Cross-Encoder (spec §8 Arabic-English requirement — do not swap for an English-only reranker) |

By default you only need to go find and set `GROQ_API_KEY` yourself — everything else has a
working default. **Why Groq by default, not a locally-run model**: Groq's hardware-accelerated
hosted inference is fast (low per-token latency), the model is accurate on multilingual/
cross-dialect Arabic content, and because it runs on Groq's infrastructure rather than yours,
there is zero local GPU/CPU/RAM footprint. See [`llm_client.py`](llm_client.py)'s module docstring
for the full reasoning.

### Zero-cost local LLM option (full data privacy, no external API call)

For a $0 budget or a hard requirement that no query/document text ever leaves your own
infrastructure, run a local `llama.cpp` server instead:

```bash
pip install huggingface_hub
python scripts/download_local_llm_model.py          # one-time, ~2.3GB
docker compose --profile local-llm up llm-local      # or run llama-server directly, see that script
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8090/v1/chat/completions   # 127.0.0.1 if outside Docker
```

Live-verified 2026-09-06 on real hardware (i5-1135G7, 4-core/8-thread CPU, Qwen2.5-3B-Instruct
Q5_K_M): ~6 tokens/sec generation, a real 32.6s for one full grounded answer through the then-current
answer code path — correct, coherent, correctly cited. Genuinely slower than Groq;
that's the real trade for zero cost and full privacy, not a bug. This was a single smoke test, not
an accuracy evaluation — a real side-by-side comparison against Groq's answers on a batch of
questions is the honest next step for quantified confidence, not yet done.

### Swapping in a paid provider later

Groq stays the active default. When a paid subscription is actually provisioned (OpenAI,
Together AI, Azure OpenAI, Fireworks, or any other vendor that speaks the same OpenAI-compatible
`/v1/chat/completions` schema Groq and llama-server already do), point the model call (`llm_client._chat_completion_with_usage()`) at it
with three env vars and nothing else changes:

```bash
export PAID_LLM_BASE_URL=https://api.your-paid-vendor.example/v1/chat/completions
export PAID_LLM_API_KEY=your-real-key-here
export PAID_LLM_MODEL=vendor/model-name   # optional — defaults to GROQ_MODEL's value
```

`PAID_LLM_BASE_URL` takes priority over both Groq and `LOCAL_LLM_BASE_URL` when set, and is unset
by default (zero behavior change until a real vendor is chosen). A vendor with a genuinely
different request/response schema — Anthropic's Messages API, Google's Gemini API — needs its own
code path in [`llm_client.py`](llm_client.py), not just these env vars; that is a real vendor
decision this pass deliberately leaves open, the same way `credential_vault.py` leaves the choice
of a HashiCorp Vault backend open.

## 2. Ingest a document

```python
import psycopg2
from minio import Minio
from src.ai.rag import pipeline

conn = psycopg2.connect("postgresql://ceopro_app:...@localhost:5432/ceopro_platform")
minio_client = Minio("localhost:9000", access_key="...", secret_key="...", secure=False)

# rag_documents_metadata needs a row with processed_status='Pending' first
# (however your upload flow creates that row) - this call does the rest:
# fetch from MinIO -> chunk -> embed -> persist to rag_document_chunks -> mark Processed/Failed.
processed_count = pipeline.ingest_pending_documents(conn, minio_client, tenant_id="...")
print(f"Ingested {processed_count} document(s)")
```

## 3. Test and query the model

The assistant is the evidence-first advisor in `advisor.py`. `llm_client.answer_query()` is a thin
wrapper around it, kept for existing callers.

```python
# query_example.py
import psycopg2
from src.ai.rag import advisor

conn = psycopg2.connect("postgresql://ceopro_app:...@localhost:5432/ceopro_platform")
# Row-level security needs app.current_tenant_id / app.current_user_id set on the connection
# (db.app_role_connection does this for the API).

result = advisor.answer(
    conn,
    tenant_id="00000000-0000-0000-0000-000000000000",
    question="How were my sales in the last 30 days?",
    user_id="00000000-0000-0000-0000-000000000001",   # the member's role decides what may be read
)

print(result["answer"])        # text with superscript reference markers
print(result["references"])    # numbered references behind those markers
```

Main fields of `result`:

| Field | Meaning |
|---|---|
| `answer` | Plain text with superscript markers (¹ ² …), for clients that cannot render blocks. |
| `answer_summary` | The short answer (one or two checked claims) shown first when the full answer is long; `null` when the answer is already short. The model writes it as the first field of its JSON; otherwise it is the answer's first statements. In evidence mode it is the one sentence that best matches the question. `answer` and `answer_blocks` stay the full answer. In evidence mode `note` is `"source_language"` when the quoted sentence is in another language than the question (section 7). |
| `answer_blocks` | Headings, paragraphs, lists and tables made of claims; each claim lists its reference numbers, its kind (fact, calculation, regulation, recommendation, …) and whether it was verified. |
| `references` | Numbered by first use: title, kind, credibility, excerpt, page or screen link, source URL, publication and retrieval dates, limitations, and the calculation trace for calculated figures. |
| `calculations` | Deterministic landed-cost results (steps, inputs, missing inputs, assumptions, sensitivity). |
| `evidence_status` | What was looked for and what was found, missing, or not permitted for this role. |
| `research` | Outcome of public research (`not_needed`, `not_configured`, `budget_exhausted`, `no_results`, `found`, …). |
| `follow_up_questions` | Suggested next questions. |
| `answer_mode` | `advisor`, or a fallback (`evidence_mode`, `unverifiable`, `unlinked`) when the model is unavailable or its claims could not be checked. |
| `state` | Intents and slots carried into the next question of the same conversation. |

### Via the HTTP endpoint

With `src/ai/main.py` running (`./keel start`, `uvicorn src.ai.main:app`, or the `ai` service in
`docker-compose.yml`), the assistant page calls the chat endpoint in `routers/rag.py`; it stores each
answer with its references and the conversation state, so reopened conversations keep their
citations. A provider failure returns the evidence found, labelled as such, instead of an error.

### Interactive terminal chat (`chat_cli.py`)

A standalone REPL for manually driving `/rag/query` like a real chat session - type a question,
see the answer and cited sources, type another, `exit` to quit. Zero extra dependencies (httpx +
PyJWT, both already in `requirements.txt`); it mints its own test JWT locally rather than needing
a real login flow (see `main.py`'s own docstring - no JWT-issuing service exists yet).

```bash
# Terminal 1 - start the service
export DATABASE_URL=... APP_DB_PASSWORD=... JWT_SECRET=... GROQ_API_KEY=...
uvicorn src.ai.main:app --host 127.0.0.1 --port 8000

# Terminal 2 - chat
export JWT_SECRET=...            # must match terminal 1's JWT_SECRET
export AI_TENANT_ID=<a real tenant_id with ingested RAG documents>
export AI_USER_ID=<any tenant_users.user_id for that tenant>
python -m src.ai.rag.chat_cli
```

```text
Connected to http://localhost:8000 as tenant <tenant_id>. Type 'exit' to quit.

You: What are our best selling products?

Assistant: Sunscreen SPF 50 is our best seller, based on the retrieved sales notes.

Sources:
  [1] chunk=3fa85f64-5717-4562-b3fc-2c963f66afa6 score=0.87

You: exit
Goodbye.
```

`AI_SERVICE_URL` overrides the default `http://localhost:8000` if the service is running elsewhere.

## 4. Running the tests

```bash
# Offline (no real models, no network - mocked HTTP for the LLM call, injected fake
# scorers for re-ranking):
python -m pytest src/ai/tests/test_rag_*.py src/ai/tests/test_main.py -q

# Live-DB, without downloading real models (Postgres + MinIO required):
AI_TEST_DATABASE_URL=postgresql://... APP_DB_PASSWORD=... \
AI_TEST_MINIO_ENDPOINT=localhost:9000 \
  python -m pytest src/ai/tests/test_rag_integration.py -q

# Live-DB, full pipeline including a real embedding model + a real Cross-Encoder
# download (~1-2 min extra, first run only - cached after):
AI_TEST_DATABASE_URL=postgresql://... APP_DB_PASSWORD=... \
AI_TEST_MINIO_ENDPOINT=localhost:9000 \
AI_TEST_EMBEDDINGS=1 AI_TEST_RERANKING=1 \
  python -m pytest src/ai/tests/test_rag_integration.py -q
```

There is no equivalent live-gated test for a real Groq call — that needs a real `GROQ_API_KEY`
only you can provision. `test_rag_llm_client.py` covers `llm_client.py`'s logic with a mocked HTTP
layer instead; run the "Test and query the model" snippet above with a real key to verify the
actual provider call yourself.

## 5. Architecture summary

```text
question (+ previous turn's state)
   |
understanding.py      intents (sales, pricing, trade, regulation, research, ...) and slots
                      (countries, period, quantity, money amounts, rates, HS code, incoterm, URLs)
   |
access.py             the member's role -> capabilities (owner/admin/manager: all;
                      accountant: sales, costs, catalog, inventory, forecasts, documents;
                      staff: catalog and inventory only)
   |
advisor.py: gather company evidence the role may see
   |-- structured_context.build_fact_sections()   live sales, sentiment, competitors, price gaps,
   |                                              forecasts, insights (read-only)
   |-- business analysis / orchestrator / financial blocks (business_tools.py)
   |-- uploaded documents via run_retrieval() (BM25 + FAISS + RRF + Cross-Encoder), with page numbers
   |-- products, reviews, product guide (how-to questions)
   |
research/ (only when the question needs public information or nothing internal was found)
   |-- plan_queries()   private figures stripped; official sites first for trade/regulation
   |-- web_search       daily and per-company search budgets
   |-- page_reader.read()  SSRF check on every redirect, robots.txt, no logins or paywalls
   |-- research_pages   shared cache of public pages only (no tenant, user or question stored)
   |
trade/landed_cost.py  deterministic landed cost: CIF/FOB customs value, ad-valorem and specific
                      duty, excise, sales tax, fees, per-unit cost, comparison, break-even,
                      sensitivity. Missing inputs are listed, never guessed.
   |
EvidenceRegistry (evidence.py)  every item numbered E1..En with kind, credibility, dates, link
   |
LLM (JSON claims citing E-ids) -> citations.validate()
   |   numbers must appear in (or be derived from) the cited evidence, quotes must match,
   |   links must belong to cited evidence; one repair round, then fallback modes
   |
citations.render()  numbered references + blocks -> frontend markers and reference panel
```

The model never does arithmetic: every computed figure comes from `trade/landed_cost.py` or from
the company records, and a claim whose numbers cannot be traced to its evidence is removed.

## 6. Unified context: scraped market data + internal sales history

The real fix for "the chatbot must leverage the interplay between internal sales history and
external market/competitor data" (previously true only via a hand-built function bolted onto the
answer afterward, bypassing retrieval entirely): **`structured_summaries.py`** and
**`structured_context.py`** are the two halves of a deliberate hybrid design, not a single
mechanism — see each module's own docstring for the full reasoning, summarized here:

- **`structured_summaries.py`** turns structured data into real narrative text — sales history
  (`invoices`/`invoice_items`), the confirmed competitor landscape (`tenant_competitors`/
  `global_competitors`, tier/scope/distance), sentiment trends (`sentiment_results`, reusing
  `sentiment/pipeline.py::get_subject_sentiment_summary()` — never a re-derived number), and market
  pricing (`products.current_price` vs. `competitor_prices`) — and ingests it through the **exact
  same** `ingest_pending_documents()` pipeline a human-uploaded file goes through. This is what
  makes "what's been happening with sentiment about my competitors" answerable by ordinary hybrid
  retrieval, same as a question about an uploaded PDF. Each summary type is one stable per-tenant
  "slot" (`_generated/<slot>.txt`) — `regenerate_all_structured_summaries(conn, minio_client,
  tenant_id)` overwrites it and re-arms ingestion (`processed_status` back to `'Pending'`); call it
  on a schedule (after a scraping/sentiment run, or nightly), never accumulating duplicate documents.
- **`structured_context.py::build_structured_facts_block()`** is the other half: real, CURRENT
  numbers (current sentiment score, competitor tier counts, live price gaps) queried fresh on
  **every** chat question and injected directly into the LLM prompt as a second, separately-labeled
  section — never chunked or embedded. This is deliberate, not an oversight: an LLM asked for an
  exact number should never have to rely on semantic search having retrieved the one chunk with the
  precise right figure, a well-documented RAG failure mode for numeric precision. The advisor reads
  these facts through `build_fact_sections()`, one section per topic, each filtered by the member's
  role and linked to the screen it comes from. When nothing internal answers the question, it
  researches public sources or says exactly what is missing instead of giving up.

**Known, flagged gap**: neither `regenerate_all_structured_summaries()` nor the four narrative
generators are yet wired into an automatic schedule (a cron/webhook after a scraping run) — they're
real, tested, callable functions, just not yet triggered automatically end-to-end.

## 7. Evidence mode: design decisions

Evidence mode answers from the gathered evidence with no model call. It is used when the model cannot write the
answer: no key, no confirmed price, a rate limit, an outage, or nothing that passes the claim checks.

**D1. Its summary is extractive, never model-written (PENDING_ACTIONS #139).** The summary is the best-matching
sentence of the best-matching item (plurals folded), or, for a question sharing no word with the evidence (Arabic
about English documents), the start of a document that retrieval already matched by meaning. A model call to improve
it was rejected: this mode exists exactly when the model is unavailable, so the call could fail the same way, it
would cost tokens on the path that is meant to cost none, and the answer would stop being traceable to a quoted
source. Guardrails: no summary unless the top item is known to answer the question (a confident but unrelated
line is worse than none), whitespace from PDF text is collapsed, and the summary is at most about 220 characters.
Revisit only if users report broad questions ("give me an overview") reading poorly, and then as an opt-in model
step with its own budget, never on this path.

**D2. A summary in another language than the question is labelled, not translated (#140).** The summary quotes
the source, so an Arabic question about an English document gets an English sentence. Translating needs the model
(see D1), so `answer_summary.note = "source_language"` is set and the chat shows a one-line note in the user's
language. A model-written answer follows the question's language already (see `SYSTEM_PROMPT`) and gets no note.
The check is `advisor._flag_foreign_summary`, by script (`product_guide.question_language`), so it is free.

**Observability.** One log line per answer (`assistant_answer mode=... summary=model|extractive|fallback|none`,
logger `KEEL_ADVISOR`) is the source for the post-deploy numbers (PENDING_ACTIONS #151).
