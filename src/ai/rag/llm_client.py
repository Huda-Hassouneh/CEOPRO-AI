"""
CEOPRO AI - LLM Reasoning (spec S21's "LLM REASONING" stage).

Completes the RAG chatbot pipeline that pipeline.py deliberately stopped
short of (see its own module docstring): takes the AssembledContext
run_retrieval() produces (context text + source citations) and asks an
LLM to answer the original question grounded in that context.

Provider/model choice - "fast, accurate, lightweight, doesn't overload my
machine" - and why those aren't in tension: Qwen2.5, served by Groq (an
OpenAI-compatible, hardware-accelerated hosted inference API - not a
locally-run model). Groq's custom LPU hardware gives some of the lowest
per-token latency of any hosted provider (satisfies "fast"); a full-size
instruction-tuned Qwen model is genuinely capable at multilingual/
cross-dialect Arabic reasoning, not a distilled toy (satisfies
"accurate"); and because the weights run on Groq's infrastructure, not
wherever this service is deployed, there is zero local GPU/CPU/RAM
footprint from running an LLM at all (satisfies "lightweight, doesn't
overload my machine" - the one local machine this call touches only ever
sends and receives text over HTTPS). This is why a hosted inference API
was the right call here, not a locally-run model: a Qwen model small
enough to run lightly on a typical machine would trade away the
multilingual accuracy this platform's 16-country, cross-dialect Arabic
requirement needs.

DEFAULT_MODEL is a starting point, not a value this session verified
against Groq's live catalog (no API key is configured in this
environment - this module is complete and tested against a mocked HTTP
layer, but has never made a real call). Model catalogs on hosted
providers change; check https://console.groq.com/docs/models before
relying on this in production and override via GROQ_MODEL if it's moved.

This module is the *only* place in src/ai/rag/ that knows an LLM
provider exists - pipeline.py, data_access.py, and everything else stay
exactly as LLM-agnostic as before. Swapping providers later (Together AI,
DeepInfra, or a different model entirely) means changing this one file,
not the retrieval pipeline underneath it.
"""

import logging
import os

import httpx

from src.ai.rag.pipeline import run_retrieval
from src.ai.rag.retrieval_types import AssembledContext

logger = logging.getLogger("CEOPRO_AI_RAG_LLM")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# See this module's own docstring: not verified against Groq's live model
# catalog in this environment. A 32B-class Qwen model is the reasoning for
# "accurate" - override via GROQ_MODEL for a different size/provider.
DEFAULT_MODEL = "qwen/qwen3-32b"
MODEL_NAME = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))

# Low temperature: this is grounded question-answering over retrieved
# business documents, not creative writing - the answer should track the
# provided context closely, not improvise around it.
DEFAULT_TEMPERATURE = 0.2

SYSTEM_PROMPT = (
    "You are CEOPRO AI's business assistant. Answer the user's question using ONLY the "
    "information in the provided context. If the context does not contain enough "
    "information to answer, say so explicitly rather than guessing or using outside "
    "knowledge. Respond in the same language as the question - the platform supports "
    "Arabic, English, and mixed Arabic-English (code-switched) queries."
)


class LLMError(Exception):
    """Raised when the LLM provider call fails or returns an unusable response."""


def _build_user_prompt(context: AssembledContext) -> str:
    return (
        f"Context:\n{context.context_text}\n\n"
        f"Question: {context.query}\n\n"
        "Answer using only the context above."
    )


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
    not three.
    """
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set - cannot call the LLM provider.")

    model = model or MODEL_NAME
    try:
        response = httpx.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_prompt(context)},
                ],
                "temperature": temperature,
            },
            timeout=timeout,
        )
    except httpx.HTTPError as err:
        raise LLMError(f"Groq API request failed: {err}") from err

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
