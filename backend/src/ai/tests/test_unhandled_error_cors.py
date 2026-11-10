"""
Production incident (keelai.net, Nov 2026): Automated Marketing showed
"Couldn't reach KEEL. Check your connection and try again." while the API was
up. An unexpected exception became a 500 from Starlette's ServerErrorMiddleware,
the outermost layer - outside CORSMiddleware - so it carried no
Access-Control-Allow-Origin. The browser discarded it and the app only saw a
network error. Every KEEL screen was exposed to this, not only Marketing.

These tests pin the fix: the catch-all 500 carries the same CORS headers the API
gives any other response, and only for origins the API allows.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.ai.core.exceptions import _cors_headers_for, register_exception_handlers

ALLOWED = "https://keelai.net"


def _app():
    # The same layering as src/ai/main.py: CORSMiddleware, then the handlers.
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=[ALLOWED], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Retry-After"])
    register_exception_handlers(app)

    @app.post("/boom")
    def boom():
        raise RuntimeError("MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD must all be set.")

    @app.get("/handled")
    def handled():
        raise HTTPException(status_code=502, detail="handled")

    return TestClient(app, raise_server_exceptions=False)


def test_an_unexpected_error_reaches_the_browser_as_a_readable_500():
    response = _app().post("/boom", headers={"Origin": ALLOWED})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}  # never the exception text
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in response.headers["vary"]
    assert "MINIO" not in response.text


def test_an_origin_the_api_refuses_gets_no_cors_headers_on_errors_either():
    response = _app().post("/boom", headers={"Origin": "https://evil.example"})
    assert response.status_code == 500
    assert "access-control-allow-origin" not in response.headers


def test_a_request_without_an_origin_is_unchanged():
    response = _app().post("/boom")
    assert response.status_code == 500 and "access-control-allow-origin" not in response.headers


def test_handled_errors_keep_their_cors_headers():
    response = _app().get("/handled", headers={"Origin": ALLOWED})
    assert response.status_code == 502 and response.headers["access-control-allow-origin"] == ALLOWED


def test_the_real_api_configuration_is_used():
    """src/ai/main.py's own CORSMiddleware settings decide (default dev origin here)."""
    from src.ai.main import app

    def request(origin):
        return Request({"type": "http", "method": "POST", "path": "/", "app": app,
                        "headers": [(b"origin", origin.encode())]})

    headers = _cors_headers_for(request("http://localhost:5173"))
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert _cors_headers_for(request("https://evil.example")) == {}


def _wildcard_app(middleware_class=CORSMiddleware):
    app = FastAPI()
    app.add_middleware(middleware_class, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    register_exception_handlers(app)

    @app.post("/boom")
    def boom():
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def test_a_wildcard_configuration_follows_starlettes_own_rule_on_errors():
    """With allow_origins=["*"] Starlette echoes the origin only for a request with
    cookies and otherwise answers "*" - the 500 must be no looser than that."""
    without_cookie = _wildcard_app().post("/boom", headers={"Origin": "https://any.example"})
    assert without_cookie.status_code == 500
    assert without_cookie.headers["access-control-allow-origin"] == "*"
    with_cookie = _wildcard_app().post("/boom", headers={"Origin": "https://any.example", "Cookie": "a=b"})
    assert with_cookie.headers["access-control-allow-origin"] == "https://any.example"


def test_a_cors_middleware_subclass_is_still_found():
    class AppCORS(CORSMiddleware):
        pass

    app = FastAPI()
    app.add_middleware(AppCORS, allow_origins=[ALLOWED], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    register_exception_handlers(app)

    @app.post("/boom")
    def boom():
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).post("/boom", headers={"Origin": ALLOWED})
    assert response.status_code == 500 and response.headers["access-control-allow-origin"] == ALLOWED
