"""The ONNX embedding backend's own steps (tokenize, run, mean-pool over real
tokens, normalize) with a stand-in runtime, and the re-ranker switch. The
real models are exercised by scripts/rag_runtime_check.py."""
import sys
import types

import numpy as np

from src.ai.rag import embeddings, pipeline
from src.ai.rag.retrieval_types import ScoredChunk


class _Encoding:
    def __init__(self, ids, mask):
        self.ids, self.attention_mask = ids, mask


class _Tokenizer:
    truncated_to = None

    @classmethod
    def from_file(cls, path):
        return cls()

    def enable_truncation(self, max_length):
        _Tokenizer.truncated_to = max_length

    def enable_padding(self):
        pass

    def encode_batch(self, texts):
        # "a b" -> two real tokens; every batch padded to its longest text.
        width = max(len(t.split()) for t in texts)
        return [_Encoding([1] * width, [1] * len(t.split()) + [0] * (width - len(t.split()))) for t in texts]


class _Session:
    batches = []

    def __init__(self, path, options, providers):
        self.path, self.options = path, options

    def get_inputs(self):
        return [types.SimpleNamespace(name=n) for n in ("input_ids", "attention_mask", "token_type_ids")]

    def run(self, outputs, feeds):
        assert set(feeds) == {"input_ids", "attention_mask", "token_type_ids"}
        _Session.batches.append(len(feeds["input_ids"]))
        batch, width = feeds["input_ids"].shape
        # Token j of every text has hidden state [j + 1, 0]; padding would drag the mean if counted.
        hidden = np.zeros((batch, width, 2), dtype=np.float32)
        hidden[:, :, 0] = np.arange(1, width + 1)
        return [hidden]


def _stub_runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(InferenceSession=_Session,
                                                                         SessionOptions=types.SimpleNamespace))
    monkeypatch.setitem(sys.modules, "tokenizers", types.SimpleNamespace(Tokenizer=_Tokenizer))
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, name: f"/cache/{repo}/{name}")
    _Session.batches = []


def test_onnx_encoder_mean_pools_real_tokens_and_normalizes(monkeypatch):
    _stub_runtime(monkeypatch)
    encoder = embeddings._OnnxEncoder("org/model", "onnx/model.onnx", max_seq_length=256)
    vectors = encoder.encode(["a b c", "a"])
    assert _Tokenizer.truncated_to == 256
    assert vectors.dtype == np.float32 and vectors.shape == (2, 2)
    # Padding ignored: "a" pools only its own token, so both normalize to [1, 0].
    np.testing.assert_allclose(vectors, [[1.0, 0.0], [1.0, 0.0]], atol=1e-6)
    raw = encoder.encode(["a b c"], normalize_embeddings=False)
    np.testing.assert_allclose(raw, [[2.0, 0.0]])  # mean of 1, 2, 3


def test_onnx_encoder_works_in_bounded_batches(monkeypatch):
    _stub_runtime(monkeypatch)
    encoder = embeddings._OnnxEncoder("org/model", "onnx/model.onnx", max_seq_length=128)
    vectors = encoder.encode(["word"] * 70)
    assert vectors.shape == (70, 2) and _Session.batches == [32, 32, 6]


def test_onnx_backend_loads_the_export_without_torch(monkeypatch):
    _stub_runtime(monkeypatch)
    monkeypatch.setattr(embeddings, "BACKEND", "onnx")
    monkeypatch.setattr(embeddings, "ONNX_FILE", "onnx/model_quint8_avx2.onnx")
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # importing it would raise
    model = embeddings._load("org/model")
    assert isinstance(model, embeddings._OnnxEncoder)
    assert model._session.path == "/cache/org/model/onnx/model_quint8_avx2.onnx"
    options = model._session.options  # memory over speed on a small host
    assert options.enable_cpu_mem_arena is False and options.enable_mem_pattern is False
    assert options.intra_op_num_threads == embeddings._ONNX_THREADS


