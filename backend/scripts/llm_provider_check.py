"""
KEEL - one real request to the assistant's configured LLM provider
(src/ai/rag/llm_client.py: paid > huggingface > local > groq), with a fixed
prompt and no company data. Prints the provider, model and outcome; never a
credential (any credential value appearing in an error is masked).

    python -m scripts.llm_provider_check            # from backend/
    ./keel llm-check                                # from the repo root

Exit status 0 only when the provider answered.
"""
import os
import sys
import time

from src.ai.rag import llm_client

PROMPT = [{"role": "user", "content": "Reply with exactly one word: ready"}]
CREDENTIALS = ("GROQ_API_KEY", "HUGGINGFACE_API_TOKEN", "PAID_LLM_API_KEY")


def _masked(text: str) -> str:
    for name in CREDENTIALS:
        value = os.getenv(name)
        if value and len(value) >= 6:
            text = text.replace(value, "***")
    return text


def main() -> int:
    provider = llm_client.active_provider()
    model = {"paid": llm_client.PAID_LLM_MODEL, "huggingface": llm_client.HUGGINGFACE_LLM_MODEL}.get(provider) \
        or llm_client.MODEL_NAME
    credential = {"groq": "GROQ_API_KEY", "huggingface": "HUGGINGFACE_API_TOKEN", "paid": "PAID_LLM_API_KEY"}.get(provider)
    print(f"provider: {provider}, model: {model}")
    if credential:
        print(f"{credential}: {'available' if os.getenv(credential) else 'not set'}")
    if not llm_client.provider_configured():
        print("FAIL: the provider's credential is not set - see docs/SECRETS.md")
        return 1
    started = time.monotonic()
    try:
        answer = llm_client.chat_completion(PROMPT, max_tokens=200)
    except llm_client.LLMError as err:
        print(f"FAIL after {time.monotonic() - started:.1f}s: {type(err).__name__}: {_masked(str(err))[:400]}")
        return 1
    print(f"answered in {time.monotonic() - started:.1f}s: {answer.strip()[:80]!r}")
    if not answer.strip():
        print("FAIL: the provider answered with empty text")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
