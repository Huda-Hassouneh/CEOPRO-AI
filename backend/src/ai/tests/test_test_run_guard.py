"""The backend conftest refuses to run tests against hosted databases or Redis."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("backend_root_conftest", Path(__file__).resolve().parents[3] / "conftest.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def test_loopback_and_container_service_names_are_local():
    for host in (None, "localhost", "127.0.0.1", "127.0.0.2", "::1", "[::1]", "postgres", "redis"):
        assert guard.is_local_host(host), host


def test_hosted_names_are_remote():
    for host in ("ep-x-pooler.c-5.us-west-2.aws.neon.tech", "summary-yak-1.upstash.io", "db.example.com", "10.0.0.5"):
        assert not guard.is_local_host(host), host


def test_remote_settings_are_reported_by_name_and_host_without_credentials():
    env = {
        "DATABASE_URL": "postgresql://owner:s3cret@ep-x-pooler.neon.tech/neondb",
        "REDIS_URL": "rediss://default:t0ken@summary-yak-1.upstash.io:6379",
        "AI_TEST_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/test",
        "AI_TEST_REDIS_HOST": "localhost",
    }
    problems = guard.remote_service_settings(env)
    assert problems == ["DATABASE_URL -> ep-x-pooler.neon.tech", "REDIS_URL -> summary-yak-1.upstash.io"]
    assert not any("s3cret" in p or "t0ken" in p for p in problems)


def test_local_ci_settings_pass():
    env = {
        "DATABASE_URL": "postgresql://ceopro_admin:pw@127.0.0.1:5432/keel_billing_test_ci",
        "AI_TEST_MANAGED_PG_ADMIN_URL": "postgresql://postgres:pw@127.0.0.1:5433/postgres",
        "REDIS_URL": "redis://localhost:6379/0",
        "SCRAPER_DATABASE_URL": "postgresql://ceopro_app:pw@postgres:5432/x",
    }
    assert guard.remote_service_settings(env) == []
