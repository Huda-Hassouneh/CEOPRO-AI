"""
CEOPRO AI - RAG. Runs the unmodified CEOPRO-AI RAG code over the documents supplied with the request:
  ingest:    src/ai/rag/pipeline.ingest_pending_documents()  -> data_access.fetch_document_text, chunking, embeddings.embed,
                                                              data_access.replace_document_chunks
  retrieve:  src/ai/rag/pipeline.run_retrieval()             -> BM25Plus + FAISS hybrid, RRF fusion, Cross-Encoder rerank,
                                                              context assembly
  answer:    src/ai/rag/llm_client._generate_answer_with_usage() (Groq, GROQ_MODEL default openai/gpt-oss-20b)
answer_query() in llm_client is exactly run_retrieval + structured facts + _generate_answer_with_usage; it's split here only
so retrieval and the Groq call stay separately visible. Structured facts need the tenant's live database,
which a public endpoint doesn't have, so include_structured_facts is off (the documented flag for that case).
"""
import base64
import json
import os
import uuid

import gradio as gr

from memdb import MemConn
from src.ai.rag import data_access as rag_data_access
from src.ai.rag import embeddings, llm_client, reranking
from src.ai.rag import pipeline as rag_pipeline
from src.ai.rag.retrieval_types import ScoredChunk

MAX_DOCS = 10
MAX_DOC_BYTES = 2 * 1024 * 1024
MAX_PASSAGES = 50

# Load both retrieval models once at startup (same module-level caches the pipeline uses).
_EMB = embeddings.get_model()
_RR = reranking.get_model()
# On ZeroGPU hardware torch.cuda.is_available() is True in the main process, so sentence-transformers'
# get_device_name() places both models on "cuda" - which only exists inside @spaces.GPU workers. These
# services run in the main process on CPU (CEOPRO-AI's specified target), so pin the cached models to CPU.
_EMB.to("cpu")
_RR.to("cpu")


def _revision(model):
    try:
        cfg = model[0].auto_model.config if hasattr(model, "__getitem__") else model.model.config
        return getattr(cfg, "_commit_hash", None) or "unknown"
    except Exception:
        return "unknown"


EMBEDDING_REVISION = _revision(_EMB)
RERANKER_REVISION = _revision(_RR)

EXAMPLE_DOCS = [
    {"file_name": "returns_policy.txt", "text": (
        "CEOPRO Store return policy. Customers may return any unopened product within 14 days of purchase with the original "
        "receipt for a full refund. Opened electronics can be exchanged within 7 days if defective. Olive oil and other food "
        "products cannot be returned once opened. Refunds are issued to the original payment method within 5 business days.")},
    {"file_name": "delivery_ar.txt", "text": (
        "سياسة التوصيل: نوصل الطلبات داخل عمّان خلال 24 ساعة، وإلى باقي محافظات الأردن خلال 3 أيام عمل. "
        "التوصيل مجاني للطلبات التي تزيد قيمتها عن 30 دينار أردني، ورسوم التوصيل 2.5 دينار للطلبات الأقل من ذلك.")},
    {"file_name": "loyalty.md", "text": (
        "# Loyalty program\nMembers earn 1 point per 1 JOD spent. 100 points can be redeemed for a 5 JOD voucher. "
        "Points expire 12 months after they are earned. Gold members (over 1,000 points per year) get free delivery on every order.")},
]


class _ObjectStore:
    """In-memory stand-in for the MinIO client: holds this request's uploaded document bytes."""
    class _Resp:
        def __init__(self, data):
            self._d = data

        def read(self):
            return self._d

        def close(self):
            pass

        def release_conn(self):
            pass

    def __init__(self):
        self.objects = {}

    def get_object(self, bucket, key):
        return self._Resp(self.objects[(bucket, key)])


def _normalise_docs(documents):
    docs = []
    for i, d in enumerate(documents or []):
        if not isinstance(d, dict):
            raise gr.Error(f"Document #{i + 1} must be an object with file_name and text (or content_base64).")
        name = os.path.basename(str(d.get("file_name") or f"document_{i + 1}.txt"))
        ext = os.path.splitext(name)[1].lower()
        if ext not in rag_data_access.SUPPORTED_DOCUMENT_EXTENSIONS:
            raise gr.Error(f"{name}: unsupported type; supported {sorted(rag_data_access.SUPPORTED_DOCUMENT_EXTENSIONS)}")
        if d.get("content_base64"):
            try:
                data = base64.b64decode(d["content_base64"], validate=True)
            except Exception:
                raise gr.Error(f"{name}: content_base64 is not valid base64.")
        else:
            data = str(d.get("text") or "").encode("utf-8")
        if len(data) > MAX_DOC_BYTES:
            raise gr.Error(f"{name}: exceeds {MAX_DOC_BYTES} bytes.")
        docs.append((f"doc-{i + 1}", name, data))
    if not docs:
        raise gr.Error("Provide at least one document.")
    if len(docs) > MAX_DOCS:
        raise gr.Error(f"At most {MAX_DOCS} documents per request.")
    return docs


