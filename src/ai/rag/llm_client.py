"""
CEOPRO AI - LLM Reasoning (spec S21's "LLM REASONING" stage)

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

DEFAULT_MODEL has moved twice, both times because a hosted provider's
catalog changed under us - re-check https://console.groq.com/docs/models
before relying on this long-term and override via GROQ_MODEL if it moves
again:
1. Originally a Qwen model, on the (correct, at the time) assumption a
   full-size Qwen would be production-ready on Groq - live verification
   (2026-09-01) found Groq's only Qwen models are preview-only.
2. Switched to llama-3.1-8b-instant. Live-verified again on 2026-09-03
   with a real API key, direct HTTP calls (bypassing this module) to
   every candidate model returned 404 "does not exist or you do not have
   access to it" for llama-3.1-8b-instant AND llama-3.3-70b-versatile,
   and 400 "decommissioned" for llama3-8b-8192/llama3-70b-8192/
   gemma2-9b-it - Groq's catalog had moved on again. openai/gpt-oss-20b
   was the first model in that same live test to return a real 200 with
   correct `choices[0].message.content` - switched to it. Notably, gpt-oss
   models return a *separate* `message.reasoning` field alongside
   `content` (chain-of-thought Groq exposes distinctly) - this module
   only ever reads `content` (see _post_with_retry's caller below), so
   that reasoning text is correctly ignored, not accidentally surfaced
   to the end user.

This module is the *only* place in src/ai/rag/ that knows an LLM
provider exists - pipeline.py, data_access.py, and everything else stay
exactly as LLM-agnostic as before. Swapping providers later (Together AI,
DeepInfra, or a different model entirely) means changing this one file,
not the retrieval pipeline underneath it.
"""

import logging
import os
import random
import time

import httpx

from src.ai.rag.pipeline import run_retrieval
from src.ai.rag.retrieval_types import AssembledContext
from src.ai.rag.structured_context import build_structured_facts_block

logger = logging.getLogger("CEOPRO_AI_RAG_LLM")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Optional local backend override - a llama.cpp `llama-server` (or any other
# OpenAI-compatible endpoint) running on this machine. Live-verified
# 2026-09-06: Qwen2.5-3B-Instruct (Q5_K_M GGUF) via llama-server on this
# same request/response shape, no other code path change needed - both
# Groq and llama-server speak the identical `/v1/chat/completions` schema.
# Set this to route generate_answer() at the local server instead of Groq;
# leave unset and the Groq path behaves exactly as before this change.
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL")

# Optional paid-provider override - the flexible placeholder for swapping
# Groq for a paid subscription later (OpenAI, Together AI, Azure OpenAI,
# Fireworks, or any other vendor that speaks the same OpenAI-compatible
# `/v1/chat/completions` schema Groq and llama-server already do) without a
# rewrite: set PAID_LLM_BASE_URL (+ PAID_LLM_API_KEY, and optionally
# PAID_LLM_MODEL) and generate_answer() routes here instead of Groq or the
# local llama-server, with zero code change. All three are unset by
# default, so Groq stays the active provider until a real vendor decision
# is made - this is a config slot, not a live integration. Takes priority
# over LOCAL_LLM_BASE_URL when both happen to be set.
#
# A genuinely different-schema provider (Anthropic's Messages API, Google's
# Gemini API) would need a new code path here, not just these env vars -
# that's a real vendor decision, not made in this pass.
PAID_LLM_BASE_URL = os.getenv("PAID_LLM_BASE_URL")
PAID_LLM_API_KEY = os.getenv("PAID_LLM_API_KEY")
PAID_LLM_MODEL = os.getenv("PAID_LLM_MODEL")

# See this module's own docstring: verified live with a real key on
# 2026-09-03 - override via GROQ_MODEL for a different size/provider.
DEFAULT_MODEL = "openai/gpt-oss-20b"
MODEL_NAME = os.getenv("GROQ_MODEL", DEFAULT_MODEL)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))

