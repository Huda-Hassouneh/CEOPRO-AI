"""
CEOPRO AI - Sentence Embeddings for Semantic Retrieval (spec S4, S6, S21).
Uses a small multilingual Sentence Transformers model (spec S6's stated
default), not an LLM - CPU-friendly (~470MB, seconds-per-batch on CPU), the
"light-medium" tier of the retrieval stack, well below the weight of the
NER/sentiment transformers or a local LLM.
"""

import os
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

# Multilingual (100+ languages incl. Arabic), small enough for CPU inference,
# spec S8's Arabic-English code-switching requirement.
DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_NAME = os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)

MAX_SEQ_LENGTH = int(os.getenv("RAG_EMBEDDING_MAX_SEQ_LENGTH", "256"))  # 0 = keep the model's own default

_model_cache = {}


def get_model(model_name: str = None) -> SentenceTransformer:
    """
    Lazily loads and caches the model - downloading/loading a transformer on
    every call would defeat the point of a "light" retrieval tier. Cached by
    name so tests can override RAG_EMBEDDING_MODEL without cross-contaminating
    a differently-configured caller in the same process.
    """
    model_name = model_name or MODEL_NAME
    if model_name not in _model_cache:
        model = SentenceTransformer(model_name)
        # paraphrase-multilingual-MiniLM-L12-v2 defaults to 128 tokens, but chunks
        # are ~200 words (more tokens in Arabic), so the tail of every chunk was
        # silently never embedded. The model's positions support up to 512.
        if MAX_SEQ_LENGTH > 0:
            model.max_seq_length = MAX_SEQ_LENGTH
        _model_cache[model_name] = model
    return _model_cache[model_name]


def embed(texts: List[str], model_name: str = None) -> np.ndarray:
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    model = get_model(model_name)
    vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vectors.astype(np.float32)