def _inserted_chunks(conn):
    # replace_document_chunks() issues DELETE then INSERT; only the inserted rows are chunks.
    return [c for c in conn.persisted if c["table"] == "rag_document_chunks" and "op" not in c]


def _ingest_and_retrieve(docs, question, top_k):
    tenant_id = f"req-{uuid.uuid4()}"
    store = _ObjectStore()
    status = {}
    for doc_id, name, data in docs:
        store.objects[(rag_pipeline.DEFAULT_BUCKET, f"{tenant_id}/{doc_id}/{name}")] = data

    def pending(q, params):
        return [(doc_id, name, f"{tenant_id}/{doc_id}/{name}", "Pending") for doc_id, name, _ in docs if doc_id not in status]

    def chunks(q, params):
        return [(c["id"], c["chunk_text_content"], c["embedding"]) for c in _inserted_chunks(conn)]

    conn = MemConn([(r"FROM rag_documents_metadata", pending), (r"FROM rag_document_chunks", chunks)])
    try:
        processed = rag_pipeline.ingest_pending_documents(conn, store, tenant_id)
        for p in conn.persisted:
            if p["table"] == "rag_documents_metadata" and p.get("op") == "UPDATE":
                status[p["params"][1]] = p["params"][0]
        context = rag_pipeline.run_retrieval(conn, tenant_id, question, top_k=top_k)
    finally:
        rag_pipeline.invalidate_tenant_index_cache(tenant_id)
    chunk_text = {c["id"]: (c["document_id"], c["chunk_index"], c["chunk_text_content"]) for c in _inserted_chunks(conn)}
    return processed, status, context, chunk_text


def rag_answer(documents: list, question: str, top_k: int = 5, history: list = None) -> dict:
    """Answer a question grounded in the supplied documents (hybrid retrieval + reranking + Groq LLM)."""
    question = (question or "").strip()
    if not question or len(question) > 2000:
        raise gr.Error("question must be 1-2000 characters.")
    top_k = max(1, min(int(top_k or 5), rag_pipeline.DEFAULT_RERANK_CANDIDATES))
    docs = _normalise_docs(documents)
    processed, status, context, chunk_text = _ingest_and_retrieve(docs, question, top_k)
    names = {doc_id: name for doc_id, name, _ in docs}
    sources = [{**s, "document": names.get(chunk_text[s["chunk_id"]][0]), "chunk_index": chunk_text[s["chunk_id"]][1],
                "text": chunk_text[s["chunk_id"]][2]} for s in context.sources]
    try:
        answer, usage = llm_client._generate_answer_with_usage(context, structured_facts="", history=history)
    except llm_client.LLMError as exc:
        raise gr.Error(f"LLM provider error: {exc}")
    return {"answer": answer, "sources": sources, "token_usage": usage, "llm_model": llm_client.MODEL_NAME,
            "embedding_model": embeddings.MODEL_NAME, "embedding_model_revision": EMBEDDING_REVISION,
            "reranker_model": reranking.MODEL_NAME, "reranker_model_revision": RERANKER_REVISION,
            "documents_ingested": processed, "document_status": {names[k]: v for k, v in status.items()}}


def _embed(texts):
    return embeddings.embed(texts)


def embed(texts: list) -> dict:
    """Multilingual sentence embeddings (CEOPRO-AI src/ai/rag/embeddings.embed)."""
    texts = [str(t) for t in (texts or []) if str(t).strip()]
    if not texts or len(texts) > 64:
        raise gr.Error("Provide 1-64 non-empty texts.")
    vecs = _embed(texts)
    return {"model": embeddings.MODEL_NAME, "model_revision": EMBEDDING_REVISION, "dimension": int(vecs.shape[1]),
            "embeddings": [[round(float(x), 6) for x in v] for v in vecs]}


def _rerank(query, candidates, top_k):
    return reranking.rerank(query, candidates, top_k=top_k)


