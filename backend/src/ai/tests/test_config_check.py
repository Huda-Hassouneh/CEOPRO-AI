"""Configuration check (core/config_check.py): required settings, formats,
deployed-only rules, half-set integrations - and never a value in a finding."""
import pytest
from cryptography.fernet import Fernet

from src.ai.core import config_check
from src.market_scraper import data_requirements

SETTINGS = ("JWT_SECRET", "DATABASE_URL", "APP_DB_PASSWORD", "REDIS_URL", "REDIS_HOST", "UNASSIGNED_PLAN_ACCESS",
            "CREDENTIAL_VAULT_KMS_BACKEND", "CREDENTIAL_VAULT_MASTER_KEY", "CREDENTIAL_VAULT_PREVIOUS_KEYS", "AWS_KMS_KEY_ID",
            "PUBLIC_FRONTEND_ORIGIN", "FRONTEND_URL", "FRONTEND_BASE_URL", "APP_BASE_URL", "CORS_ALLOWED_ORIGINS", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD",
            "EMAIL_FROM_ADDRESS", "EMAIL_LOG_UNSENT_BODIES", "MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
            "SENTRY_ENVIRONMENT", "GROQ_API_KEY", "PAID_LLM_BASE_URL", "PAID_LLM_API_KEY", "HUGGINGFACE_LLM_MODEL",
            "LOCAL_LLM_BASE_URL", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_API_TOKEN", "GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX", "POSTGRES_PASSWORD",
            "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "SEARXNG_INSTANCE_URL", "WEB_SEARCH_PROVIDERS",
            *config_check.IGNORED_NAMES, *data_requirements.known_names())


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


def test_public_origin_is_the_single_link_and_payment_setting(env):
    env.setenv('SENTRY_ENVIRONMENT','production')
    env.setenv('PUBLIC_FRONTEND_ORIGIN','https://app.example.test')
    env.setenv('CORS_ALLOWED_ORIGINS','https://app.example.test')
    findings=_by_setting(config_check.check_environment())
    assert not {('error','FRONTEND_BASE_URL'),('error','APP_BASE_URL'),('error','PUBLIC_FRONTEND_ORIGIN')} & findings


@pytest.mark.parametrize('value',['https://app.example.test/path','https://user:private@example.test','http://public.example.test'])
def test_unsafe_public_origin_is_a_configuration_error_without_echoing_its_value(env,value):
    env.setenv('PUBLIC_FRONTEND_ORIGIN',value)
    findings=config_check.check_environment()
    assert ('error','PUBLIC_FRONTEND_ORIGIN') in _by_setting(findings)
    assert all('user:private' not in item.line() for item in findings)


def test_disagreeing_legacy_origins_require_an_explicit_authority(env):
    env.setenv('FRONTEND_BASE_URL','http://localhost:5173')
    env.setenv('APP_BASE_URL','http://127.0.0.1:5204')
    assert ('error','PUBLIC_FRONTEND_ORIGIN') in _by_setting(config_check.check_environment())


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
    for name in data_requirements.declared_names():
        env.setenv(name, "set")
    assert config_check.check_environment() == []


def test_no_web_search_provider_is_reported_by_name(env):
    findings = [f for f in config_check.check_environment() if f.setting == "TAVILY_API_KEY"]
    assert findings and findings[0].level == config_check.WARNING and "research" in findings[0].message
    env.setenv("SEARXNG_INSTANCE_URL", "http://searxng:8080")
    assert not [f for f in config_check.check_environment() if f.setting == "TAVILY_API_KEY"]


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


def test_missing_competitor_data_settings_name_what_they_block(env):
    env.setenv("SENTRY_ENVIRONMENT", "staging")
    env.setenv("TAVILY_API_KEY", "tvly-test")
    env.setenv("GOOGLE_PLACES_API_KEY", "a-places-key")
    env.setenv("APIFY_TOKEN", "an-apify-key")  # the older name still counts
    findings = {f.setting: f.message for f in config_check.check_environment() if f.level == config_check.WARNING}
    assert "Video comments" in findings["YOUTUBE_API_KEY"]
    # One line per setting, naming every facet it blocks.
    assert "Google reviews" in findings["SCRAPER_ACTOR_USER_ID"] and "Video comments" in findings["SCRAPER_ACTOR_USER_ID"]
    assert "GOOGLE_PLACES_API_KEY" not in findings and "APIFY_API_TOKEN" not in findings and "TAVILY_API_KEY" not in findings
    assert "Service setup" in findings["OPERATOR_EMAILS"]
    assert not any("a-places-key" in m or "an-apify-key" in m for m in findings.values())
