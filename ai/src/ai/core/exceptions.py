"""
KEEL - Global exception handling.

Every endpoint in this service already converts its own known failure
modes into an HTTPException with a specific status/detail (a 404 for a
missing product, a 502 for an upstream LLM failure, etc.) - FastAPI's
built-in HTTPException handling already returns those exactly as written,
{"detail": <str>}, and this module does not touch that path at all.

What was genuinely missing: a truly UNEXPECTED exception (a real bug, not
one of the cases an endpoint already anticipated) fell through to
FastAPI/Starlette's own default handler, which by default re-raises in a
way that either crashes the worker or (depending on server config) leaks
a raw traceback to the caller - neither is acceptable for a production
API. register_exception_handlers() below is the single place that catches
anything an endpoint didn't already handle, logs the real exception
server-side (so it's still debuggable), and returns the exact same
{"detail": "..."} shape every other error response already uses - a
caller can always read response.json()["detail"] regardless of which
error path produced it, never a differently-shaped body depending on
whether the failure was anticipated.
"""

import logging

import psycopg2.errors
import psycopg2.pool

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("CEOPRO_AI_MAIN")


def register_exception_handlers(app: FastAPI) -> None:
    from src.ai.core.usage import PlanLimitReached

    @app.exception_handler(PlanLimitReached)
    async def _plan_limit_handler(request: Request, exc: PlanLimitReached) -> JSONResponse:
        # A company used its plan's allowance (src/ai/core/usage.py): one
        # consistent 402 body wherever it is raised, so routers don't each
        # translate it - and it never surfaces as a 500.
        http = exc.as_http()
        return JSONResponse(status_code=http.status_code, content={"detail": http.detail})

    from src.ai.billing.credits import BudgetError

    @app.exception_handler(BudgetError)
    async def _budget_handler(request: Request, exc: BudgetError) -> JSONResponse:
        # A paid provider call refused before it was made (billing/credits.py):
        # reason code and plain message only - never provider names or prices.
        http = exc.as_http()
        return JSONResponse(status_code=http.status_code, content={"detail": http.detail})

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Re-implements Starlette's own default HTTPException body exactly
        # ({"detail": ...}) - registering a handler for it at all is only
        # necessary so this module owns every error path with ONE
        # consistent shape/logging point, not because the default
        # behavior for an already-raised HTTPException was wrong.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's own default 422 body is already {"detail": [...]} -
        # preserved as-is (existing tests already assert status_code==422
        # for this path); only reason to register this explicitly is so a
        # validation failure logs at the same place as every other error
        # instead of bypassing this module entirely.
        #
        # Real bug this fixes: a Pydantic v2 @field_validator that raises a
        # plain ValueError (e.g. routers/products.py's product_name-
        # requires-"en"-key check) makes exc.errors() embed the original
        # ValueError OBJECT under each error's ctx.error key, not a string -
        # the stdlib json module can't serialize that (TypeError: Object of
        # type ValueError is not JSON serializable), turning an intended
        # 422 into an unhandled 500 the moment that validator's message
        # ever fires. jsonable_encoder() alone "fixes" the crash but
        # serializes a bare exception (no public attributes of its own) as
        # an unhelpful {} - the caller loses the actual validation message.
        # Stringifying ctx.error explicitly first preserves it.
        errors = exc.errors()
        for error in errors:
            ctx = error.get("ctx")
            if isinstance(ctx, dict) and isinstance(ctx.get("error"), Exception):
                ctx["error"] = str(ctx["error"])
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @app.exception_handler(psycopg2.errors.InvalidTextRepresentation)
    async def _invalid_identifier_handler(request: Request, exc: psycopg2.errors.InvalidTextRepresentation) -> JSONResponse:
        # A malformed id (e.g. GET /products/not-a-uuid) used to reach
        # Postgres as-is and come back as a generic 500 - found in live
        # acceptance testing on every {id} route. It's a client error, not
        # a server one: a path id that can't be a UUID names a resource
        # that can't exist (404, same as any other unknown id, so it leaks
        # nothing about other tenants); a malformed id in the body/query
        # is invalid input (422). Anything that isn't a bad-uuid input
        # still goes through the generic 500 path below so real bugs stay
        # visible.
        message = str(exc)
        if "type uuid" not in message:
            return await _unhandled_exception_handler(request, exc)
        path_values = [str(v) for v in request.path_params.values()]
        if any(f'"{value}"' in message for value in path_values):
            return JSONResponse(status_code=404, content={"detail": "Not found."})
        return JSONResponse(status_code=422, content={"detail": "One or more identifiers are not valid."})

    @app.exception_handler(psycopg2.pool.PoolError)
    async def _busy_handler(request: Request, exc: psycopg2.pool.PoolError) -> JSONResponse:
        # Every database connection stayed busy for the whole checkout wait
        # (infrastructure/db_pool.py): the service is overloaded, not broken.
        # Say so and when to retry, instead of a generic 500.
        logger.warning("Database connections busy on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=503, content={"detail": "KEEL is very busy right now. Please try again in a moment."},
                            headers={"Retry-After": "5"})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # The real fix: a bug in code that ISN'T already wrapped in a
        # try/except HTTPException (every endpoint in this service
        # otherwise is) no longer leaks its message/traceback to the
        # caller - logged in full server-side (exc_info=True) for real
        # debugging, but the response is the same generic, safe shape
        # every other error already returns.
        logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
