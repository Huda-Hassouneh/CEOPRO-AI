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


def test_native_billing_has_disposable_database_and_required_runtime_credentials():
    target = urlsplit(value("BILLING_TEST_DATABASE_URL"))
    assert target == urlsplit(value("DATABASE_URL"))
    assert target.hostname == "127.0.0.1" and target.path == "/keel_billing_test_ci"
    for name in ("BILLING_SETUP_DB_PASSWORD", "BILLING_WEBHOOK_DB_PASSWORD", "CREDIT_ACCOUNTING_DB_PASSWORD"):
        assert value(name).startswith("ci_test_")
    assert 'BILLING_DATABASE_TESTS: "1"' in BACKEND
    assert "BILLING_TEST_ENGINE: postgres" in BACKEND
    assert 'AI_TEST_REDIS_PORT: "6379"' in BACKEND
    assert 'STRIPE_SECRET_KEY: ""' in BACKEND
    assert "python -m scripts.billing_verification preflight" in BACKEND
    assert "python -m scripts.billing_verification test --database" in BACKEND
    assert "run: python -m pytest src/ -q" in BACKEND
    assert "node-version: '24'" in BACKEND
    assert "working-directory: frontend\n        run: npm ci" in BACKEND
    assert 'test -x "$CHROMIUM_PATH"' in BACKEND


def _native_billing_report_check():
    block = BACKEND.split("id: native-billing\n", 1)[1]
    import textwrap

    return textwrap.dedent(re.search(r"python - <<'PY'\n(.*?)\n          PY", block, re.S)[1])


def test_native_billing_report_accepts_executed_security_proofs(tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    report = ET.Element("testsuite")
    for name in ("test_native_runtime_role_password_authentication",
                 "test_restricted_runtime_role_cannot_forge_billing_or_read_another_tenant",
                 "test_password_authenticated_capabilities_do_not_overlap",
                 "test_setup_role_has_no_admin_ownership_or_memberships"):
        ET.SubElement(report, "testcase", name=name)
    ET.ElementTree(report).write(tmp_path / "native-billing.xml")
    exec(compile(_native_billing_report_check(), "native-billing-report-check", "exec"), {})


def test_native_billing_report_rejects_missing_prerequisites_or_skips(tmp_path, monkeypatch):
    import pytest
    import xml.etree.ElementTree as ET

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    for marker in ("skipped", "failure", "error"):
        report = ET.Element("testsuite")
        ET.SubElement(ET.SubElement(report, "testcase", name="billing_fixture"), marker)
        ET.ElementTree(report).write(tmp_path / "native-billing.xml")
        with pytest.raises(SystemExit, match="zero skips"):
            exec(compile(_native_billing_report_check(), "native-billing-report-check", "exec"), {})
    for contents in ("<testsuite/>", '<testsuite><testcase name="unit_only"/></testsuite>'):
        (tmp_path / "native-billing.xml").write_text(contents)
        with pytest.raises(SystemExit):
            exec(compile(_native_billing_report_check(), "native-billing-report-check", "exec"), {})
    (tmp_path / "native-billing.xml").unlink()
    with pytest.raises(FileNotFoundError):
        exec(compile(_native_billing_report_check(), "native-billing-report-check", "exec"), {})


def test_native_billing_runner_propagates_pytest_failure(monkeypatch):
    from types import SimpleNamespace
    from scripts import billing_verification

    monkeypatch.setenv("BILLING_TEST_DATABASE_URL", "postgresql://ci:ci@127.0.0.1:5432/keel_billing_test_ci")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    calls = []

    def failed_pytest(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(billing_verification.subprocess, "run", failed_pytest)
    assert billing_verification.main(["test", "--database"]) == 1
    command, options = calls[0]
    assert "tests/billing" in command
    assert options["env"]["BILLING_DATABASE_TESTS"] == "1"
