"""Prevent CI configuration from violating the application's disposable DB guard."""
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = (ROOT / ".github/workflows/pr-checks.yml").read_text(encoding="utf-8")
BACKEND = WORKFLOW.split("  backend:\n", 1)[1].split("\n  frontend:", 1)[0]


def value(name):
    return re.search(r"^\s+" + name + r":\s*(\S+)", BACKEND, re.M)[1]


def test_ci_database_identity_satisfies_disposable_guard_without_relaxing_it():
    database = value("POSTGRES_DB")
    assert database.startswith("keel_billing_test_")
    for name in ("DATABASE_URL", "AI_TEST_DATABASE_URL", "SCRAPER_DATABASE_URL"):
        target = urlsplit(value(name))
        assert target.hostname == "127.0.0.1" and target.path == "/" + database
    assert urlsplit(value("SCRAPER_DATABASE_URL")).username == "ceopro_app"
    assert urlsplit(value("SCRAPER_DATABASE_URL")).password == value("APP_DB_PASSWORD")
    assert "KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION:" not in BACKEND
    assert value("FRONTEND_BASE_URL") == "http://localhost:5173"


def test_python_security_audit_is_required_and_has_no_advisory_exceptions():
    assert 'pip-audit -r "$RUNNER_TEMP/installed.txt"' in BACKEND
    assert "--ignore-vuln" not in BACKEND
    assert "continue-on-error" not in BACKEND
    assert "pip check" in BACKEND


def test_browser_fixture_waits_for_real_readiness_and_uses_verified_signup():
    browser = WORKFLOW.split("  browser-smoke:\n", 1)[1]
    assert "http://localhost:8000/health/ready" in browser
    assert "scripts.ci_smoke_account" in browser and "--test-email-verification-fixture" in browser
    assert "npm run test:browser" in browser and "npm run test:a11y" in browser
    assert "continue-on-error" not in browser
