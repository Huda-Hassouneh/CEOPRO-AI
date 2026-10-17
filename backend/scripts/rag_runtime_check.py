"""
KEEL - RAG runtime check: the real models, a real database, and (when a key
is set) the real LLM, with the memory each stage costs.

Answers three questions the unit tests can't, because they mock the models:

1. Does semantic retrieval really work? A document is ingested through the
   real ingestion path, its chunks must get stored vectors, and an Arabic
   question that shares no word with the English document must still find
   it. Keyword search (BM25) can't, so a hit proves the embedding model did
   the work.
2. How much memory does the assistant need? Resident memory is printed after
   importing the ai app, after loading the embedding model and (when
   enabled) the re-ranker, plus the process's peak, so a host's limit
   (Render's free plan: 512 MB) is checked against measured numbers. Runs
   with whatever RAG_EMBEDDING_BACKEND / RAG_RERANKER_ENABLED say.
   --compare-onnx (torch backend only) also runs the app's ONNX backend in
   fresh processes for each export and reports their peak memory and how
   close their vectors are to the torch model's.
3. With GROQ_API_KEY (or another configured provider) set: does the
   assistant answer from that document, in AI mode, citing it?

Needs AI_TEST_DATABASE_URL (a migrated test database - it seeds its own
tenant) and network access to the Hugging Face hub. Exits 1 with the reason
when a check fails; never reports a pass it didn't observe.

    python -m scripts.rag_runtime_check [--compare-onnx] [--max-peak-mb N]
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
SENTENCES = [DOCUMENT, CROSS_LINGUAL_QUESTION, "Which products are most profitable?"]
ONNX_FILES = ("onnx/model_quint8_avx2.onnx", "onnx/model_qint8_avx512_vnni.onnx", "onnx/model.onnx")

# Runs in a fresh process: the app's own embeddings module with the backend
# the environment selects, so its peak memory is its own.
_CHILD = r"""
import json, sys
from src.ai.rag import embeddings
from scripts.rag_runtime_check import _status_mb
vectors = embeddings.embed(json.loads(sys.argv[1]))
print(json.dumps({"backend": embeddings.BACKEND, "peak_mb": _status_mb("VmHWM"), "vectors": vectors.tolist()}))
"""


def _status_mb(field: str) -> float:
    """VmRSS (now) or VmHWM (this process's peak) from /proc - unlike
    getrusage's maxrss, VmHWM is not inherited from a parent process."""
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith(field + ":"):
                return int(line.split()[1]) / 1024
    return 0.0


class _Object(io.BytesIO):
    def release_conn(self):
        pass


class _Storage:
    """Stands in for MinIO: the check is about retrieval, not object storage."""

    def get_object(self, bucket, key):
        return _Object(DOCUMENT.encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--compare-onnx", action="store_true", help="Also measure the ONNX backend in fresh processes")
    parser.add_argument("--max-peak-mb", type=float, help="Fail when this process's peak memory exceeds this")
    args = parser.parse_args()
    database_url = os.getenv("AI_TEST_DATABASE_URL")
    if not database_url:
        print("FAIL: AI_TEST_DATABASE_URL is not set")
        return 1

    failures = []
    memory = {"baseline": _status_mb("VmRSS")}
    import src.ai.main  # noqa: F401 - the whole ai app, as the service boots it

    memory["after_importing_the_ai_app"] = _status_mb("VmRSS")
    from src.ai.rag import embeddings, pipeline, reranking

    print(f"Embedding backend: {embeddings.BACKEND}"
          + (f" ({embeddings.ONNX_FILE})" if embeddings.BACKEND == "onnx" else "") + f", model {embeddings.MODEL_NAME}")
    print(f"Re-ranker: {reranking.MODEL_NAME if pipeline.RERANKER_ENABLED else 'disabled (RAG_RERANKER_ENABLED)'}")
    try:
        embeddings.get_model()
        memory["after_embedding_model"] = _status_mb("VmRSS")
        if pipeline.RERANKER_ENABLED:
            reranking.get_model()
            memory["after_reranker"] = _status_mb("VmRSS")
    except Exception as exc:  # noqa: BLE001 - the reason is the result
        print(f"FAIL: a model could not be loaded: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    print("Resident memory (MB):", json.dumps({k: round(v) for k, v in memory.items()}))
    print("torch imported:", "torch" in sys.modules)

    import psycopg2
    from src.ai.rag import advisor, bm25_index, llm_client
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
        print("  tokens the keyword index saw:", bm25_index.tokenize(CROSS_LINGUAL_QUESTION))
        if keyword_hits:
            print("  (BM25 matched something, so this run doesn't isolate the semantic path)")
        if not found:
            failures.append("semantic retrieval did not find the document for a cross-lingual question")

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
        with conn.cursor() as cursor:  # the seeded tenant's other rows stay, as with run_eval
            cursor.execute("DELETE FROM rag_documents_metadata WHERE document_id = %s;", (document_id,))
        conn.commit()
    finally:
        conn.close()

    peak = _status_mb("VmHWM")
    print(f"\nPeak resident memory of this process: {round(peak)} MB")
    if args.max_peak_mb and peak > args.max_peak_mb:
        failures.append(f"peak memory {round(peak)} MB is over the {round(args.max_peak_mb)} MB limit")
    if args.compare_onnx:
        if embeddings.BACKEND == "onnx":
            print("--compare-onnx needs the torch backend as the reference; skipped")
        else:
            failures += compare_onnx(embeddings.embed(SENTENCES))

    if failures:
        print("\nFAIL:\n- " + "\n- ".join(failures))
        return 1
    print("\nPASS")
    return 0


def compare_onnx(reference) -> list:
    """The app's ONNX backend for each export, each in a fresh process."""
    import numpy as np

    failures = []
    for file_name in ONNX_FILES:
        env = {**os.environ, "RAG_EMBEDDING_BACKEND": "onnx", "RAG_EMBEDDING_ONNX_FILE": file_name}
        run = subprocess.run([sys.executable, "-c", _CHILD, json.dumps(SENTENCES)], env=env,
                             capture_output=True, text=True, timeout=900)
        if run.returncode != 0:
            last = run.stderr.strip().splitlines()[-1] if run.stderr.strip() else f"exit {run.returncode}"
            print(f"ONNX {file_name}: failed - {last}")
            failures.append(f"the ONNX backend failed with {file_name}")
            continue
        out = json.loads(run.stdout.strip().splitlines()[-1])
        cosine = [round(float(np.dot(a, b)), 4) for a, b in zip(np.array(out["vectors"], dtype=np.float32), reference)]
        print(f"ONNX {file_name}: embedder process peak {round(out['peak_mb'])} MB, cosine vs torch {cosine}")
        if min(cosine) < 0.97:
            failures.append(f"ONNX {file_name} vectors drift from the torch model's (min cosine {min(cosine)})")
    return failures

if __name__ == "__main__":
    sys.exit(main())