# Defaults to DEFAULT_TIMEOUT_SECONDS (Groq's own budget) since a paid
# hosted provider is presumed comparably fast until proven otherwise -
# override with PAID_LLM_TIMEOUT_SECONDS if the chosen vendor needs more.
PAID_LLM_TIMEOUT_SECONDS = float(os.getenv("PAID_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))

# Local llama-server generates at real-measured ~6 tokens/sec on this
# platform's reference hardware (i5-1135G7, 4 threads, Qwen2.5-3B Q5_K_M -
# live-benchmarked 2026-09-06), vs. Groq's hardware-accelerated hosted
# inference - 20s (right for Groq) produced a real httpx.ReadTimeout in
# testing the very first time this ran against a local model. Not a bug in
# the request, just a genuinely slower backend needing a genuinely longer
# budget - this is that budget, used only on the local path.
LOCAL_LLM_TIMEOUT_SECONDS = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "90"))

# Uncapped generation is a real, free latency lever, not just a Groq nicety:
# the same uncapped request that finishes in ~1-2s on Groq's hardware can
# run long enough to hit even the extended local timeout above. Applied to
# both backends (harmless on Groq, since a grounded RAG answer rarely needs
# to run long anyway) rather than only the local path, so behavior stays
# predictable regardless of which backend is active.
DEFAULT_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "400"))

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

# Jitter on top of the linear backoff above: under a real provider-wide
# outage/429 event, many concurrent requests hitting this same process
# would otherwise all retry in lockstep at the exact same 0.5s/1.0s
# intervals, adding a synchronized retry spike right when the provider is
# already struggling. A random fraction added to each wait spreads
# retries out instead - RETRY_JITTER_FRACTION=0.5 means each backoff is
# lengthened by 0%-50% of its base value, never shortened (never retrying
# SOONER than the base backoff already calls for).
RETRY_JITTER_FRACTION = float(os.getenv("GROQ_RETRY_JITTER_FRACTION", "0.5"))

# Circuit breaker: /rag/query runs synchronously in a FastAPI request
# handler (on the thread-pool executor), and a single failed request can
# already cost close to MAX_RETRIES attempts x up to DEFAULT_TIMEOUT_SECONDS/
# LOCAL_LLM_TIMEOUT_SECONDS each. Under a sustained provider outage, every
# new incoming chat request keeps paying that same full retry cost against
# a provider that's already known to be down - real risk of exhausting the
# thread pool and queuing/timing out unrelated requests (pricing, sentiment,
# etc. sharing the same process). After CIRCUIT_BREAKER_THRESHOLD consecutive
# request-level failures (a failure meaning every retry within one call was
# already exhausted - a transient blip that succeeds on retry never counts),
# new calls fail fast for CIRCUIT_BREAKER_COOLDOWN_SECONDS instead of
# attempting the full retry sequence again. Module-level, in-process state -
# not shared across worker processes, which is fine: the goal is protecting
# THIS process's own thread pool, not a global rate limit.
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("GROQ_CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_COOLDOWN_SECONDS = float(os.getenv("GROQ_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "30"))

# Real bug this constant fixes: every call into this module used to send
# exactly one message (system prompt + the current turn) - the LLM had
# zero memory of anything said earlier in the same conversation, so a
# natural follow-up ("I meant jumper wire", "why isn't that clear?") had
# no way to resolve what it was referring to and the reply came back
# disconnected from what was just discussed. history (a list of
# {"role": "user"|"assistant", "content": str} dicts, oldest first, the
# same shape the caller's own chat log already tracks) is now threaded
# into the real chat-completion `messages` array between the system
# prompt and the current turn, giving the model the actual prior
# exchange to reason over - the same mechanism every real chat product
# (Claude, NotebookLM, ChatGPT) relies on for this exact behavior.
# Capped rather than sent in full: a long-running conversation would
# otherwise grow the prompt (and the cost/latency of every future turn)
# without bound. 12 messages = 6 full user/assistant turns - enough for
# real short-term context (a clarification, a "why", a "tell me more")
# without paying to re-send an entire session's history on every message.
MAX_HISTORY_MESSAGES = int(os.getenv("RAG_MAX_HISTORY_MESSAGES", "12"))

