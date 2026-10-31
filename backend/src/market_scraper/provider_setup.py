"""
KEEL - operator-owned provider keys: setup status, connection test, one-time alert.

Provider keys (Groq, Tavily, Google Places, YouTube, Apify) belong to the service operator and
live in environment settings only (docs/SECRETS.md). Nothing here reads a key
out to a caller: status reports "configured or not" and the variable NAME, a
connection test returns one fixed word, and an alert names the provider and the
problem, never a key or a provider message.

"Operator" = a signed-in, email-confirmed user whose address is listed in
OPERATOR_EMAILS (comma separated). Unset or empty: nobody is an operator and
the setup screen does not exist.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("CEOPRO_PROVIDER_SETUP")

TIMEOUT = 10.0
ALERT_TTL_SECONDS = 24 * 3600
TEST_COOLDOWN_SECONDS = 10
ALERT_CODES = ("CREDENTIALS_REJECTED", "QUOTA_EXHAUSTED")

# provider -> what it is for, the variable(s) to set (first is the preferred name), and a cost note.
PROVIDERS: Dict[str, dict] = {
    "groq": {
        "label": "Groq (AI model)",
        "unlocks": "AI-written assistant answers, analyses and summaries.",
        "env": ("GROQ_API_KEY",),
        "cost": "Billed by Groq per token. The test lists the models and asks the configured one for a one-word answer.",
    },
    "tavily": {
        "label": "Tavily (web search)",
        "unlocks": "Public research in assistant answers, competitor news and web discovery.",
        "env": ("TAVILY_API_KEY",),
        "cost": "1,000 free searches a month, then billed per search. The test runs one basic search (1 credit).",
    },
    "google_places": {
        "label": "Google Places",
        "unlocks": "Competitor discovery, competitor details and the first Google reviews.",
        "env": ("GOOGLE_PLACES_API_KEY",),
        "cost": "Billed by Google Cloud per request. Restrict the key to the Places API. The test is a free ID-only lookup.",
    },
    "youtube": {
        "label": "YouTube comments",
        "unlocks": "Public YouTube comments, with likes, on videos naming a competitor.",
        "env": ("YOUTUBE_API_KEY",),
        "cost": "Free daily quota (10,000 units). The test uses 1 unit.",
    },
    "apify": {
        "label": "Apify",
        "unlocks": "Competitor discovery through Google Maps, reviews beyond five, and prices from social posts.",
        "env": ("APIFY_API_TOKEN", "APIFY_TOKEN"),
        "cost": "Every run is billed to the Apify account. The test only reads the account (or, for a restricted token, its actor list) and is free.",
    },
}


def operator_emails() -> set:
    return {e.strip().lower() for e in (os.getenv("OPERATOR_EMAILS") or "").split(",") if e.strip()}


def is_operator(email: Optional[str], email_verified: bool) -> bool:
    return bool(email and email_verified and email.strip().lower() in operator_emails())


def _key(provider: str) -> str:
    from src.ai.core.env_secret import secret

    return secret(*PROVIDERS[provider]["env"])


def _redis():
    from src.ai.core.redis_client import get_redis_client

    return get_redis_client(socket_timeout=2, socket_connect_timeout=2)


def _alert_key(provider: str, code: str) -> str:
    return f"provider_alert:{provider}:{code}"


def status() -> List[dict]:
    """One row per provider. No values - only whether a key is set and the last problem seen (24 h)."""
    problems: Dict[str, dict] = {}
    try:
        client = _redis()
        for provider in PROVIDERS:
            for code in ALERT_CODES:
                seen = client.get(_alert_key(provider, code))
                if seen:
                    problems[provider] = {"code": code, "seen_at": seen}
    except Exception:  # noqa: BLE001 - the page works without Redis, it just can't show recent problems
        logger.warning("provider setup: recent problems unavailable (Redis)")
    return [
        {
            "provider": provider, "label": info["label"], "unlocks": info["unlocks"], "env": list(info["env"]),
            "cost": info["cost"], "configured": bool(_key(provider)), "recent_problem": problems.get(provider),
        }
        for provider, info in PROVIDERS.items()
    ]


# ---------------------------------------------------------------- connection test

def _classify_http(status_code: int) -> str:
    if status_code in (401, 403):
        return "rejected"
    if status_code == 429:
        return "quota_exhausted"
    return "valid" if status_code < 400 else "error"


def _test_google_places(key: str) -> str:
    response = httpx.get(
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        params={"input": "cafe", "inputtype": "textquery", "fields": "place_id", "key": key}, timeout=TIMEOUT,
    )
    state = (response.json() or {}).get("status")
    return {"OK": "valid", "ZERO_RESULTS": "valid", "REQUEST_DENIED": "rejected", "OVER_QUERY_LIMIT": "quota_exhausted"}.get(state, "error")


def _test_youtube(key: str) -> str:
    response = httpx.get(
        "https://www.googleapis.com/youtube/v3/videos", params={"part": "id", "id": "dQw4w9WgXcQ", "key": key}, timeout=TIMEOUT,
    )
    if response.status_code < 400:
        return "valid"
    try:
        reasons = {(e or {}).get("reason") for e in ((response.json() or {}).get("error") or {}).get("errors") or []}
    except ValueError:
        reasons = set()
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        return "quota_exhausted"
    return "rejected" if response.status_code in (400, 401, 403) else "error"


def _test_apify(key: str, evidence: Optional[dict] = None) -> str:
    """A restricted ("scoped") Apify token may not read the account: Apify answers 403 insufficient-permissions
    for /users/me although the token is valid. Its actor list then tells a valid token (200) from a bad one."""
    evidence = {} if evidence is None else evidence
    headers = {"Authorization": f"Bearer {key}"}
    response = httpx.get("https://api.apify.com/v2/users/me", headers=headers, timeout=TIMEOUT)
    evidence["account_http"] = response.status_code
    if response.status_code != 403:
        return _classify_http(response.status_code)
    actors = httpx.get("https://api.apify.com/v2/acts", params={"limit": 1}, headers=headers, timeout=TIMEOUT)
    evidence["actor_list_http"] = actors.status_code
    if actors.status_code < 400:
        evidence["actors_total"] = ((actors.json() or {}).get("data") or {}).get("total")
        return "valid_restricted"
    return "rejected" if actors.status_code in (401, 403) else _classify_http(actors.status_code)


def _test_groq(key: str, evidence: Optional[dict] = None) -> str:
    """The key, the configured model being available to it, and a real answer from that model."""
    from src.ai.rag import llm_client

    evidence = {} if evidence is None else evidence
    headers = {"Authorization": f"Bearer {key}"}
    models = httpx.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=TIMEOUT)
    evidence["models_http"] = models.status_code
    if models.status_code >= 400:
        return _classify_http(models.status_code)
    available = {m.get("id") for m in (models.json() or {}).get("data") or []}
    evidence.update(models=len(available), model=llm_client.MODEL_NAME)
    if llm_client.MODEL_NAME not in available:
        return "model_unavailable"
    answer = httpx.post(llm_client.GROQ_API_URL, headers=headers, timeout=30, json={
        "model": llm_client.MODEL_NAME, "max_tokens": 256,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
    })
    evidence["answer_http"] = answer.status_code
    if answer.status_code >= 400:
        return _classify_http(answer.status_code)
    choices = (answer.json() or {}).get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    evidence["answer"] = text[:40]
    return "valid" if text else "error"


def _test_tavily(key: str, evidence: Optional[dict] = None) -> str:
    """One real basic search. Tavily answers 432/433 when the plan's or the pay-as-you-go limit is reached."""
    evidence = {} if evidence is None else evidence
    response = httpx.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT,
                          json={"query": "Amman restaurant prices", "max_results": 1, "search_depth": "basic"})
    evidence["search_http"] = response.status_code
    if response.status_code in (432, 433):
        return "quota_exhausted"
    if response.status_code >= 400:
        return _classify_http(response.status_code)
    results = (response.json() or {}).get("results")
    if results is None:
        return "error"
    evidence["results"] = len(results)
    if results:
        evidence["first_source"] = urlsplit(results[0].get("url") or "").hostname
    return "valid"


