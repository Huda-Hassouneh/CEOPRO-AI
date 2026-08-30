"""
CEOPRO AI - Service Entrypoint (PENDING_ACTIONS.md #2/#25, RED_FLAGS.md's
Critical "ceopro_admin unconditionally bypasses RLS" entry).

Before this file existed, nothing in the deployed system ever connected to
Postgres as anything other than the superuser ceopro_admin - RLS policies
were correct and regression-tested (tests/test_rls_integration_db.py) but
provided zero actual isolation, since superusers bypass RLS unconditionally
regardless of policy correctness. This is the first real request path that
connects as the restricted ceopro_app role (via db.app_role_connection())
and sets app.current_tenant_id/app.current_user_id per request.

One thin HTTP endpoint per already-built pipeline entry point (pricing/,
sentiment/, mpi/, extraction/ - the four modules this track owns per
DATA_OWNERSHIP_AND_CONTRACTS.md). forecasting/ is deliberately not
duplicated here - it already has a real trigger, forecasting/consumer.py's
Redis Streams consumer.

Auth: decodes a Bearer JWT (JWT_SECRET, HS256) for tenant_id/user_id claims.
Flagged explicitly, not silently assumed: no JWT-issuing service or claim-
shape contract exists anywhere else in this repo today - security.py only
validates an internal service-to-service token, unrelated. tenant_id/user_id
is this session's own reasonable default (matching what the RLS session
variables and .env.example's JWT_SECRET comment already imply), not a
confirmed contract with a real auth service - worth reconciling once one
exists.
"""

import os
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException

from src.ai import db
from src.ai.extraction import pipeline as extraction_pipeline
from src.ai.mpi import pipeline as mpi_pipeline
from src.ai.pricing import pipeline as pricing_pipeline
from src.ai.sentiment import pipeline as sentiment_pipeline

app = FastAPI(title="CEOPRO AI Service")


class TenantContext:
    def __init__(self, tenant_id: str, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id


def get_tenant_context(authorization: Optional[str] = Header(default=None)) -> TenantContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")

    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set.")

    token = authorization[len("Bearer "):]
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Token is missing tenant_id/user_id claims.")

    return TenantContext(tenant_id=tenant_id, user_id=user_id)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/pricing/recommend")
def pricing_recommend(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = pricing_pipeline.run_price_recommendation(conn, ctx.tenant_id, product_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/sentiment/analyze-pending")
def sentiment_analyze_pending(batch_size: int = 100, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.classify_and_store_reviews(conn, ctx.tenant_id, batch_size)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/sentiment/summary")
def sentiment_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    country_context: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = sentiment_pipeline.get_subject_sentiment_summary(
            conn, ctx.tenant_id, subject_type, subject_id, country_context
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/mpi/summary")
def mpi_summary(
    subject_type: str,
    subject_id: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = mpi_pipeline.get_subject_mpi(conn, ctx.tenant_id, subject_type, subject_id)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.post("/extraction/process-pending")
def extraction_process_pending(limit: int = 100, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        news_count = extraction_pipeline.extract_and_store_news_records(conn, ctx.tenant_id, None, limit)
        mentions_count = extraction_pipeline.extract_and_store_social_mentions(conn, ctx.tenant_id, None, limit)
        conn.commit()
        return {"news_processed": news_count, "social_mentions_processed": mentions_count}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
