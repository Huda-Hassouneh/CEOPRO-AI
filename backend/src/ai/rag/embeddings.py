"""
KEEL - Sentence Embeddings for Semantic Retrieval (spec S4, S6, S21).
Uses a small multilingual Sentence Transformers model (spec S6's stated
default), not an LLM - CPU-friendly (~470MB, seconds-per-batch on CPU), the
"light-medium" tier of the retrieval stack, well below the weight of the
NER/sentiment transformers or a local LLM.
"""

import logging
import os
import threading
import time
from typing import List, Optional

import numpy as np

from src.ai.core.ml_runtime import ML_LOAD_LOCK, WEIGHT_FILES

# sentence_transformers is deliberately NOT imported at module level - this
# module is reached from main.py's own eager router-import chain
# (routers/rag.py -> pipeline.py -> here), so importing it here at all
# means every boot of the ai service pays its cost (it pulls in torch as
# its own backend), whether or not a single RAG request is ever made.
# Measured directly: ~800MB RSS just from import - on Render's free
# 512Mi web service this OOM-kills the process before uvicorn ever binds
# a port. Deferred into get_model() instead (model WEIGHTS were already
# lazily loaded and cached, per its own docstring below - this closes
# the same gap one level up, for the library itself).

# Multilingual (100+ languages incl. Arabic), small enough for CPU inference,
# spec S8's Arabic-English code-switching requirement.
DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)

# How the model runs. "torch" (default): sentence-transformers on torch - torch
# alone is ~520 MB resident and the loaded model ~1.6 GB (measured,
# scripts/rag_runtime_check.py), too much for a 512 MB host. "onnx": the same
# model's ONNX export (shipped in its own Hugging Face repo) on onnxruntime
# with the model's own tokenizer, no torch - same mean pooling and
# normalization, so its vectors match the stored ones (cosine 1.0 for the
# full-precision export, ~0.995 for the 8-bit ones).
BACKEND = os.getenv("RAG_EMBEDDING_BACKEND", "torch").strip().lower()
ONNX_FILE = os.getenv("RAG_EMBEDDING_ONNX_FILE", "onnx/model_quint8_avx2.onnx")
_ONNX_BATCH = 32

# paraphrase-multilingual-MiniLM-L12-v2 defaults to 128 tokens, but chunks are ~200
# words (more tokens in Arabic), so the tail of every chunk was silently never
# embedded. The model's positions support up to 512. 0 = keep the model default.
MAX_SEQ_LENGTH = int(os.getenv("RAG_EMBEDDING_MAX_SEQ_LENGTH", "256"))

_model_cache = {}

logger = logging.getLogger("CEOPRO_AI_RAG_EMBEDDINGS")

# When the model can't be loaded (no network to download it, not enough
# memory on a small host), retrieval falls back to keyword search instead of
# failing every question. The failure is remembered for this long so each
# request doesn't wait out the download retries again.
_RETRY_AFTER_SECONDS = float(os.getenv("RAG_EMBEDDING_RETRY_SECONDS", "600"))
_unavailable_until = 0.0
_unavailable_lock = threading.Lock()


class EmbeddingUnavailable(RuntimeError):
    """The semantic model can't be used right now; keyword search still works."""


class _OnnxEncoder:
    """The model's ONNX export behind the one method embed() uses, with
    sentence-transformers' own steps for this model: tokenize (truncated to
    max_seq_length), run, mean-pool over real tokens, L2-normalize."""

    def __init__(self, model_name: str, file_name: str, max_seq_length: int):
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.max_seq_length = max_seq_length
        self._tokenizer = Tokenizer.from_file(hf_hub_download(model_name, "tokenizer.json"))
        self._tokenizer.enable_truncation(max_seq_length)
        self._tokenizer.enable_padding()
        self._session = onnxruntime.InferenceSession(hf_hub_download(model_name, file_name),
                                                     providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        out = []
        for start in range(0, len(texts), _ONNX_BATCH):  # bounded memory for a large document
            encoded = self._tokenizer.encode_batch(texts[start:start + _ONNX_BATCH])
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(None, feeds)[0]
            pooled = (hidden * mask[..., None]).sum(axis=1) / np.maximum(mask.sum(axis=1, keepdims=True), 1)
            if normalize_embeddings:
                pooled = pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            out.append(pooled)
        return np.concatenate(out).astype(np.float32)


def _load(model_name: str):
    if BACKEND == "onnx":
        # The model's own default (128) when MAX_SEQ_LENGTH is 0, as with torch.
        return _OnnxEncoder(model_name, ONNX_FILE, MAX_SEQ_LENGTH or 128)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    if MAX_SEQ_LENGTH > 0:
        model.max_seq_length = MAX_SEQ_LENGTH
    return model


def get_model(model_name: str = None) -> "SentenceTransformer":
    """
    Lazily loads and caches the model - downloading/loading a transformer on
    every call would defeat the point of a "light" retrieval tier. Cached by
    name so tests can override RAG_EMBEDDING_MODEL without cross-contaminating
    a differently-configured caller in the same process.
    """
    global _unavailable_until
    model_name = model_name or MODEL_NAME
    if model_name not in _model_cache:
        if time.monotonic() < _unavailable_until:
            raise EmbeddingUnavailable(f"embedding model {model_name} is unavailable (retrying later)")
        with ML_LOAD_LOCK:  # see core/ml_runtime.py
            if model_name not in _model_cache:
                from src.ai.core.ml_runtime import model_obtainable

                weights = (ONNX_FILE,) if BACKEND == "onnx" else WEIGHT_FILES
                if not model_obtainable(model_name, weights=weights):
                    with _unavailable_lock:
                        _unavailable_until = time.monotonic() + _RETRY_AFTER_SECONDS
                    logger.error("Embedding model %s is not cached and its host is unreachable; using keyword search only", model_name)
                    raise EmbeddingUnavailable(f"embedding model {model_name} is not cached and its host is unreachable")
                try:
                    _model_cache[model_name] = _load(model_name)
                except Exception as err:
                    with _unavailable_lock:
                        _unavailable_until = time.monotonic() + _RETRY_AFTER_SECONDS
                    logger.error("Embedding model %s could not be loaded; using keyword search only: %s", model_name, err)
                    raise EmbeddingUnavailable(str(err)) from err
    return _model_cache[model_name]


def try_embed(texts: List[str], model_name: str = None) -> Optional[np.ndarray]:
    """embed(), or None when the semantic model is unavailable."""
    try:
        return embed(texts, model_name)
    except EmbeddingUnavailable:
        return None


def embed(texts: List[str], model_name: str = None) -> np.ndarray:
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    model = get_model(model_name)
    vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vectors.astype(np.float32)
