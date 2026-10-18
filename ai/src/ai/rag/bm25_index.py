"""
KEEL - BM25 Lexical Retrieval Index (spec S4, S6, S21).
Pure-Python, no trained model, no GPU - the lightest tier of the RAG
retrieval stack. Regex word tokenization (Unicode-aware by default in
Python's re module) works for both Arabic and English without a
language-specific tokenizer, matching chunking.py's approach.
"""

import re
from typing import List, Tuple

from rank_bm25 import BM25Plus

from src.ai.rag.retrieval_types import ScoredChunk

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


_ARABIC = re.compile(r"[\u0600-\u06FF]")


def _normalize(token: str) -> str:
    """Light, conservative stemming so "returns" finds "return" and
    "التوصيل" finds "توصيل" - never so aggressive that unrelated words merge."""
    if _ARABIC.search(token):
        for prefix in ("وال", "بال", "فال", "كال", "لل", "ال"):
            if token.startswith(prefix) and len(token) - len(prefix) >= 3:
                return token[len(prefix):]
        return token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> List[str]:
    return [_normalize(token) for token in _TOKEN_PATTERN.findall(text.lower())]


class BM25Index:
    """
    In-memory per-build index. Not persisted across process restarts by this
    class - callers needing persistence must rebuild from source chunks (see
    data_access.py) or serialize separately. Kept in-memory here because BM25
    index state doesn't belong in PostgreSQL (spec S37: "Redis is not
    permanent storage. The LLM is not the database" - by the same logic, an
    in-memory search index isn't a system of record either; the chunks
    themselves are the source of truth).
    """

    def __init__(self, chunks: List[Tuple[str, str]]):
        """
        `chunks` is a list of (chunk_id, text) pairs. Uses BM25Plus rather
        than the classic BM25Okapi: Okapi's IDF formula (log((N-df+0.5)/(df+0.5)))
        is exactly zero for any term appearing in precisely half of a
        corpus - trivially reachable with tenants that have only 2-3
        documents uploaded (a realistic cold-start state for an SME, spec
        S23), which silently zeroed out otherwise-obvious matches. BM25Plus's
        added delta term keeps IDF strictly positive regardless of corpus
        size.
        """
        self._chunk_ids = [chunk_id for chunk_id, _ in chunks]
        self._texts = [text for _, text in chunks]
        tokenized_corpus = [tokenize(text) for text in self._texts]
        self._token_sets = [set(tokens) for tokens in tokenized_corpus]
        self._bm25 = BM25Plus(tokenized_corpus) if tokenized_corpus else None

    def __len__(self) -> int:
        return len(self._chunk_ids)

    def query(self, query_text: str, top_k: int = 5) -> List[ScoredChunk]:
        if self._bm25 is None:
            return []

        tokenized_query = tokenize(query_text)
        scores = self._bm25.get_scores(tokenized_query)

        # BM25Plus's delta term gives EVERY chunk a positive score for any
        # in-vocabulary query term, even chunks that don't contain it - so
        # `score > 0` alone doesn't mean "lexical match". Without this
        # overlap check, unrelated chunks leaked into RRF fusion with an
        # arbitrary lexical rank.
        query_terms = set(tokenized_query)
        ranked = sorted(
            (row for row in zip(self._chunk_ids, self._texts, scores, self._token_sets) if row[3] & query_terms),
            key=lambda r: r[2],
            reverse=True,
        )
        return [ScoredChunk(chunk_id=cid, text=text, score=float(score)) for cid, text, score, _ in ranked[:top_k] if score > 0]
