"""Shared types for src/ai/rag/ retrieval modules."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class ScoredChunk:
    chunk_id: str
    text: str
    score: float


@dataclass
class AssembledContext:
    """
    The final output of this module's pipeline - everything up to (not
    including) the "LLM REASONING" stage in spec S21's RAG workflow. The
    LLM layer is deliberately not this module's concern (see pipeline.py's
    module docstring): whatever provider/model gets chosen consumes
    `context_text` as its prompt context and `sources` for citing which
    chunks it was given, without this module knowing or caring which LLM
    that is.
    """
    query: str
    context_text: str
    sources: List[dict] = field(default_factory=list)
