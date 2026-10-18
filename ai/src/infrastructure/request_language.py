"""
The interface language of the request being served (en, ar, fr).

Set once per HTTP request by RequestLanguageMiddleware (from the frontend's
X-App-Language header, falling back to Accept-Language) and copied onto each
tenant connection as the transaction-local setting `app.lang` (db_pool.py).
SQL then picks a product's or category's name in that language with the
`localized_text(jsonb)` function (migration 20261008000000), so every screen
and the assistant show Arabic names in Arabic and never show an Arabic name
in English when an English one exists.
"""

from contextvars import ContextVar

SUPPORTED_LANGUAGES = ("en", "ar", "fr")
DEFAULT_LANGUAGE = "en"

_current_language: ContextVar[str] = ContextVar("apex_request_language", default=DEFAULT_LANGUAGE)


def normalize_language(value) -> str:
    """'ar-JO', 'AR', 'ar;q=0.9' -> 'ar'; anything unsupported -> 'en'."""
    if not value:
        return DEFAULT_LANGUAGE
    tag = str(value).split(",")[0].split(";")[0].strip().lower().replace("_", "-").split("-")[0]
    return tag if tag in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_request_language() -> str:
    return _current_language.get()


def set_request_language(value):
    """Returns the token so a caller can reset it (tests, middleware)."""
    return _current_language.set(normalize_language(value))


def reset_request_language(token) -> None:
    _current_language.reset(token)


class RequestLanguageMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware) so the context variable
    is set in the same context the endpoint - and its threadpool copy - runs
    in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        token = set_request_language(headers.get("x-app-language") or headers.get("accept-language"))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_language(token)