_TESTS = {"groq": _test_groq, "tavily": _test_tavily, "google_places": _test_google_places, "youtube": _test_youtube,
          "apify": _test_apify}


def test_connection(provider: str) -> str:
    """valid | valid_restricted | rejected | quota_exhausted | model_unavailable | not_configured | error | too_soon.
    A cheap real call (two or three for Groq and a restricted Apify token); never returns provider text."""
    if provider not in PROVIDERS:
        raise KeyError(provider)
    key = _key(provider)
    if not key:
        return "not_configured"
    try:
        if not _redis().set(f"provider_test:{provider}", "1", nx=True, ex=TEST_COOLDOWN_SECONDS):
            return "too_soon"
    except Exception:  # noqa: BLE001 - no cooldown without Redis; the operator-only gate still applies
        pass
    try:
        result = _TESTS[provider](key)
    except Exception as exc:  # noqa: BLE001 - the exception text can carry the request URL, and so the key
        logger.warning("provider test %s failed: %s", provider, type(exc).__name__)
        return "error"
    if result in ("valid", "valid_restricted"):
        try:
            client = _redis()
            for code in ALERT_CODES:
                client.delete(_alert_key(provider, code))
        except Exception:  # noqa: BLE001
            pass
    return result


# ---------------------------------------------------------------- alert, once

def report_problem(provider: Optional[str], reason_code: Optional[str]) -> None:
    """Called when a collection reports a rejected key or a used-up quota. Emails the operators once per
    provider and problem per 24 h, however many companies hit it. Never raises."""
    if provider not in PROVIDERS or reason_code not in ALERT_CODES:
        return
    try:
        if not _redis().set(_alert_key(provider, reason_code), datetime.now(timezone.utc).isoformat(), nx=True, ex=ALERT_TTL_SECONDS):
            return
        logger.error("provider setup: %s reported %s", provider, reason_code)
        recipients = sorted(operator_emails())
        if not recipients:
            return
        from src.ai.core import notifications

        label = PROVIDERS[provider]["label"]
        what = "rejected the key" if reason_code == "CREDENTIALS_REJECTED" else "reports the daily quota is used up"
        body = (f"{label} {what}. Companies' data collection that needs it is paused or waiting.\n\n"
                "Open Settings > Service setup, run Test connection, and fix the key in the service's environment settings. "
                "This message is sent once per day per problem.")
        for address in recipients:
            notifications.send_email(address, f"KEEL service setup: {label} needs attention", body)
    except Exception:  # noqa: BLE001 - an alert problem must never break a collection
        logger.warning("provider setup: alert could not be sent")
