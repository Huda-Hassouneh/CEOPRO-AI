# RAG Pipeline — Setup & Query Guide

End-to-end retrieval-augmented generation: document ingestion → persisted hybrid (BM25 + FAISS)
retrieval → Cross-Encoder re-ranking → context assembly → LLM reasoning (Groq-hosted Qwen). See
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
| `GROQ_API_KEY` | Yes, for `/rag/query` | — | **You must provide this.** Get one at [console.groq.com](https://console.groq.com/) |
| `GROQ_MODEL` | No | `qwen/qwen3-32b` | Verify this is still current against Groq's [model catalog](https://console.groq.com/docs/models) before relying on it — hosted catalogs change |
| `RAG_EMBEDDING_MODEL` | No | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Dense retrieval embedding model |
| `RAG_RERANKER_MODEL` | No | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Multilingual Cross-Encoder (spec §8 Arabic-English requirement — do not swap for an English-only reranker) |

`GROQ_API_KEY` is the only one of these you actually need to go find and set yourself — everything
else has a working default. **Why Groq + Qwen, not a locally-run model**: Groq's hardware-accelerated
hosted inference is fast (low per-token latency), Qwen at this size is accurate on multilingual/
cross-dialect Arabic content, and because the model runs on Groq's infrastructure rather than
yours, there is zero local GPU/CPU/RAM footprint — the only thing your machine does is send and
receive text over HTTPS. See [`llm_client.py`](llm_client.py)'s module docstring for the full
reasoning.

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
generate_answer()  -- Groq API call (Qwen), the only LLM-aware step in this whole path
        |
{"answer": ..., "sources": [...]}
```
