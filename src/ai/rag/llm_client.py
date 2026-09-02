"""
CEOPRO AI - LLM Reasoning (spec S21's "LLM REASONING" stage).

Completes the RAG chatbot pipeline that pipeline.py deliberately stopped
short of (see its own module docstring): takes the AssembledContext
run_retrieval() produces (context text + source citations) and asks an
LLM to answer the original question grounded in that context.

Provider/model choice - "fast, accurate, lightweight, doesn't overload my
machine" - and why those aren't in tension: a large instruction-tuned
model served by Groq (an OpenAI-compatible, hardware-accelerated hosted
inference API - not a locally-run model). Groq's custom LPU hardware
gives some of the lowest per-token latency of any hosted provider
(satisfies "fast"); a full 70B-class model is genuinely capable at
multilingual/cross-dialect Arabic reasoning, not a distilled toy
(satisfies "accurate"); and because the weights run on Groq's
infrastructure, not wherever this service is deployed, there is zero
local GPU/CPU/RAM footprint from running an LLM at all (satisfies
"lightweight, doesn't overload my machine" - the one local machine this
call touches only ever sends and receives text over HTTPS). This is why
a hosted inference API was the right call here, not a locally-run model:
a model small enough to run lightly on a typical machine would trade
away the multilingual accuracy this platform's 16-country, cross-dialect
Arabic requirement needs.

DEFAULT_MODEL was originally set to a Qwen model on the (correct, at the
time) assumption that a full-size Qwen would be available and
production-ready on Groq - live verification against
https://console.groq.com/docs/models (2026-09-01, real request from a
user's own running service, confirmed by a 404 "model does not exist"
from Groq itself) found this was wrong: Groq's only Qwen models
(qwen/qwen3.6-27b, qwen/qwen3.8-27b) are preview-only, and Groq's own
docs say preview models "should not be used in production ... as they
may be discontinued." Switched to llama-3.1-8b-instant - Meta's
70B-parameter model, listed under Groq's *production* chat-completion
models as of the same verification. Model catalogs on hosted providers
change; re-check https://console.groq.com/docs/models before relying on
this long-term and override via GROQ_MODEL if it moves again.

This module is the *only* place in src/ai/rag/ that knows an LLM
provider exists - pipeline.py, data_access.py, and everything else stay
exactly as LLM-agnostic as before. Swapping providers later (Together AI,
DeepInfra, or a different model entirely) means changing this one file,
not the retrieval pipeline underneath it.
"""

import logging
import os
import time

import httpx

from src.ai.rag.pipeline import run_retrieval
from src.ai.rag.retrieval_types import AssembledContext

logger = logging.getLogger("CEOPRO_AI_RAG_LLM")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# See this module's own docstring: verified live against Groq's production
# model catalog (2026-09-01) - a 70B-class Llama model is the reasoning for
# "accurate" - override via GROQ_MODEL for a different size/provider.
DEFAULT_MODEL = "llama-3.1-8b-instant"
MODEL_NAME = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))

# Retry only what's actually transient: a network blip, a 5xx (Groq's own
# problem), or a 429 (explicitly "try again shortly", not a permanent
# rejection). A 400/401/403 means this request or this key is wrong and
# will still be wrong on the next attempt - retrying those would just burn
# quota and latency for no chance of a different outcome. Small bounded
# backoff, not unbounded - this is a synchronous call a real request is
# waiting on, not a background job that can afford to wait minutes.
MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECONDS = float(os.getenv("GROQ_RETRY_BACKOFF_SECONDS", "0.5"))
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Low temperature: this is grounded question-answering over retrieved
# business documents, not creative writing - the answer should track the
# provided context closely, not improvise around it.
DEFAULT_TEMPERATURE = 0.2

