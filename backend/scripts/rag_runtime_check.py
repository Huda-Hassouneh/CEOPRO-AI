"""
KEEL - RAG runtime check: the real models, a real database, and (when a key
is set) the real LLM, with the memory each stage costs.

Answers three questions the unit tests can't, because they mock the models:

1. Does semantic retrieval really work? A document is ingested through the
   real ingestion path, its chunks must get stored vectors, and an Arabic
   question that shares no word with the English document must still find
   it. Keyword search (BM25) can't, so a hit proves the embedding model did
   the work.
2. How much memory does the assistant's retrieval stack need? Resident
   memory is printed after importing torch, after loading the embedding
   model and after loading the re-ranker, so a host's limit (Render's free
   plan has 512 MB) can be checked against measured numbers. --probe-onnx
   also measures the same embedding model's int8 ONNX export in a separate
   process without torch.
3. With GROQ_API_KEY (or another configured provider) set: does the
   assistant answer from that document, in AI mode, citing it?

Needs AI_TEST_DATABASE_URL (a migrated test database - it seeds its own
tenant) and network access to the Hugging Face hub. Exits 1 with the reason
when a check fails; never reports a pass it didn't observe.

    python -m scripts.rag_runtime_check [--probe-onnx]
"""
import argparse
import io
import json
import os
import subprocess
import sys
import uuid

DOCUMENT = ("Supplier agreement summary. Our supplier Al-Noor Trading delivers every Tuesday. "
            "The minimum order with Al-Noor Trading is 250 JOD and the payment terms are net 45 days. "
            "Late deliveries earn a 3 percent discount on that invoice.")
# "What are the payment terms with the supplier?" - no word in common with DOCUMENT.
CROSS_LINGUAL_QUESTION = "ما هي شروط الدفع مع المورد؟"

ONNX_PROBE = r"""
import json, os, resource, sys
import numpy as np, onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer
model, file_name = sys.argv[1], sys.argv[2]
tok = Tokenizer.from_file(hf_hub_download(model, "tokenizer.json"))
tok.enable_padding(); tok.enable_truncation(256)
session = ort.InferenceSession(hf_hub_download(model, file_name), providers=["CPUExecutionProvider"])
enc = tok.encode_batch(json.loads(sys.argv[3]))
ids = np.array([e.ids for e in enc], dtype=np.int64); mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
feeds = {"input_ids": ids, "attention_mask": mask}
if "token_type_ids" in {i.name for i in session.get_inputs()}:
    feeds["token_type_ids"] = np.zeros_like(ids)
hidden = session.run(None, feeds)[0]
pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
pooled /= np.linalg.norm(pooled, axis=1, keepdims=True)
print(json.dumps({"peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, "vectors": pooled.tolist()}))
"""


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / (1024 * 1024)


def _peak_mb() -> float:
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class _Object(io.BytesIO):
    def release_conn(self):
        pass


