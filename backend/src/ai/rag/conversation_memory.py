"""
KEEL - conversation memory and long messages.

A conversation has no end: it can run for any number of turns, and one
message can carry any amount of pasted text (a report, an export, a long
email thread). None of it may be cut off or forgotten - but the model reads
a bounded prompt, and a prompt over its limit is refused outright. So:
- the newest turns go to the model as they were (advisor.HISTORY_MESSAGES),
  a long one reduced to its start and end (focus());
- everything else the user wrote - every older message, and the full text of
  any long message, the current one included - is split into passages, and
  the passages that best match the question go to the model as citable
  evidence, up to MEMORY_BUDGET_CHARS (relevant_passages()).
Storage keeps every message in full (conversation_store.py); only what
reaches the model on each turn is chosen.

Only the user's own messages are recalled this way, not earlier answers: a
recalled passage is cited as evidence, and an earlier answer is the model's
own words, not something the user or the company stated.
"""
import os
from typing import List, Tuple

from src.ai.rag.bm25_index import BM25Index
from src.ai.rag.chunking import chunk_text

# A message longer than this is reduced to its start and end wherever it is
# read whole (intent detection, search, the prompt's Question line); its
# middle reaches the model through relevant_passages().
LONG_MESSAGE_CHARS = int(os.getenv("RAG_LONG_MESSAGE_CHARS", "4000"))
# How much recalled text each answer gets (~2,500 tokens).
MEMORY_BUDGET_CHARS = int(os.getenv("RAG_MEMORY_BUDGET_CHARS", "7000"))
# Small enough that a passage fits an evidence excerpt (evidence._MAX_EXCERPT).
PASSAGE_WORDS, PASSAGE_OVERLAP_WORDS = 120, 20


def is_long(text: str) -> bool:
    return len(text or "") > LONG_MESSAGE_CHARS


def focus(text: str) -> str:
    """`text`, or for a long message its start and end - where a question
    about pasted text usually is."""
    if not is_long(text):
        return text
    side = LONG_MESSAGE_CHARS // 2
    head = text[:side].rsplit(" ", 1)[0]
    tail = text[-side:].split(" ", 1)[-1]
    return f"{head} … {tail}"


def relevant_passages(sources: List[Tuple[str, str]], query: str,
                      budget: int = MEMORY_BUDGET_CHARS) -> List[Tuple[str, str]]:
    """(label, passage) for the passages of `sources` ((label, text) pairs,
    oldest first) that best match `query`, within `budget` characters, in
    the order they were written. Passages sharing no word with the query
    fill what is left of the budget, newest first."""
    passages = [(label, chunk) for label, text in sources
                for chunk in chunk_text(text or "", PASSAGE_WORDS, PASSAGE_OVERLAP_WORDS)]
    if not passages:
        return []
    index = BM25Index([(str(i), text) for i, (_, text) in enumerate(passages)])
    ranked = [int(hit.chunk_id) for hit in index.query(query, top_k=len(passages))]
    matched = set(ranked)
    ranked += [i for i in reversed(range(len(passages))) if i not in matched]
    chosen, used = [], 0
    for i in ranked:
        size = len(passages[i][1])
        if used + size > budget:
            continue
        chosen.append(i)
        used += size
    return [passages[i] for i in sorted(chosen)]
