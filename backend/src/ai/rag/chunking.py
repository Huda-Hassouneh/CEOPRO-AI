"""
KEEL - RAG Document Chunking (spec S21: "Document ingestion").
Word-boundary based (via whitespace split) so it works for both Arabic and
English (spec S8: "The platform must support Arabic-English code-switching")
without a language-specific tokenizer. Pure function - no I/O.
"""

import os
from typing import List, Optional

DEFAULT_CHUNK_SIZE_WORDS = int(os.getenv("RAG_CHUNK_SIZE_WORDS", "200"))
DEFAULT_CHUNK_OVERLAP_WORDS = int(os.getenv("RAG_CHUNK_OVERLAP_WORDS", "40"))


def chunk_text(text: str, chunk_size_words: int = None, overlap_words: int = None) -> List[str]:
    """
    Splits `text` into overlapping word-count windows. Overlap keeps a sentence
    or idea spanning a chunk boundary retrievable from either chunk, at the
    cost of some duplicated content in the index - a standard RAG tradeoff.
    """
    chunk_size_words = DEFAULT_CHUNK_SIZE_WORDS if chunk_size_words is None else chunk_size_words
    overlap_words = DEFAULT_CHUNK_OVERLAP_WORDS if overlap_words is None else overlap_words

    if chunk_size_words <= 0:
        raise ValueError("chunk_size_words must be positive")
    if overlap_words < 0 or overlap_words >= chunk_size_words:
        raise ValueError("overlap_words must be non-negative and smaller than chunk_size_words")

    words = text.split()
    if not words:
        return []

    step = chunk_size_words - overlap_words
    chunks = []
    for start in range(0, len(words), step):
        window = words[start:start + chunk_size_words]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + chunk_size_words >= len(words):
            break

    return chunks


def chunk_pages(text: str, chunk_count: int, chunk_size_words: int = None, overlap_words: int = None) -> List[Optional[int]]:
    """The page (1-based) each chunk of chunk_text(text) starts on, for text
    whose pages are separated by form feeds (PDFs); all None otherwise."""
    if "\f" not in (text or ""):
        return [None] * chunk_count
    chunk_size_words = DEFAULT_CHUNK_SIZE_WORDS if chunk_size_words is None else chunk_size_words
    overlap_words = DEFAULT_CHUNK_OVERLAP_WORDS if overlap_words is None else overlap_words
    starts, offset = [], 0
    for page_text in text.split("\f"):
        starts.append(offset)
        offset += len(page_text.split())
    step = chunk_size_words - overlap_words
    pages = []
    for index in range(chunk_count):
        word = index * step
        pages.append(max(number for number, start in enumerate(starts, start=1) if start <= word))
    return pages