_circuit_state = {"consecutive_failures": 0, "opened_at": None}


def _reset_circuit_breaker() -> None:
    """Test-only reset hook - module-level state would otherwise leak
    failure counts across unrelated test cases (and across requests for
    different, independent backends in a real deployment that switches
    providers at runtime)."""
    _circuit_state["consecutive_failures"] = 0
    _circuit_state["opened_at"] = None


def _circuit_is_open() -> bool:
    opened_at = _circuit_state["opened_at"]
    if opened_at is None:
        return False
    if time.monotonic() - opened_at >= CIRCUIT_BREAKER_COOLDOWN_SECONDS:
        _reset_circuit_breaker()  # cooldown elapsed - let the next call retry for real
        return False
    return True


def _record_circuit_success() -> None:
    _reset_circuit_breaker()


def _record_circuit_failure() -> None:
    _circuit_state["consecutive_failures"] += 1
    if _circuit_state["consecutive_failures"] >= CIRCUIT_BREAKER_THRESHOLD:
        _circuit_state["opened_at"] = time.monotonic()


def _backoff_seconds(attempt: int) -> float:
    base = RETRY_BACKOFF_SECONDS * (attempt + 1)
    return base + random.uniform(0, base * RETRY_JITTER_FRACTION)

# Low temperature: this is grounded question-answering over retrieved
# business documents, not creative writing - the answer should track the
# provided context closely, not improvise around it.
DEFAULT_TEMPERATURE = 0.2

SYSTEM_PROMPT = (
    "You are CEOPRO AI's business assistant - a friendly, supportive advisor for an "
    "ordinary small-business owner (a shop or restaurant owner, not a data analyst, "
    "engineer, or accountant). Answer the user's question using ONLY the information in "
    "the provided context. If the context does not contain enough information to answer, "
    "say so explicitly and simply - in the exact same language and dialect the user's "
    "CURRENT message is written in, never switching to English or any other language just "
    "because this is an 'I don't know' reply - rather than guessing or using outside "
    "knowledge.\n\n"
    "Conversation history: earlier turns from this same conversation may be included before "
    "the current question, oldest first. Use them only to understand what the CURRENT "
    "question is actually asking - resolving a pronoun, a correction ('I meant X'), or a "
    "follow-up ('why?', 'tell me more') against what was just discussed. Never treat "
    "something said earlier in the conversation (by either you or the user) as a new fact "
    "on its own - every factual claim in your answer must still come from the context/"
    "business data provided for THIS turn, exactly as the provenance rule below requires.\n\n"
    "Language, dialect, and tone - match the user exactly, every time: respond in the "
    "EXACT SAME language the user just wrote in, never switching languages on your own and "
    "never defaulting to English. If they wrote in Arabic, answer entirely in Arabic; if "
    "English, entirely in English; if they mixed Arabic and English in the same message "
    "(code-switching), mirror that same natural mix rather than forcing the reply into one "
    "pure language. This applies to every single reply, including a follow-up later in the "
    "same conversation - re-check the language of the CURRENT message each time rather than "
    "sticking with whatever language was used earlier.\n\n"
    "Go further than just the language: match the user's specific dialect and register too, "
    "so the reply sounds like it's coming from someone who actually talks the way they do, "
    "not a generic translation. If they write in a regional Arabic dialect (e.g. Jordanian/"
    "Levantine, Gulf, Egyptian), reply naturally in that same dialect, not formal Modern "
    "Standard Arabic and never English technical terms transliterated into Arabic letters. "
    "If they write formal, correct Arabic or English, reply in an equally professional "
    "register; if they write casually (short sentences, colloquial phrasing, emoji), reply "
    "just as casually and warmly back. When the dialect or register genuinely isn't clear "
    "from a short message, default to plain, everyday spoken business Arabic or English (the "
    "way a shopkeeper actually talks with a trusted advisor) rather than guessing at a "
    "specific dialect. None of this dialect/tone matching ever excuses using jargon - a "
    "casual Jordanian-dialect reply and a formal English reply must both stay equally free "
    "of it, per the Extreme Simplicity rule below.\n\n"
    "Extreme Simplicity - this is a hard rule, not a style preference: never use technical, "
    "statistical, or machine-learning jargon in any language, no matter how it appears in "
    "the context. This includes (but isn't limited to) model/algorithm names (XGBoost, "
    "baseline model, walk-forward validation), statistical metrics (MASE, RMSE, MAE, "
    "p-value, standard deviation), and raw confidence scores or probabilities (\"confidence "
    "0.73\"). If the context contains any of these, silently translate them into a plain, "
    "everyday statement before answering - never repeat the technical term or number "
    "itself, even if asked to cite where a figure came from. For confidence/uncertainty, "
    "use plain qualitative language instead of numbers - for example: 'this is a solid "
    "estimate based on your own sales history' (high confidence), 'this is a reasonable "
    "estimate, but it will get more accurate over time' (moderate confidence), or 'this is "
    "an early, rough estimate since we don't have much history yet' (low confidence). "
    "Every answer should read like straightforward, practical business advice a friend "
    "who understands the shop's numbers would give over coffee - short sentences, concrete "
    "next steps, no filler.\n\n"
    "Teaching mode: if the user seems confused, asks what something means, or asks you to "
    "explain a concept (pricing, demand, sentiment, competition, or anything else about "
    "how the business works), switch into a patient, supportive teacher. Explain it using "
    "everyday language and a simple, relatable example (a small shop, a market stall, a "
    "familiar situation) rather than a definition or technical explanation. Never make the "
    "user feel talked down to for not knowing something, and always check afterward "
    "whether they'd like it explained a different way.\n\n"
    "Provenance: the context is labeled with [Source N] markers, and each fact within a "
    "source is itself annotated with where it came from (e.g. a database table and column, "
    "or a market data snapshot with its origin and capture time). When asked what your "
    "answer is based on, or where a number came from, describe the source in plain, "
    "everyday terms the same way the rest of your answer is phrased (e.g. 'based on your "
    "own sales records' or 'based on what we've seen from your competitors online') - never "
    "invent a source, generalize to 'our database' without saying what kind of information "
    "it is, claim a source that isn't literally present in the context above, or read out "
    "the raw table/column name itself."
)


