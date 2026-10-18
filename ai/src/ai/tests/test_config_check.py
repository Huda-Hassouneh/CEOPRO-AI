"""Configuration check (core/config_check.py): required settings, formats,
deployed-only rules, half-set integrations - and never a value in a finding."""
import pytest
from cryptography.fernet import Fernet

from src.ai.core import config_check

SETTINGS = ("JWT_SECRET", "DATABASE_URL", "APP_DB_PASSWORD", "REDIS_URL", "REDIS_HOST", "UNASSIGNED_PLAN_ACCESS",
            "CREDENTIAL_VAULT_KMS_BACKEND", "CREDENTIAL_VAULT_MASTER_KEY", "CREDENTIAL_VAULT_PREVIOUS_KEYS", "AWS_KMS_KEY_ID",
            "FRONTEND_BASE_URL", "APP_BASE_URL", "CORS_ALLOWED_ORIGINS", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD",
            "EMAIL_FROM_ADDRESS", "EMAIL_LOG_UNSENT_BODIES", "MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
            "SENTRY_ENVIRONMENT", "GROQ_API_KEY", "PAID_LLM_BASE_URL", "PAID_LLM_API_KEY", "HUGGINGFACE_LLM_MODEL",
            "LOCAL_LLM_BASE_URL", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_API_TOKEN", "GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX", "POSTGRES_PASSWORD",
            *config_check.IGNORED_NAMES)


@pytest.fixture
def env(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    good = {
        "JWT_SECRET": "j" * 64, "DATABASE_URL": "postgresql://u:p@db:5432/x", "APP_DB_PASSWORD": "app-password",
        "REDIS_URL": "redis://r:6379/0", "CREDENTIAL_VAULT_MASTER_KEY": Fernet.generate_key().decode(),
        "GROQ_API_KEY": "gsk_test",
    }
    for name, value in good.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _by_setting(findings):
    return {(f.level, f.setting) for f in findings}


def test_a_complete_local_setup_has_no_errors(env):
    assert not [f for f in config_check.check_environment() if f.level == config_check.ERROR]


def test_required_settings_are_errors(env):
    for name in ("JWT_SECRET", "DATABASE_URL", "APP_DB_PASSWORD"):
        env.delenv(name)
    found = _by_setting(config_check.check_environment())
    assert {("error", "JWT_SECRET"), ("error", "DATABASE_URL"), ("error", "APP_DB_PASSWORD")} <= found


def test_a_hex_vault_key_is_an_error_and_its_value_never_appears(env):
    hex_key = "cd" * 32
    env.setenv("CREDENTIAL_VAULT_MASTER_KEY", hex_key)
    findings = config_check.check_environment()
    assert ("error", "CREDENTIAL_VAULT_MASTER_KEY") in _by_setting(findings)
    assert all(hex_key not in f.line() for f in findings)


def test_deployed_rules(env):
    env.setenv("SENTRY_ENVIRONMENT", "staging")
    env.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    env.setenv("CORS_ALLOWED_ORIGINS", "https://api.example.com/")
    env.setenv("UNASSIGNED_PLAN_ACCESS", "default")
    env.setenv("EMAIL_LOG_UNSENT_BODIES", "true")
    found = _by_setting(config_check.check_environment())
    assert {("error", "FRONTEND_BASE_URL"), ("error", "APP_BASE_URL"), ("error", "CORS_ALLOWED_ORIGINS"),
            ("error", "UNASSIGNED_PLAN_ACCESS"), ("error", "EMAIL_LOG_UNSENT_BODIES")} <= found
    assert ("warning", "SMTP_HOST") in found and ("warning", "MINIO_ENDPOINT") in found


def test_a_correct_deployment_passes(env):
    env.setenv("SENTRY_ENVIRONMENT", "production")
    for name in ("FRONTEND_BASE_URL", "APP_BASE_URL"):
        env.setenv(name, "https://app.example.com")
    env.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM_ADDRESS",
                 "MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        env.setenv(name, "https://storage.example.com" if name == "MINIO_ENDPOINT" else "set")
    assert config_check.check_environment() == []


def test_cors_must_name_the_frontend_not_the_api(env):
    env.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    env.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:8000")
    assert ("warning", "CORS_ALLOWED_ORIGINS") in _by_setting(config_check.check_environment())


def test_half_set_pairs_and_ignored_names_are_reported(env):
    env.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    env.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    env.setenv("GEMINI_API_KEYS", "anything")
    found = _by_setting(config_check.check_environment())
    assert {("warning", "CLOUDFLARE_API_TOKEN"), ("warning", "STRIPE_WEBHOOK_SECRET"), ("warning", "GEMINI_API_KEYS")} <= found


def test_no_language_model_is_a_warning(env):
    env.delenv("GROQ_API_KEY")
    assert ("warning", "GROQ_API_KEY") in _by_setting(config_check.check_environment())