def test_onnx_backend_checks_for_the_export_it_will_load(monkeypatch):
    seen = {}
    monkeypatch.setattr(embeddings, "BACKEND", "onnx")
    monkeypatch.setattr(embeddings, "ONNX_FILE", "onnx/model.onnx")
    monkeypatch.setattr(embeddings, "_model_cache", {})
    monkeypatch.setattr(embeddings, "_unavailable_until", 0.0)
    monkeypatch.setattr("src.ai.core.ml_runtime.model_obtainable",
                        lambda name, weights=(): seen.update(name=name, weights=weights) or False)
    assert embeddings.try_embed(["text"], "org/model") is None
    assert seen == {"name": "org/model", "weights": ("onnx/model.onnx",)}


def test_retrieval_skips_a_disabled_reranker(monkeypatch):
    chunks = [ScoredChunk(chunk_id=f"c{i}", text=f"text {i}", score=1.0 / (i + 1)) for i in range(5)]
    monkeypatch.setattr(pipeline, "build_hybrid_index", lambda conn, tenant: None)
    monkeypatch.setattr(pipeline, "retrieve_hybrid", lambda index, query, top_k: chunks)

    def rerank(*args, **kwargs):
        raise AssertionError("the re-ranker must not load when disabled")

    monkeypatch.setattr(pipeline, "rerank", rerank)
    monkeypatch.setattr(pipeline, "RERANKER_ENABLED", False)
    context = pipeline.run_retrieval(None, "t", "question", top_k=2)
    assert [s["chunk_id"] for s in context.sources] == ["c0", "c1"]


def test_a_switched_off_backend_never_loads_a_model(monkeypatch):
    """RAG_EMBEDDING_BACKEND=none (a host too small for any model): keyword
    search only, without the load attempt that would exhaust its memory."""
    monkeypatch.setattr(embeddings, "BACKEND", "none")
    monkeypatch.setattr(embeddings, "_model_cache", {})
    monkeypatch.setattr(embeddings, "_load", lambda name: (_ for _ in ()).throw(AssertionError("must not load")))
    monkeypatch.setattr("src.ai.core.ml_runtime.model_obtainable",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not probe")))
    assert embeddings.try_embed(["text"]) is None


def _tiny_static_model(tmp_path):
    """A 4-token static model, 3 wide, saved the way the real one is published."""
    from safetensors.numpy import save_file
    from tokenizers import Tokenizer, models, pre_tokenizers

    weights = tmp_path / "model.safetensors"
    save_file({"embedding.weight": np.array([[0, 0, 9], [1, 0, 9], [0, 1, 9], [1, 1, 9]], dtype=np.float32)}, str(weights))
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "pay": 1, "terms": 2, "supplier": 3}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(tmp_path / "tokenizer.json"))
    return {"0_StaticEmbedding/model.safetensors": str(weights), "0_StaticEmbedding/tokenizer.json": str(tmp_path / "tokenizer.json")}


def test_static_model_is_prepared_once_as_its_first_dims_and_averaged(monkeypatch, tmp_path):
    import huggingface_hub

    files = _tiny_static_model(tmp_path)
    downloads = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, name: downloads.append(name) or files[name])
    for name, value in (("STATIC_MODEL", "org/static"), ("STATIC_DIM", 2), ("STATIC_DIR", str(tmp_path / "prepared"))):
        monkeypatch.setattr(embeddings, name, value)
    meta = embeddings.prepare_static()
    assert meta == {"model": "org/static", "dim": 2, "rows": 4}
    embeddings.prepare_static()
    assert len(downloads) == 2  # already prepared: nothing downloaded again

    encoder = embeddings._StaticEncoder()
    assert encoder._matrix.dtype == np.float16 and encoder._matrix.shape == (4, 2)
    vectors = encoder.encode(["pay terms", "supplier", ""], normalize_embeddings=False)
    np.testing.assert_allclose(vectors, [[0.5, 0.5], [1.0, 1.0], [0.0, 0.0]])  # 3rd column dropped
    normalized = encoder.encode(["pay terms"])
    np.testing.assert_allclose(np.linalg.norm(normalized, axis=1), 1.0, rtol=1e-6)