class _Storage:
    """Stands in for MinIO: the check is about retrieval, not object storage."""

    def get_object(self, bucket, key):
        return _Object(DOCUMENT.encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--probe-onnx", action="store_true", help="Also measure the int8 ONNX embedder without torch")
    args = parser.parse_args()
    database_url = os.getenv("AI_TEST_DATABASE_URL")
    if not database_url:
        print("FAIL: AI_TEST_DATABASE_URL is not set")
        return 1

    failures = []
    memory = {"baseline": _rss_mb()}
    import torch  # noqa: F401 - measured on its own: every model below needs it

    memory["after_import_torch"] = _rss_mb()
    from src.ai.rag import embeddings, reranking

    try:
        embeddings.get_model()
        memory["after_embedding_model"] = _rss_mb()
        reranking.get_model()
        memory["after_reranker"] = _rss_mb()
    except Exception as exc:  # noqa: BLE001 - the reason is the result
        print(f"FAIL: a model could not be loaded: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    print("Embedding model:", embeddings.MODEL_NAME)
    print("Re-ranker:      ", reranking.MODEL_NAME)
    print("Resident memory (MB):", json.dumps({k: round(v) for k, v in memory.items()}))

    import psycopg2
    from src.ai.rag import advisor, bm25_index, pipeline
    from src.ai.rag.eval.run_eval import _seed_live_tenant

    conn = psycopg2.connect(database_url)
    try:
        tenant = _seed_live_tenant(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO rag_documents_metadata (tenant_id, file_name, storage_bucket_path, file_size_bytes, content_type) "
                "VALUES (%s, 'supplier_agreement.txt', %s, %s, 'text/plain') RETURNING document_id;",
                (tenant, f"{tenant}/supplier_agreement_{uuid.uuid4().hex[:8]}.txt", len(DOCUMENT)),
            )
            document_id = cursor.fetchone()[0]
        conn.commit()
        processed = pipeline.ingest_pending_documents(conn, _Storage(), tenant)
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*), count(embedding) FROM rag_document_chunks WHERE tenant_id = %s;", (tenant,))
            chunks, with_vectors = cursor.fetchone()
        print(f"Ingested {processed} document(s): {chunks} chunk(s), {with_vectors} with a stored vector")
        if not processed or not chunks or with_vectors != chunks:
            failures.append("ingestion did not store a vector for every chunk")

        index = pipeline.build_hybrid_index(conn, tenant, use_cache=False)
        keyword_hits = [c for c in index.bm25.query(CROSS_LINGUAL_QUESTION, top_k=5) if c.score > 0]
        context = pipeline.run_retrieval(conn, tenant, CROSS_LINGUAL_QUESTION, top_k=3)
        found = "net 45 days" in context.context_text
        print(f"Arabic question vs English document: keyword hits={len(keyword_hits)}, "
              f"retrieved={len(context.sources)}, document found={found}")
        if keyword_hits:
            print("  (BM25 matched something, so this run doesn't isolate the semantic path)")
        if not found:
            failures.append("semantic retrieval did not find the document for a cross-lingual question")
        print("Tokens the keyword index saw in the question:", bm25_index.tokenize(CROSS_LINGUAL_QUESTION))

        from src.ai.rag import llm_client

        if os.getenv("GROQ_API_KEY") or llm_client.LOCAL_LLM_BASE_URL or llm_client.PAID_LLM_BASE_URL:
            for question in (CROSS_LINGUAL_QUESTION, "Which products are most profitable?"):
                result = advisor.answer(conn, tenant, question, enable_research=False)
                conn.rollback()
                titles = [r.get("title") for r in result["references"]]
                print(f"\nQ: {question}\n   mode={result['answer_mode']} tokens={result['token_usage']['total_tokens']} "
                      f"citation_issues={result['citation_check']['issues']} references={titles}")
                print("   A:", result["answer"][:400].replace("\n", " "))
                if result["answer_mode"] != "ai":
                    failures.append(f"assistant answered in {result['answer_mode']} mode for {question!r}")
                if question == CROSS_LINGUAL_QUESTION and not any("supplier_agreement" in str(t) for t in titles):
                    failures.append("the assistant's answer to the document question did not cite the document")
        else:
            print("\nLLM check skipped: no provider configured (GROQ_API_KEY unset)")
        with conn.cursor() as cursor:  # leave nothing behind but the seeded tenant's own rows
            cursor.execute("DELETE FROM rag_documents_metadata WHERE document_id = %s;", (document_id,))
        conn.commit()
    finally:
        conn.close()

    print(f"\nPeak resident memory of this process: {round(_peak_mb())} MB")
    if args.probe_onnx:
        probe_onnx()

    if failures:
        print("\nFAIL:\n- " + "\n- ".join(failures))
        return 1
    print("\nPASS: semantic retrieval with stored vectors" +
          (", AI answers citing the document" if os.getenv("GROQ_API_KEY") else ""))
    return 0


def probe_onnx():
    """The same embedding model's int8 ONNX export, in a fresh process with no
    torch: its peak memory, and how close its vectors are to the torch model's."""
    import numpy as np
    from src.ai.rag import embeddings

    sentences = [DOCUMENT, CROSS_LINGUAL_QUESTION, "Which products are most profitable?"]
    reference = embeddings.embed(sentences)
    for file_name in ("onnx/model_qint8_avx512_vnni.onnx", "onnx/model_quint8_avx2.onnx", "onnx/model.onnx"):
        run = subprocess.run([sys.executable, "-c", ONNX_PROBE, embeddings.MODEL_NAME, file_name, json.dumps(sentences)],
                             capture_output=True, text=True, timeout=600)
        if run.returncode != 0:
            print(f"ONNX {file_name}: failed - {run.stderr.strip().splitlines()[-1] if run.stderr.strip() else run.returncode}")
            continue
        out = json.loads(run.stdout.strip().splitlines()[-1])
        vectors = np.array(out["vectors"], dtype=np.float32)
        cosine = [round(float(np.dot(a, b)), 4) for a, b in zip(vectors, reference)]
        print(f"ONNX {file_name}: peak memory {round(out['peak_rss_mb'])} MB, cosine vs torch model {cosine}")


if __name__ == "__main__":
    sys.exit(main())
