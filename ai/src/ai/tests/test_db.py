"""
Unit tests for src/ai/db.py::_app_database_url() - no DB required.

Regression test for a real bug: reconstructing the ceopro_app DSN used
parsed.port directly, which urlparse leaves as None whenever the source
URL omits an explicit port - exactly Neon's standard copy-paste format
(postgresql://user:pass@ep-xxx.aws.neon.tech/db?sslmode=require, no
":5432"). That produced a DSN with the literal text "None" as the port,
which psycopg2 rejects with OperationalError before any query ever runs.
Every local/docker-compose DATABASE_URL already includes ":5432"
explicitly, which is why this was invisible to every other test and to
local development, and only surfaced against real Neon-hosted staging.
"""
import os
from unittest.mock import patch

from src.ai.db import _app_database_url


def test_app_database_url_defaults_port_when_source_url_omits_it():
    env = {
        "DATABASE_URL": "postgresql://ceopro_admin:adminpass@ep-example.aws.neon.tech/neondb?sslmode=require",
        "APP_DB_PASSWORD": "app-secret",
    }
    with patch.dict(os.environ, env, clear=False):
        result = _app_database_url()

    assert ":None" not in result
    assert "ceopro_app:app-secret@ep-example.aws.neon.tech:5432/neondb?sslmode=require" == result.split("://", 1)[1]


def test_app_database_url_preserves_explicit_port():
    env = {
        "DATABASE_URL": "postgresql://ceopro_admin:adminpass@postgres:5433/ceopro",
        "APP_DB_PASSWORD": "app-secret",
    }
    with patch.dict(os.environ, env, clear=False):
        result = _app_database_url()

    assert result == "postgresql://ceopro_app:app-secret@postgres:5433/ceopro"