def rerank(query: str, passages: list, top_k: int = 5) -> dict:
    """Cross-Encoder relevance re-ranking of passages for a query (CEOPRO-AI src/ai/rag/reranking.rerank)."""
    passages = [str(p) for p in (passages or []) if str(p).strip()]
    if not (query or "").strip() or not passages or len(passages) > MAX_PASSAGES:
        raise gr.Error(f"Provide a query and 1-{MAX_PASSAGES} passages.")
    cands = [ScoredChunk(chunk_id=str(i), text=p, score=0.0) for i, p in enumerate(passages)]
    ranked = _rerank(query, cands, max(1, min(int(top_k or 5), len(passages))))
    return {"model": reranking.MODEL_NAME, "model_revision": RERANKER_REVISION,
            "results": [{"passage_index": int(c.chunk_id), "text": c.text, "score": round(float(c.score), 6)} for c in ranked]}


def _ui_answer(docs_json, question, top_k):
    try:
        docs = json.loads(docs_json)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Invalid JSON: {exc}")
    out = rag_answer(docs, question, top_k)
    src = [[s["source_index"], s["document"], round(s["score"], 4), s["text"][:300]] for s in out["sources"]]
    return out["answer"], src, out


def _ui_embed(text_block):
    out = embed(text_block.splitlines())
    return f"{len(out['embeddings'])} vectors × {out['dimension']} dims · first values: {out['embeddings'][0][:6]}", out


def _ui_rerank(query, passages_block, top_k):
    out = rerank(query, passages_block.splitlines(), top_k)
    return [[r["passage_index"], r["score"], r["text"]] for r in out["results"]], out


def build_ui():
    gr.Markdown("## CEOPRO AI - RAG\nCEOPRO-AI retrieval-augmented answering (`src/ai/rag/`): chunking, "
                f"`{embeddings.MODEL_NAME}` embeddings, BM25Plus + FAISS hybrid retrieval with RRF fusion, "
                f"`{reranking.MODEL_NAME}` re-ranking, and the Groq LLM (`{llm_client.MODEL_NAME}`).")
    with gr.Tab("Ask (full RAG)"):
        d_in = gr.Code(json.dumps(EXAMPLE_DOCS, indent=1, ensure_ascii=False), language="json",
                       label='Documents: [{"file_name": "x.txt", "text": "..."}] (.txt/.md, or content_base64 for .pdf/.docx/.xlsx)')
        q_in = gr.Textbox(value="Can I return an opened bottle of olive oil, and how long does delivery to Irbid take?", label="Question")
        k_in = gr.Slider(1, 10, value=4, step=1, label="top_k")
        b = gr.Button("Ask", variant="primary")
        ans = gr.Markdown(label="Answer")
        src = gr.Dataframe(headers=["source", "document", "rerank score", "chunk text"], label="Sources", wrap=True)
        raw = gr.JSON(label="Raw output")
        b.click(_ui_answer, [d_in, q_in, k_in], [ans, src, raw], api_name="rag_answer_ui")
    with gr.Tab("Embeddings"):
        e_in = gr.Textbox(lines=4, label="Texts (one per line)", value="Premium olive oil 1L\nزيت زيتون ممتاز لتر واحد")
        e_b = gr.Button("Embed", variant="primary")
        e_md = gr.Markdown()
        e_raw = gr.JSON(label="Raw output")
        e_b.click(_ui_embed, e_in, [e_md, e_raw], api_name="embed_ui")
    with gr.Tab("Reranker"):
        r_q = gr.Textbox(value="How long does delivery take?", label="Query")
        r_p = gr.Textbox(lines=5, label="Passages (one per line)", value=(
            "Members earn 1 point per 1 JOD spent.\nنوصل الطلبات داخل عمّان خلال 24 ساعة\n"
            "Refunds are issued within 5 business days.\nDelivery to other governorates takes 3 business days."))
        r_k = gr.Slider(1, 10, value=3, step=1, label="top_k")
        r_b = gr.Button("Rerank", variant="primary")
        r_t = gr.Dataframe(headers=["passage", "score", "text"], label="Ranked")
        r_raw = gr.JSON(label="Raw output")
        r_b.click(_ui_rerank, [r_q, r_p, r_k], [r_t, r_raw], api_name="rerank_ui")
    gr.api(rag_answer, api_name="rag_answer")
    gr.api(embed, api_name="embed")
    gr.api(rerank, api_name="rerank")
