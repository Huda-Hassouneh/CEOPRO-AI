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

    def __init__(self, path, providers):
        self.path = path

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
    monkeypatch.setitem(sys.modules, "onnxruntime", types.SimpleNamespace(InferenceSession=_Session))
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
