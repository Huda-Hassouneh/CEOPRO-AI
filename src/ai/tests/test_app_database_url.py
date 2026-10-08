"""How src/ai/db.py builds the restricted app-role connection string: an
explicit APP_DATABASE_URL (hosted database, its own user) wins; otherwise
the local ceopro_app credentials are swapped into DATABASE_URL."""
import pytest

from src.ai import db


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("APP_DATABASE_URL", "APP_DB_PASSWORD", "APP_DB_USER", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


def test_explicit_app_database_url_is_used_as_is(monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "postgresql://ai_user:pw@db.example.com/ceopro?sslmode=require")
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:x@localhost:5432/other")
    assert db._app_database_url() == "postgresql://ai_user:pw@db.example.com/ceopro?sslmode=require"


def test_local_swap_keeps_host_port_database_and_query(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://ceopro_admin:admin@postgres:5432/ceopro_platform?sslmode=prefer")
    monkeypatch.setenv("APP_DB_PASSWORD", "app-secret")
    assert db._app_database_url() == "postgresql://ceopro_app:app-secret@postgres:5432/ceopro_platform?sslmode=prefer"


def test_missing_port_is_not_written_as_none(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:x@db.example.com/ceopro")
    monkeypatch.setenv("APP_DB_PASSWORD", "p")
    assert db._app_database_url() == "postgresql://ceopro_app:p@db.example.com/ceopro"


def test_user_name_is_configurable_and_special_characters_are_escaped(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:x@localhost:5432/ceopro")
    monkeypatch.setenv("APP_DB_USER", "ai_team")
    monkeypatch.setenv("APP_DB_PASSWORD", "p@ss:w/rd")
    assert db._app_database_url() == "postgresql://ai_team:p%40ss%3Aw%2Frd@localhost:5432/ceopro"


def test_nothing_configured_is_a_clear_error():
    with pytest.raises(RuntimeError, match="APP_DATABASE_URL"):
        db._app_database_url()