class LLMError(Exception):
    """Raised when the LLM provider call fails or returns an unusable response."""


def _sanitize_history(history) -> list:
    """
    Defensive normalization for the caller-supplied conversation history,
    not just a pass-through - a caller building this from a UI's own chat
    log (a plain list of (role, text) pairs, or a request body from an
    untrusted client) can hand this function almost anything. Silently
    drops/fixes what it can rather than raising, since a malformed history
    entry should degrade to "less context", never break the whole chat
    turn:
    - keeps only {"role", "content"} keys (drops anything else a caller
      might have included, e.g. a UI's own internal message id/timestamp);
    - coerces role to "user"/"assistant" only - anything else (including
      an accidental "system") is dropped rather than risk a caller
      injecting a second system-level instruction into the payload;
    - drops empty/non-string content;
    - keeps only the most recent MAX_HISTORY_MESSAGES entries (oldest of
      the kept ones first) - see that constant's own comment for why.
    """
    if not history:
        return []
    cleaned = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned[-MAX_HISTORY_MESSAGES:]


def _build_user_prompt(context: AssembledContext, structured_facts: str = "") -> str:
    """
    structured_facts (structured_context.py::build_structured_facts_block())
    is a second, separately-labeled section - real, current numbers
    queried live, never retrieved via semantic search. Kept visually and
    textually distinct from the retrieved "Context" section so the model
    (and SYSTEM_PROMPT's own provenance instruction, which already tells
    it to cite the exact table/field a number came from) can tell "a
    retrieved passage" apart from "a live database fact" - both are real,
    grounded input, just sourced two different ways.
    """
    sections = [f"Context:\n{context.context_text}"]
    if structured_facts:
        sections.append(f"Current business data (live, queried for this question):\n{structured_facts}")
    sections.append(f"Question: {context.query}\n\nAnswer using only the information above.")
    return "\n\n".join(sections)


