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
| `GROQ_MAX_TOKENS` | No | `400` | Caps response length — a real, free latency lever on both backends, not just a Groq nicety |
| `LOCAL_LLM_BASE_URL` | No | unset (uses Groq) | Set to route generation at a local `llama.cpp` server instead — see "Zero-cost local LLM option" below |
| `LOCAL_LLM_TIMEOUT_SECONDS` | No | `90` | Only applies when `LOCAL_LLM_BASE_URL` is set — local generation is genuinely slower than Groq's hosted hardware |
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
Q5_K_M): ~6 tokens/sec generation, a real 32.6s for one full grounded answer through the actual
`generate_answer()` code path — correct, coherent, correctly cited. Genuinely slower than Groq;
that's the real trade for zero cost and full privacy, not a bug. This was a single smoke test, not
an accuracy evaluation — a real side-by-side comparison against Groq's answers on a batch of
questions is the honest next step for quantified confidence, not yet done.

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

This is the exact shape of a real call, end to end — copy this, swap in a real `tenant_id` and
`GROQ_API_KEY`, and run it.

```python
# query_example.py
import os
import psycopg2
from src.ai.rag import llm_client

os.environ["GROQ_API_KEY"] = "your-real-key-here"   # or set it in your shell environment instead

conn = psycopg2.connect("postgresql://ceopro_app:...@localhost:5432/ceopro_platform")

result = llm_client.answer_query(
    conn,
    tenant_id="00000000-0000-0000-0000-000000000000",
    query_text="What is our best selling product this summer?",
    top_k=5,
)

print("Answer: ", result["answer"])
print("Sources:", result["sources"])
```

```bash
python query_example.py
```

Expected shape of `result`:

```json
{
  "answer": "Your best selling summer product is Sunscreen SPF 50, based on the retrieved sales notes.",
  "sources": [
    {"source_index": 1, "chunk_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "score": 0.87}
  ]
}
```

An empty `sources` list with an "I don't have any relevant information..." answer means retrieval
found nothing in that tenant's knowledge base for the query — the LLM was never called (see
`answer_query()`'s own short-circuit).

### Via the HTTP endpoint

With `src/ai/main.py` running (`uvicorn src.ai.main:app`, or the `ai` service in
`docker-compose.yml`):

```bash
curl -X POST "http://localhost:8000/rag/query?query_text=What+is+our+best+selling+product%3F&top_k=5" \
  -H "Authorization: Bearer <your JWT>"
```

Returns the same `{"answer": ..., "sources": [...]}` shape as a JSON response. A Groq/network
failure comes back as HTTP 502 (retrieval succeeded, only the LLM call didn't); anything else
unexpected comes back as 500.

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
Document upload (MinIO)
        |
ingest_pending_documents()  -- chunk, embed, persist (once, at ingest time)
        |
rag_document_chunks (Postgres + pgvector)
        |
run_retrieval()
  |-- build_hybrid_index()        -- read persisted chunks, no MinIO/re-embed
  |-- retrieve_hybrid()           -- BM25 + FAISS, wide candidate pool -> RRF fusion
  |-- rerank()                    -- multilingual Cross-Encoder, narrows to top_k
  |-- assemble_context()          -- source-labeled context text + citations
        |
AssembledContext
        |
generate_answer()  -- Groq API call (Llama), the only LLM-aware step in this whole path
        |
{"answer": ..., "sources": [...]}
```.
