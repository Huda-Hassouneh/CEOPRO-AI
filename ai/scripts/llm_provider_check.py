"""
KEEL - checks the assistant's configured LLM provider
(src/ai/rag/llm_client.py: paid > huggingface > local > groq) the way the
assistant will use it. Prints the provider, model and outcome; never a
credential (any credential value appearing in an error is masked).

    python -m scripts.llm_provider_check                    # from backend/
    python -m scripts.llm_provider_check --tenant <id>      # plus one real answer
    ./keel llm-check [--tenant <id>]                        # from the repo root

1. The credential is set.
2. With DATABASE_URL reachable: the model has a confirmed price in
   provider_cost_schedules. Without one every assistant call is refused
   (COST_NOT_CONFIGURED) - set it with scripts/billing_admin.py.
3. The provider accepts the credential and serves the model: its model list
   (no tokens, not billed) for Groq and Hugging Face.
4. With --tenant: one real request with a fixed prompt and no company data,
   metered like any assistant call and paid from that company's AI Credits
   (billing/credits.py) - a paid call is never made outside metering.

Exit status 0 only when every check that ran passed.
"""
import argparse
import os
import sys
import time

import httpx

from src.ai.rag import llm_client

PROMPT = [{"role": "user", "content": "Reply with exactly one word: ready"}]
CREDENTIALS = ("GROQ_API_KEY", "HUGGINGFACE_API_TOKEN", "PAID_LLM_API_KEY")
MODEL_LISTS = {"groq": "https://api.groq.com/openai/v1/models", "huggingface": "https://router.huggingface.co/v1/models"}


def _masked(text: str) -> str:
    for name in CREDENTIALS:
        value = os.getenv(name)
        if value and len(value) >= 6:
            text = text.replace(value, "***")
    return text


def _price_check(provider: str, model: str) -> bool:
    """True when the model has confirmed input and output token prices (or
    no accounting database is configured here to check against)."""
    if provider == "local":
        return True  # seeded at $0
    if not os.getenv("DATABASE_URL"):
        print("price: not checked (DATABASE_URL not set)")
        return True
    from src.ai import db
    from src.ai.billing import credits

    try:
        conn = db.system_connection()
    except Exception as exc:  # noqa: BLE001
        print(f"price: not checked (database unavailable: {type(exc).__name__})")
        return True
    try:
        prices = credits.schedule(conn, credits.AI, provider, model)
    finally:
        conn.close()
    missing = [unit for unit in ("input_token", "output_token") if (prices.get(unit) or {}).get("cost") is None]
    if missing:
        print(f"FAIL: no confirmed {' / '.join(missing)} price for {provider}/{model} - every assistant call is "
              "refused (COST_NOT_CONFIGURED). Record the provider's real price with scripts/billing_admin.py "
              "set-price (docs/SUBSCRIPTIONS_AND_CREDITS.md section 4).")
        return False
    per_million = {unit: float(prices[unit]["cost"]) * 1_000_000 for unit in ("input_token", "output_token")}
    print(f"price: ${per_million['input_token']:g} input / ${per_million['output_token']:g} output per 1M tokens")
    return True


def _model_listed(provider: str, model: str, api_key: str) -> bool:
    url = MODEL_LISTS.get(provider)
    if not url:
        print("model list: not available for this provider (use --tenant for a real request)")
        return True
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    except httpx.HTTPError as err:
        print(f"FAIL: {provider} unreachable: {type(err).__name__}")
        return False
    if response.status_code in (401, 403):
        print(f"FAIL: {provider} rejected the credential ({response.status_code})")
        return False
    if response.status_code != 200:
        print(f"FAIL: {provider} model list returned {response.status_code}: {_masked(response.text)[:200]}")
        return False
    served = {item.get("id") for item in response.json().get("data") or []}
    # The HF router lists bare model ids; "model:provider" picks one provider for it.
    if model in served or model.split(":", 1)[0] in served:
        print(f"model list: credential accepted, {model} is served")
        return True
    print(f"FAIL: credential accepted, but {provider} doesn't serve {model} - set a supported model "
          f"(GROQ_MODEL / HUGGINGFACE_LLM_MODEL)")
    return False


def _real_answer(tenant_id: str) -> bool:
    from src.ai.billing import credits

    started = time.monotonic()
    try:
        with credits.metering(tenant_id, "llm_provider_check", usage_class="simple_question"):
            answer = llm_client.chat_completion(PROMPT, max_tokens=200)
    except credits.BudgetError as err:
        print(f"FAIL: refused before the call - {err.reason}: {err.message()}")
        return False
    except llm_client.LLMError as err:
        print(f"FAIL after {time.monotonic() - started:.1f}s: {type(err).__name__}: {_masked(str(err))[:400]}")
        return False
    print(f"answered in {time.monotonic() - started:.1f}s (metered for tenant {tenant_id}): {answer.strip()[:80]!r}")
    if not answer.strip():
        print("FAIL: the provider answered with empty text")
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the assistant's configured LLM provider.")
    parser.add_argument("--tenant", help="company id to attribute one real, metered request to")
    args = parser.parse_args(argv)

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
    ok = _price_check(provider, model)
    if credential:
        ok = _model_listed(provider, model, os.getenv(credential)) and ok
    if args.tenant:
        ok = ok and _real_answer(args.tenant)
    else:
        print("real answer: skipped (pass --tenant <company id> to make one metered request)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
