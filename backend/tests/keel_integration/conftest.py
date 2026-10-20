import os
os.environ.setdefault('JWT_SECRET','phase1a-isolated-unit-secret-at-least-32-bytes')

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.ai.core import security
from src.ai.routers import auth, platform


@pytest.fixture
def api(monkeypatch):
    # Explicit infrastructure boundary doubles; neither Redis nor PostgreSQL is certified here.
    monkeypatch.setattr(security,'is_token_revoked',lambda token:False)
    monkeypatch.setattr(security,'assert_active_principal',lambda *args:None)
    from src.ai.core import auth_throttle
    monkeypatch.setattr(auth_throttle,'ensure_allowed',lambda *a:None)
    monkeypatch.setattr(auth_throttle,'record_failure',lambda *a:False)
    monkeypatch.setattr(auth_throttle,'reset',lambda *a:None)
    app=FastAPI();app.include_router(auth.router);app.include_router(platform.router)
    with TestClient(app)as client:yield client


@pytest.fixture
def token():
    value,_=security.create_access_token('00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000002',email_verified=True)
    return {'Authorization':'Bearer '+value}
