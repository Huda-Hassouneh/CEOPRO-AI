"""
Proves the three external services work FROM THIS MACHINE with the keys it
already has - real calls, not "the variable is set" - and then the
assistant end to end. Prints names, HTTP statuses and short evidence (model
count, a one-word model reply, search result counts, actor counts); never a
key or a header.

  1. Groq    - the key is accepted, the configured model (GROQ_MODEL) is
               available to it, and it writes a real reply.
  2. Tavily  - the key is accepted and one real basic search returns results
               (1 credit).
  3. Apify   - the token is accepted, read-only: the account, or for a
               restricted token its actor list. No actor is run (runs are billed).
  4. With --api/--email/--password: the assistant through the running API,
     the way the app uses it - one English and one Arabic question that need
     the company's own data AND public market research. Passes when each
     answer is written by the AI model (answer_mode "ai"), cites a company
     record, and research ran and read at least one web page.

Each failure is named: missing variable, pasted with spaces/quotes,
invalid key (401), no permission (403), quota (429/432/433), model not
available, or network.

Usage (from backend/, with the environment loaded; ./keel integrations does this):
    python -m scripts.integration_check
    python -m scripts.integration_check --api http://localhost:8000 --email you@example.com --password ...
    python -m scripts.integration_check --api https://<your-render-api>.onrender.com --email ... --password ...
Exit code 1 when any check fails.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from src.ai.core.env_secret import secret, shape_problem  # noqa: E402
from src.market_scraper import provider_setup  # noqa: E402

SERVICES = ("groq", "tavily", "apify")
PASSING = ("valid", "valid_restricted")
MEANING = {
    "valid": "works",
    "valid_restricted": "works (restricted token: it cannot read the account, which KEEL does not need)",
    "rejected": "the provider refused the key (invalid, revoked, or without permission for this API)",
    "quota_exhausted": "the key works but its quota or rate limit is used up",
    "model_unavailable": "the key works but the configured GROQ_MODEL is not available to it - set GROQ_MODEL to one it lists",
    "not_configured": "the variable is not set in this environment",
    "error": "the provider gave an unexpected answer",
}
QUESTIONS = (
    ("en", "Which of my products sell best, and what are restaurants in Amman charging for similar items right now?"),
    ("ar", "ما هي أكثر منتجاتي مبيعاً، وما هي أسعار المطاعم في عمّان لأصناف مشابهة حالياً؟"),
)


def check_service(name: str) -> bool:
    env = provider_setup.PROVIDERS[name]["env"]
    print(f"\n{provider_setup.PROVIDERS[name]['label']}  ({' / '.join(env)})")
    for variable in env:
        problem = shape_problem(variable)
        if problem:
            print(f"  note: {variable} {problem}")
    key = secret(*env)
    if not key:
        print(f"  FAIL - {MEANING['not_configured']}")
        return False
    evidence: dict = {}
    try:
        result = provider_setup._TESTS[name](key, evidence)  # noqa: SLF001 - the same call as Service setup
    except httpx.TimeoutException:
        result = "network: the provider did not answer in time"
    except httpx.HTTPError as exc:
        result = f"network: {type(exc).__name__} (DNS, firewall or proxy between this machine and the provider)"
    except ValueError:
        result = "error"
    shown = ", ".join(f"{k}={v}" for k, v in evidence.items())
    ok = result in PASSING
    print(f"  {'PASS' if ok else 'FAIL'} - {MEANING.get(result, result)}" + (f"\n  evidence: {shown}" if shown else ""))
    return ok


def check_assistant(api: str, email: str, password: str) -> bool:
    print(f"\nAssistant end to end via {api}")
    with httpx.Client(base_url=api.rstrip("/"), timeout=180) as http:
        signed = http.post("/auth/login", json={"email": email, "password": password})
        if signed.status_code != 200:
            print(f"  FAIL - sign-in answered HTTP {signed.status_code}")
            return False
        headers = {"Authorization": f"Bearer {signed.json()['access_token']}"}
        all_ok = True
        for language, question in QUESTIONS:
            response = http.post("/rag/query", params={"query_text": question}, headers=headers)
            if response.status_code != 200:
                print(f"  [{language}] FAIL - HTTP {response.status_code} {response.headers.get('X-Assistant-Reason') or ''}")
                all_ok = False
                continue
            body = response.json()
            kinds = [r.get("kind") for r in body.get("references") or []]
            research = body.get("research") or {}
            written_by_ai = body.get("answer_mode") == "ai"
            company = any(k in ("company_record", "company_summary", "company_document") for k in kinds)
            web = kinds.count("web_page")
            ok = written_by_ai and company and web > 0
            all_ok &= ok
            print(f"  [{language}] {'PASS' if ok else 'FAIL'} - answer_mode={body.get('answer_mode')}, company sources="
                  f"{sum(k in ('company_record', 'company_summary', 'company_document') for k in kinds)}, web pages cited={web}, "
                  f"research={research.get('status')} ({research.get('pages', 0)} page(s) read)")
            print(f"       {(body.get('answer_summary') or body.get('answer') or '')[:220]}".replace("\n", " "))
            if not written_by_ai:
                print("       -> the AI model did not write it (evidence mode): see the Groq check above")
            if not web:
                print(f"       -> no web research cited: {research.get('detail') or 'see the Tavily check above'}")
        return all_ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Real-call checks for Groq, Tavily and Apify, then the assistant.")
    parser.add_argument("--api", help="the running API (e.g. http://localhost:8000) for the assistant check")
    parser.add_argument("--email")
    parser.add_argument("--password", default=os.getenv("KEEL_CHECK_PASSWORD"))
    args = parser.parse_args(argv)
    print("KEEL integration check (real calls; no key is printed)")
    results = [check_service(name) for name in SERVICES]
    if args.api:
        if not (args.email and args.password):
            parser.error("--api needs --email and --password (or KEEL_CHECK_PASSWORD)")
        results.append(check_assistant(args.api, args.email, args.password))
    print(f"\n{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