SYSTEM_PROMPT = (
    "You are CEOPRO AI's business assistant. Answer the user's question using ONLY the "
    "information in the provided context. If the context does not contain enough "
    "information to answer, say so explicitly rather than guessing or using outside "
    "knowledge. Respond in the same language as the question - the platform supports "
    "Arabic, English, and mixed Arabic-English (code-switched) queries.\n\n"
    "Provenance: the context is labeled with [Source N] markers, and each fact within a "
    "source is itself annotated with where it came from (e.g. a database table and column, "
    "or a market data snapshot with its origin and capture time). When asked what your "
    "answer is based on, or where a number came from, cite the exact table/field/source "
    "annotation as written in the context - never invent a source, generalize to 'our "
    "database' without naming the specific table, or claim a source that isn't literally "
    "present in the context above."
)


class LLMError(Exception):
    """Raised when the LLM provider call fails or returns an unusable response."""


def _build_user_prompt(context: AssembledContext) -> str:
    return (
        f"Context:\n{context.context_text}\n\n"
        f"Question: {context.query}\n\n"
        "Answer using only the context above."
    )


def _post_with_retry(payload: dict, headers: dict, timeout: float) -> httpx.Response:
    """
    Up to MAX_RETRIES retries (MAX_RETRIES + 1 attempts total) with a
    linear backoff, only for a network failure or a status code in
    _RETRYABLE_STATUS_CODES - see those constants' own comment for why a
    4xx outside that set (bad request, bad key, forbidden) is deliberately
    not retried. Returns the last response/re-raises the last exception
    once retries are exhausted, so the caller sees exactly the same shape
    of failure it would have without retries, just after trying harder
    first.
    """
    last_exception = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.post(GROQ_API_URL, headers=headers, json=payload, timeout=timeout)
        except httpx.HTTPError as err:
            last_exception = err
            if attempt < MAX_RETRIES:
                logger.warning(f"Groq request failed ({err}), retrying (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise LLMError(f"Groq API request failed: {err}") from err

        if response.status_code not in _RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
            return response

        logger.warning(
            f"Groq returned {response.status_code}, retrying (attempt {attempt + 1}/{MAX_RETRIES})"
        )
        time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    # Unreachable in practice (the loop always returns or raises above),
    # kept only so this function has an explicit exhaustive return path.
    raise LLMError(f"Groq API request failed after {MAX_RETRIES} retries: {last_exception}")


def generate_answer(
    context: AssembledContext,
    api_key: str = None,
    model: str = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """
    Calls the LLM provider with `context` (from pipeline.run_retrieval() or
    pipeline.assemble_context()) and returns the generated answer text.

    Raises LLMError (never a bare httpx/JSON exception) on a missing API
    key, a non-2xx response, a network failure, or an unexpected response
    shape - one exception type this module's caller needs to know about,
    not three. Transient failures (network errors, 429/5xx) are retried
    with backoff first - see _post_with_retry().
    """
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set - cannot call the LLM provider.")

    model = model or MODEL_NAME
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(context)},
        ],
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = _post_with_retry(payload, headers, timeout)

    if response.status_code != 200:
        raise LLMError(f"Groq API returned {response.status_code}: {response.text[:500]}")

    try:
        payload = response.json()
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as err:
        raise LLMError(f"Unexpected Groq API response shape: {response.text[:500]}") from err


def answer_query(conn, tenant_id: str, query_text: str, top_k: int = 5, **retrieval_kwargs) -> dict:
    """
    The complete, end-to-end RAG chatbot call: retrieval
    (pipeline.run_retrieval() - persisted hybrid index -> RRF fusion ->
    Cross-Encoder re-rank -> context assembly) followed by LLM reasoning
    (generate_answer()). Returns {"answer": str, "sources": list[dict]} -
    sources are the same chunk citations AssembledContext already carries,
    passed through so a caller can show "grounded in these N sources"
    alongside the answer.

    An empty retrieval result (nothing in the tenant's knowledge base
    matched) short-circuits before ever calling the LLM - there is
    nothing to ground an answer in, and no context to send.
    """
    context = run_retrieval(conn, tenant_id, query_text, top_k=top_k, **retrieval_kwargs)
    if not context.context_text:
        return {"answer": "I don't have any relevant information to answer that question.", "sources": []}

    answer = generate_answer(context)
    return {"answer": answer, "sources": context.sources}