def test_static_backend_labels_vectors_with_model_and_width():
    import importlib
    import os

    os.environ["RAG_EMBEDDING_BACKEND"] = "static"
    try:
        module = importlib.reload(embeddings)
        assert module.MODEL_NAME == f"{module.STATIC_MODEL}@{module.STATIC_DIM}"
    finally:
        os.environ.pop("RAG_EMBEDDING_BACKEND")
        importlib.reload(embeddings)


def test_advisor_keeps_a_chunk_close_in_meaning_even_with_no_shared_word(monkeypatch):
    """An Arabic question about an English document shares no word with it;
    the word check alone would drop the very match semantic search found."""
    from src.ai.rag import advisor

    # Low absolute similarities, as the static model gives: the closest
    # retrieved chunk counts, one far behind it doesn't, nor one under the floor.
    vectors = {"ما هي شروط الدفع؟": [1.0, 0.0, 0.0], "payment terms are net 45 days": [0.2, 0.98, 0.0],
               "leave policy": [0.12, 0.99, 0.0], "summer campaign": [0.05, 0.0, 1.0]}
    monkeypatch.setattr(embeddings, "try_embed", lambda texts: np.array([vectors[t] for t in texts], dtype=np.float32))
    monkeypatch.setattr(advisor, "SEMANTIC_MIN_SIMILARITY", 0.15)
    monkeypatch.setattr(advisor, "SEMANTIC_MARGIN", 0.05)
    assert not advisor._relevant("ما هي شروط الدفع؟", "payment terms are net 45 days")
    close = advisor._semantic_check("ما هي شروط الدفع؟", ["payment terms are net 45 days", "leave policy", "summer campaign"])
    assert close("payment terms are net 45 days")
    assert not close("leave policy")  # 0.12: under the floor and 0.08 behind the best
    assert not close("summer campaign")


def test_a_word_matched_chunk_stops_the_best_leftover_passing_as_relevant(monkeypatch):
    """Retrieval returned the leave policy (shares words) and a supplier agreement (shares one). The agreement
    is the best of the leftovers, which used to be enough to show it for a leave question."""
    from src.ai.rag import advisor

    question = "How many days of annual leave does an employee get?"
    leave = "Staff handbook, time off. Every employee receives 21 days of paid annual leave each year."
    supplier = "Supplier agreement summary. The payment terms are net 45 days."
    vectors = {question: [1.0, 0.0], leave: [0.9, 0.44], supplier: [0.3, 0.95]}
    monkeypatch.setattr(embeddings, "try_embed", lambda texts: np.array([vectors[t] for t in texts], dtype=np.float32))
    admits = advisor._chunk_filter(question, [leave, supplier])
    assert admits(leave)
    assert not admits(supplier)


def test_advisor_semantic_check_is_off_without_an_embedding_model(monkeypatch):
    from src.ai.rag import advisor

    monkeypatch.setattr(embeddings, "try_embed", lambda texts: None)
    assert advisor._semantic_check("any question", ["a chunk"]) is None


def test_evidence_mode_keeps_the_matched_document_among_many_records():
    """A question matching no topic (an Arabic leave question) brings every
    record section; without an LLM, the document that answers it must still
    be among the sources shown."""
    from src.ai.rag import advisor
    from src.ai.rag import evidence as ev

    registry = ev.EvidenceRegistry()
    for n in range(12):
        registry.add(ev.COMPANY_RECORD, f"Record {n}", f"line {n}", ev.COMPANY, ev.OBSERVED)
    registry.add(ev.COMPANY_DOCUMENT, "leave_policy.pdf", "21 days of paid annual leave", ev.COMPANY, ev.OBSERVED)
    draft = advisor._evidence_mode(registry, "en")
    shown = [claim[0].text for claim in draft.blocks[1]["items"]]
    assert len(shown) == 8
    assert shown[-1].startswith("leave_policy.pdf")  # still after the records, as ranked
    assert shown[0].startswith("Record 0")
