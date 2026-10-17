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
# "none": don't load an embedding model at all - keyword search only, for a
# host that can't hold one (trying would get the process killed for memory).
# "static": a static multilingual embedding model - per-token vectors averaged,
# no transformer, no torch - so semantic search fits a 512 MB host. Default
# sentence-transformers/static-similarity-mrl-multilingual-v1 (Apache-2.0),
# trained on parallel sentences in 50 languages including Arabic, so an
# Arabic question still finds an English document. Matryoshka-trained, so its
# first STATIC_DIM dimensions are a usable embedding: 384 fills the existing
# vector(384) column. Prepared once (prepare_static(), done at image build)
# into a float16 matrix that is memory-mapped, not loaded.
BACKEND = os.getenv("RAG_EMBEDDING_BACKEND", "torch").strip().lower()
DISABLED_BACKENDS = ("none", "off", "disabled")
STATIC_MODEL = os.getenv("RAG_STATIC_EMBEDDING_MODEL", "sentence-transformers/static-similarity-mrl-multilingual-v1")
STATIC_DIM = int(os.getenv("RAG_STATIC_EMBEDDING_DIM", "384"))
STATIC_DIR = os.getenv("RAG_STATIC_EMBEDDING_DIR",
                       os.path.join(os.path.expanduser("~"), ".cache", "keel", "static-embeddings"))
if BACKEND == "static":
    # Also what each stored vector is labelled with (embedding_model_version),
    # so vectors from another model are re-embedded rather than compared.
    MODEL_NAME = f"{STATIC_MODEL}@{STATIC_DIM}"
ONNX_FILE = os.getenv("RAG_EMBEDDING_ONNX_FILE", "onnx/model_quint8_avx2.onnx")
_ONNX_BATCH = 32
_ONNX_THREADS = int(os.getenv("RAG_EMBEDDING_ONNX_THREADS", "1"))

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
        options = onnxruntime.SessionOptions()
        # Memory over speed: no pre-grown arena or per-shape memory plans
        # (they hold hundreds of MB between calls), and one thread.
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.intra_op_num_threads = _ONNX_THREADS
        self._session = onnxruntime.InferenceSession(hf_hub_download(model_name, file_name), options,
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


def _static_paths(model: str, dim: int, directory: str):
    stem = os.path.join(directory, model.replace("/", "--") + f"-{dim}")
    return stem + ".npy", stem + ".tokenizer.json", stem + ".json"


def prepare_static(model: str = None, dim: int = None, directory: str = None) -> dict:
    """Writes the static model's first `dim` dimensions as a float16 matrix
    next to its tokenizer, once. Reads the published weights in row blocks,
    so the full 1024-wide float32 matrix (~430 MB) is never in memory."""
    import json
    import shutil

    model, dim, directory = model or STATIC_MODEL, dim or STATIC_DIM, directory or STATIC_DIR
    matrix_path, tokenizer_path, meta_path = _static_paths(model, dim, directory)
    if os.path.exists(meta_path):
        with open(meta_path) as handle:
            return json.load(handle)
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open

    os.makedirs(directory, exist_ok=True)
    weights = hf_hub_download(model, "0_StaticEmbedding/model.safetensors")
    tokenizer = hf_hub_download(model, "0_StaticEmbedding/tokenizer.json")
    partial = matrix_path + ".partial.npy"
    with safe_open(weights, framework="numpy") as tensors:
        table = tensors.get_slice(next(iter(tensors.keys())))
        rows, width = table.get_shape()
        if dim > width:
            raise ValueError(f"{model} has {width} dimensions, fewer than {dim}")
        out = np.lib.format.open_memmap(partial, mode="w+", dtype=np.float16, shape=(rows, dim))
        for start in range(0, rows, 8192):
            end = min(start + 8192, rows)  # safetensors slices don't clamp
            out[start:end] = table[start:end, :dim].astype(np.float16)
        out.flush()
        del out
    os.replace(partial, matrix_path)
    shutil.copyfile(tokenizer, tokenizer_path)
    meta = {"model": model, "dim": dim, "rows": int(rows)}
    with open(meta_path, "w") as handle:  # written last: marks the preparation complete
        json.dump(meta, handle)
    return meta


class _StaticEncoder:
    """sentence-transformers' StaticEmbedding steps: tokenize without special
    tokens or truncation (the whole chunk counts), average the token vectors,
    L2-normalize. Rows are read from the memory-mapped matrix as needed."""

    def __init__(self):
        from tokenizers import Tokenizer

        prepare_static()
        matrix_path, tokenizer_path, _ = _static_paths(STATIC_MODEL, STATIC_DIM, STATIC_DIR)
        self._matrix = np.load(matrix_path, mmap_mode="r")
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        vectors = np.zeros((len(texts), self._matrix.shape[1]), dtype=np.float32)
        for row, encoded in enumerate(self._tokenizer.encode_batch(list(texts), add_special_tokens=False)):
            if encoded.ids:
                vectors[row] = np.asarray(self._matrix[np.asarray(encoded.ids)], dtype=np.float32).mean(axis=0)
        if normalize_embeddings:
            vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        return vectors


def _load(model_name: str):
    if BACKEND == "static":
        return _StaticEncoder()
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
    if BACKEND in DISABLED_BACKENDS:
        raise EmbeddingUnavailable(f"semantic search is switched off (RAG_EMBEDDING_BACKEND={BACKEND})")
    if model_name not in _model_cache:
        if time.monotonic() < _unavailable_until:
            raise EmbeddingUnavailable(f"embedding model {model_name} is unavailable (retrying later)")
        with ML_LOAD_LOCK:  # see core/ml_runtime.py
            if model_name not in _model_cache:
                from src.ai.core.ml_runtime import model_obtainable

                weights = (ONNX_FILE,) if BACKEND == "onnx" else WEIGHT_FILES
                if BACKEND == "static":
                    weights = ("0_StaticEmbedding/model.safetensors",)
                prepared = BACKEND == "static" and os.path.exists(_static_paths(STATIC_MODEL, STATIC_DIM, STATIC_DIR)[2])
                if not prepared and not model_obtainable(STATIC_MODEL if BACKEND == "static" else model_name,
                                                         weights=weights):
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
