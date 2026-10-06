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
import io
import json
import os
import uuid
import zipfile

import gradio as gr

from memdb import MemConn
from src.ai.rag import data_access as rag_data_access
from src.ai.rag import embeddings, llm_client, reranking
from src.ai.rag import pipeline as rag_pipeline
from src.ai.rag.chunking import DEFAULT_CHUNK_SIZE_WORDS, chunk_text as rag_chunk_text
from src.ai.rag.retrieval_types import ScoredChunk

MAX_DOCS = 10
# Upload limits, chosen from live measurements on this Space (see
# deploy/huggingface_spaces/UPLOAD_LIMITS.md). Request time is driven by how
# much TEXT has to be embedded on this Space's CPU, not by the file size, so
# there is also a per-request chunk budget: a 20 MB plain-text document
# (~22,000 chunks, measured 137 s end to end) fits it, ten of them would not.
MAX_DOC_MB = int(os.getenv("RAG_MAX_DOC_MB", "20"))
MAX_DOC_BYTES = MAX_DOC_MB * 1024 * 1024
MAX_REQUEST_MB = int(os.getenv("RAG_MAX_REQUEST_MB", "100"))
MAX_REQUEST_BYTES = MAX_REQUEST_MB * 1024 * 1024
MAX_REQUEST_CHUNKS = int(os.getenv("RAG_MAX_REQUEST_CHUNKS", "25000"))
# .docx/.xlsx are zip archives; a 20 MB one can unpack to gigabytes (zip bomb).
MAX_UNPACKED_MB = 512
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
    docs, total = [], 0
    for i, d in enumerate(documents or []):
        if not isinstance(d, dict):
            raise gr.Error(f"Document #{i + 1} must be an object with file_name and text (or content_base64).")
        name = os.path.basename(str(d.get("file_name") or f"document_{i + 1}.txt"))
        ext = os.path.splitext(name)[1].lower()
        if ext not in rag_data_access.SUPPORTED_DOCUMENT_EXTENSIONS:
            raise gr.Error(f"{name}: unsupported type; supported {sorted(rag_data_access.SUPPORTED_DOCUMENT_EXTENSIONS)}")
        if len(docs) >= MAX_DOCS:
            raise gr.Error(f"At most {MAX_DOCS} documents per request.")
        if d.get("content_base64"):
            encoded = str(d["content_base64"])
            size = len(encoded) // 4 * 3 - (len(encoded) - len(encoded.rstrip("=")))
            if size > MAX_DOC_BYTES:  # checked before decoding
                raise gr.Error(_too_large(name, size))
            try:
                data = base64.b64decode(encoded, validate=True)
            except Exception:
                raise gr.Error(f"{name}: content_base64 is not valid base64.")
        else:
            data = str(d.get("text") or "").encode("utf-8")
        if len(data) > MAX_DOC_BYTES:
            raise gr.Error(_too_large(name, len(data)))
        total += len(data)
        if total > MAX_REQUEST_BYTES:
            raise gr.Error(f"The documents total more than {MAX_REQUEST_MB} MB; the maximum per request is {MAX_REQUEST_MB} MB "
                           f"({MAX_DOC_MB} MB per document). Send fewer documents per request.")
        docs.append((f"doc-{i + 1}", name, data))
    if not docs:
        raise gr.Error("Provide at least one document.")
    return docs


def _too_large(name, size):
    return f"{name}: file is {size / 1048576:.1f} MB; the maximum is {MAX_DOC_MB} MB ({MAX_DOC_BYTES} bytes) per document."


def _check_unpacked_size(name, data):
    try:
        unpacked = sum(m.file_size for m in zipfile.ZipFile(io.BytesIO(data)).infolist())
    except zipfile.BadZipFile:
        return  # not a valid archive: extraction fails and the document is marked Failed, as before
    if unpacked > MAX_UNPACKED_MB * 1048576:
        raise gr.Error(f"{name}: unpacks to {unpacked / 1048576:.0f} MB; the maximum is {MAX_UNPACKED_MB} MB. "
                       "Split the document or save it as PDF or text.")


def _extract_and_budget(docs):
    """Extracts each document's text once, with the pipeline's own extractor
    (data_access.fetch_document_text), and enforces MAX_REQUEST_CHUNKS before
    any embedding starts. Returns the object key and bytes the pipeline should
    ingest: the extracted text as UTF-8 (so it isn't extracted a second time;
    fetch_document_text() of a .txt key is exactly .decode("utf-8")), or the
    original bytes when extraction fails, so the pipeline marks that document
    Failed exactly as before."""
    store, staged, chunks = _ObjectStore(), [], 0
    for doc_id, name, data in docs:
        if os.path.splitext(name)[1].lower() in (".docx", ".xlsx"):
            _check_unpacked_size(name, data)
        key = f"{doc_id}/{name}"
        store.objects[(rag_pipeline.DEFAULT_BUCKET, key)] = data
        try:
            text = rag_data_access.fetch_document_text(store, rag_pipeline.DEFAULT_BUCKET, key)
        except Exception:
            staged.append((doc_id, name, name, data))
            continue
        chunks += len(rag_chunk_text(text))
        if chunks > MAX_REQUEST_CHUNKS:
            raise gr.Error(f"The documents contain too much text for one request (more than {MAX_REQUEST_CHUNKS} passages of "
                           f"~{DEFAULT_CHUNK_SIZE_WORDS} words, "
                           f"about 20 MB of plain text). Send fewer or shorter documents per request.")
        staged.append((doc_id, name, f"{name}.txt" if os.path.splitext(name)[1].lower() not in (".txt", ".md") else name,
                       text.encode("utf-8")))
    return staged


def _inserted_chunks(conn):
    # replace_document_chunks() issues DELETE then INSERT; only the inserted rows are chunks.
    return [c for c in conn.persisted if c["table"] == "rag_document_chunks" and "op" not in c]


def _ingest_and_retrieve(docs, question, top_k):
    tenant_id = f"req-{uuid.uuid4()}"
    store = _ObjectStore()
    status = {}
    staged = _extract_and_budget(docs)
    for doc_id, name, key_name, data in staged:
        store.objects[(rag_pipeline.DEFAULT_BUCKET, f"{tenant_id}/{doc_id}/{key_name}")] = data

    def pending(q, params):
        return [(doc_id, name, f"{tenant_id}/{doc_id}/{key_name}", "Pending") for doc_id, name, key_name, _ in staged if doc_id not in status]

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
