"""
CEOPRO AI - Standalone RAG Chat REPL (terminal-based test interface).

Zero extra dependencies beyond what src/ai/requirements.txt already
installs (httpx, PyJWT) - talks to a running `uvicorn src.ai.main:app`
over plain HTTP, the same POST /rag/query endpoint any real client would
use. No login flow exists yet (main.py's own docstring: "no JWT-issuing
service... exists anywhere else in this repo today"), so this mints its
own test JWT locally with JWT_SECRET - the same secret the running
service was started with - rather than inventing a second auth path.

Usage (from the repo root, with the AI service already running):
    export JWT_SECRET=...            # must match the running service's JWT_SECRET
    export AI_TENANT_ID=<uuid>       # a real tenant_id with ingested RAG documents
    export AI_USER_ID=<uuid>         # optional - any tenant_users.user_id for that tenant
    python -m src.ai.rag.chat_cli    # defaults to http://localhost:8000

Type a question and press Enter to send it. Type 'exit' or 'quit' to leave.
"""
import os
import sys
import uuid

import httpx
import jwt

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TOP_K = 5
REQUEST_TIMEOUT_SECONDS = 60.0


def _mint_token(secret: str, tenant_id: str, user_id: str) -> str:
    return jwt.encode({"tenant_id": tenant_id, "user_id": user_id}, secret, algorithm="HS256")


def _ask(base_url: str, token: str, query_text: str, top_k: int) -> dict:
    response = httpx.post(
        f"{base_url}/rag/query",
        params={"query_text": query_text, "top_k": top_k},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _render_answer(result: dict) -> None:
    print(f"\nAssistant: {result.get('answer', '(no answer field returned)')}\n")
    sources = result.get("sources") or []
    if sources:
        print("Sources:")
        for source in sources:
            print(f"  [{source.get('source_index')}] chunk={source.get('chunk_id')} score={source.get('score')}")
    print()


def _resolve_config():
    base_url = os.getenv("AI_SERVICE_URL", DEFAULT_BASE_URL)
    secret = os.getenv("JWT_SECRET")
    tenant_id = os.getenv("AI_TENANT_ID")
    user_id = os.getenv("AI_USER_ID") or str(uuid.uuid4())

    if not secret:
        print("JWT_SECRET is not set - export the same secret the running AI service uses.")
        sys.exit(1)
    if not tenant_id:
        print("AI_TENANT_ID is not set - export a real tenant_id that has ingested RAG documents.")
        sys.exit(1)
    return base_url, secret, tenant_id, user_id


def main() -> None:
    base_url, secret, tenant_id, user_id = _resolve_config()
    token = _mint_token(secret, tenant_id, user_id)
    print(f"Connected to {base_url} as tenant {tenant_id}. Type 'exit' to quit.\n")

    while True:
        try:
            query_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not query_text:
            continue
        if query_text.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        try:
            result = _ask(base_url, token, query_text, DEFAULT_TOP_K)
        except httpx.ConnectError:
            print(f"Could not reach {base_url} - is `uvicorn src.ai.main:app` running?\n")
            continue
        except httpx.HTTPStatusError as e:
            print(f"Request failed ({e.response.status_code}): {e.response.text}\n")
            continue

        _render_answer(result)


if __name__ == "__main__":
    main()