def _post_with_retry(url: str, payload: dict, headers: dict, timeout: float) -> httpx.Response:
    """
    Up to MAX_RETRIES retries (MAX_RETRIES + 1 attempts total) with a
    jittered linear backoff (see RETRY_JITTER_FRACTION), only for a
    network failure or a status code in _RETRYABLE_STATUS_CODES - see
    those constants' own comment for why a 4xx outside that set (bad
    request, bad key, forbidden) is deliberately not retried. Returns the
    last response/re-raises the last exception once retries are
    exhausted, so the caller sees exactly the same shape of failure it
    would have without retries, just after trying harder first.

    Guarded by a circuit breaker (see CIRCUIT_BREAKER_* constants): after
    enough consecutive request-level failures, a new call fails fast
    instead of repeating the full retry sequence against a provider
    that's already known to be down.
    """
    if _circuit_is_open():
        raise LLMError(
            f"LLM provider ({url}) circuit breaker is open after {CIRCUIT_BREAKER_THRESHOLD} consecutive "
            f"failures - failing fast for up to {CIRCUIT_BREAKER_COOLDOWN_SECONDS:.0f}s instead of retrying "
            f"against a provider that's already known to be down."
        )

    last_exception = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.HTTPError as err:
            last_exception = err
            if attempt < MAX_RETRIES:
                logger.warning(f"LLM request to {url} failed ({err}), retrying (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(_backoff_seconds(attempt))
                continue
            _record_circuit_failure()
            raise LLMError(f"LLM provider request failed: {err}") from err

        if response.status_code not in _RETRYABLE_STATUS_CODES:
            if response.status_code == 200:
                _record_circuit_success()
            return response
        if attempt == MAX_RETRIES:
            _record_circuit_failure()
            return response

        logger.warning(
            f"LLM provider returned {response.status_code}, retrying (attempt {attempt + 1}/{MAX_RETRIES})"
        )
        time.sleep(_backoff_seconds(attempt))

    # Unreachable in practice (the loop always returns or raises above),
    # kept only so this function has an explicit exhaustive return path.
    raise LLMError(f"Groq API request failed after {MAX_RETRIES} retries: {last_exception}")


def generate_answer(
    context: AssembledContext,
    api_key: str = None,
    model: str = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    structured_facts: str = "",
    history: list = None,
) -> str:
    """
    Calls the LLM provider with `context` (from pipeline.run_retrieval() or
    pipeline.assemble_context()) and returns the generated answer text.

    history (optional): prior turns of this same conversation, as
    {"role": "user"|"assistant", "content": str} dicts, oldest first -
    normalized/truncated via _sanitize_history() (see its own docstring)
    before being placed between the system prompt and the current turn in
    the real chat-completion `messages` array. Without this, every call
    was a fresh, memory-less single-turn exchange - a real defect for a
    conversational assistant, not a design choice: a user's own follow-up
    ("I meant X", "why isn't that clear?") had nothing to resolve against.
    Only the CURRENT turn gets a freshly retrieved context/structured-facts
    block; earlier turns carry their own plain conversational text only,
    so the prompt doesn't re-send the same grounding material on every
    message.

    Raises LLMError (never a bare httpx/JSON exception) on a missing API
    key, a non-2xx response, a network failure, or an unexpected response
    shape - one exception type this module's caller needs to know about,
    not three. Transient failures (network errors, 429/5xx) are retried
    with backoff first - see _post_with_retry().

    Backend selection, in priority order: PAID_LLM_BASE_URL (a paid
    subscription vendor, once one is actually provisioned - see this
    module's PAID_LLM_* constants) > LOCAL_LLM_BASE_URL (a llama.cpp
    `llama-server` running on this machine for zero-cost, fully local
    inference) > Groq (the default while neither override is set).
    llama-server doesn't validate the Authorization header at all, so no
    real key is required for it - GROQ_API_KEY stays mandatory only on the
    Groq path, exactly as before this change; the paid path requires
    PAID_LLM_API_KEY (or an explicit api_key argument) since a real paid
    vendor does validate its key.

    timeout defaults to None so it can pick the right budget for whichever
    backend is actually active (DEFAULT_TIMEOUT_SECONDS for Groq,
    LOCAL_LLM_TIMEOUT_SECONDS for a local server, PAID_LLM_TIMEOUT_SECONDS
    for a paid vendor) rather than a single fixed default that's only
    correct for one of them - a real httpx.ReadTimeout in testing is what
    caught this needing to be backend-aware at all.
    """
    using_paid = bool(PAID_LLM_BASE_URL)
    using_local = bool(LOCAL_LLM_BASE_URL) and not using_paid

    if using_paid:
        url = PAID_LLM_BASE_URL
    elif using_local:
        url = LOCAL_LLM_BASE_URL
    else:
        url = GROQ_API_URL

    if timeout is None:
        if using_paid:
            timeout = PAID_LLM_TIMEOUT_SECONDS
        elif using_local:
            timeout = LOCAL_LLM_TIMEOUT_SECONDS
        else:
            timeout = DEFAULT_TIMEOUT_SECONDS

    if using_paid:
        api_key = api_key or PAID_LLM_API_KEY
        if not api_key:
            raise LLMError("PAID_LLM_BASE_URL is set but PAID_LLM_API_KEY is not - cannot call the paid LLM provider.")
    else:
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            if not using_local:
                raise LLMError("GROQ_API_KEY is not set - cannot call the LLM provider.")
            api_key = "local"  # llama-server ignores this; only Groq actually validates it.

    model = model or (PAID_LLM_MODEL if using_paid else None) or MODEL_NAME
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *_sanitize_history(history),
            {"role": "user", "content": _build_user_prompt(context, structured_facts)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = _post_with_retry(url, payload, headers, timeout)

    if response.status_code != 200:
        raise LLMError(f"LLM provider ({url}) returned {response.status_code}: {response.text[:500]}")

    try:
        payload = response.json()
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as err:
        raise LLMError(f"Unexpected LLM provider response shape: {response.text[:500]}") from err


def answer_query(
    conn, tenant_id: str, query_text: str, top_k: int = 5,
    include_structured_facts: bool = True, history: list = None, **retrieval_kwargs,
) -> dict:
    """
    The complete, end-to-end RAG chatbot call: retrieval
    (pipeline.run_retrieval() - persisted hybrid index -> RRF fusion ->
    Cross-Encoder re-rank -> context assembly), live structured facts
    (structured_context.py - real current numbers, not retrieved),
    followed by LLM reasoning (generate_answer(), which now also takes
    this same `history` - see its own docstring). Returns
    {"answer": str, "sources": list[dict]} - sources are the same chunk
    citations AssembledContext already carries; structured facts have no
    "chunk" to cite (they're a live query, not a persisted document), so
    they never appear in `sources`, only inline in the answer text
    itself when the model chooses to use them.

    Always calls the LLM, even when retrieval and structured facts both
    come back empty - SYSTEM_PROMPT already tells the model exactly how
    to decline gracefully AND in the user's own language/dialect when
    there's genuinely nothing to answer from (see its own text). A
    hardcoded English "I don't have any relevant information" string used
    to short-circuit this case instead, skipping the LLM (and therefore
    skipping SYSTEM_PROMPT's language-matching) entirely - a real bug: an
    Arabic-speaking user asking anything with no matching data got an
    English sentence back no matter what language they'd been using.
    Removed rather than translated, since duplicating SYSTEM_PROMPT's own
    language logic in a second, non-LLM code path is exactly the kind of
    drift that caused this bug in the first place.

    include_structured_facts=True by default; set False for a caller
    that wants retrieval-only behavior (e.g. testing, or a context where
    live structured queries aren't desired for this one call).
    """
    context = run_retrieval(conn, tenant_id, query_text, top_k=top_k, **retrieval_kwargs)
    structured_facts = build_structured_facts_block(conn, tenant_id) if include_structured_facts else ""

    answer = generate_answer(context, structured_facts=structured_facts, history=history)
    return {"answer": answer, "sources": context.sources}
