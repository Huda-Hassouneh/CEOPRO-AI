"""
KEEL - configuration check against backend/KEYS_AND_ACCOUNTS_NEEDED.md.

Run at API start-up (every finding is logged) and by
`python -m scripts.check_config`. Findings name a setting and what is wrong
with it - never its value. "error": a required setting is missing or
unusable, or a setting is unsafe where it is deployed. "warning": an
optional integration is half-configured or off. Nothing here changes a
setting or switches a provider on.

Deployed = SENTRY_ENVIRONMENT is staging or production (set in render.yaml);
there https addresses, a real email service and no local-only settings are
required.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

ERROR, WARNING = "error", "warning"

# Names the code never reads (older checklist): set only by mistake.
IGNORED_NAMES = ("CLOUDFLARE_ACCOUNTS", "HUGGINGFACE_API_TOKENS", "GEMINI_API_KEYS", "TOGETHER_API_KEYS",
                 "HORDE_API_KEYS", "POLLINATIONS_API_KEYS")

# Settings that must be set together.
PAIRS = (
    ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
    ("GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX"),
    ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"),
    ("PAID_LLM_BASE_URL", "PAID_LLM_API_KEY"),
)

# Paid integrations: setting(s) that turn them on -> the cost schedule rows
# a call needs (budget, provider, operation, units). Without a confirmed
# price for every unit the integration's calls are refused (billing/credits.py).
PAID_INTEGRATIONS: Dict[str, Tuple[Tuple[str, ...], str, str, Optional[str], Tuple[str, ...]]] = {
    "Google Places / Geocoding": (("GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_API_KEY"), "data", "google_places", "text_search", ("request",)),
    "Google Custom Search": (("GOOGLE_CUSTOM_SEARCH_API_KEY",), "data", "google_cse", "search", ("request",)),
    "Brave Search": (("BRAVE_SEARCH_API_KEY",), "data", "brave_search", "search", ("request",)),
    "Tavily": (("TAVILY_API_KEY",), "data", "tavily", "search", ("request",)),
    "SerpAPI": (("SERPAPI_API_KEY",), "data", "serpapi", "search", ("request",)),
    "Apify": (("APIFY_API_TOKEN", "APIFY_TOKEN"), "data", "apify", "actor_run", ("record",)),
    "Cloudflare images": (("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNTS"), "ai", "cloudflare", "image_generation", ("image",)),
    "Hugging Face images": (("HUGGINGFACE_API_TOKEN", "HUGGINGFACE_API_TOKENS"), "ai", "huggingface", "image_generation", ("image",)),
}


@dataclass(frozen=True)
class Finding:
    level: str
    setting: str
    message: str

    def line(self) -> str:
        return f"[{self.level}] {self.setting}: {self.message}"


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def deployed() -> bool:
    return _env("SENTRY_ENVIRONMENT").lower() in ("staging", "production")


def _is_local(host: Optional[str]) -> bool:
    return (host or "") in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or (host or "").endswith(".local")


def _url_problem(value: str, is_deployed: bool) -> Optional[str]:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "is not an http(s) address"
    if value.endswith("/"):
        return "ends with '/' (remove it)"
    if is_deployed and parsed.scheme != "https":
        return "must use https where KEEL is deployed"
    if is_deployed and _is_local(parsed.hostname):
        return "points at this machine (localhost) where KEEL is deployed"
    return None


def _origin_problem(origin: str, is_deployed: bool) -> Optional[str]:
    problem = _url_problem(origin, is_deployed)
    if problem:
        return problem
    if urlparse(origin).path not in ("", None):
        return "must be an origin only (scheme://host[:port]), without a path"
    return None


def active_llm_provider() -> Optional[Tuple[str, str]]:
    """(provider, model) the AI calls will use, as rag/llm_client.py picks
    it, or None when no provider can be called."""
    if _env("PAID_LLM_BASE_URL"):
        return ("paid", _env("PAID_LLM_MODEL") or _env("GROQ_MODEL") or "openai/gpt-oss-20b")
    if _env("HUGGINGFACE_LLM_MODEL"):
        return ("huggingface", _env("HUGGINGFACE_LLM_MODEL")) if _env("HUGGINGFACE_API_TOKEN") else None
    if _env("LOCAL_LLM_BASE_URL"):
        return ("local", _env("GROQ_MODEL") or "openai/gpt-oss-20b")
    if _env("GROQ_API_KEY"):
        return ("groq", _env("GROQ_MODEL") or "openai/gpt-oss-20b")
    return None


def check_environment() -> List[Finding]:
    """Everything that can be checked without a database."""
    out: List[Finding] = []
    is_deployed = deployed()

    def add(level, setting, message):
        out.append(Finding(level, setting, message))

    # --- required ---------------------------------------------------------------
    jwt = _env("JWT_SECRET")
    if not jwt:
        add(ERROR, "JWT_SECRET", "is not set - the API refuses to start")
    elif len(jwt) < 32:
        add(ERROR if is_deployed else WARNING, "JWT_SECRET", "is shorter than 32 characters - generate one with `openssl rand -hex 32`")
    if not _env("DATABASE_URL"):
        add(ERROR, "DATABASE_URL", "is not set")
    if not _env("APP_DB_PASSWORD"):
        add(ERROR, "APP_DB_PASSWORD", "is not set - the restricted application database role can't connect")
    if not (_env("REDIS_URL") or _env("REDIS_HOST")):
        add(WARNING, "REDIS_URL", "is not set - using localhost:6379")
    access = _env("UNASSIGNED_PLAN_ACCESS") or "none"
    if access not in ("none", "default"):
        add(ERROR, "UNASSIGNED_PLAN_ACCESS", "must be 'none' or 'default'")
    elif access == "default" and is_deployed:
        add(ERROR, "UNASSIGNED_PLAN_ACCESS", "is 'default' - companies without a plan get free access; use 'none' where KEEL is deployed")
    for name in ("POSTGRES_PASSWORD", "APP_DB_PASSWORD", "MINIO_ROOT_PASSWORD"):
        if _env(name).lower().startswith("change_this") and is_deployed:
            add(ERROR, name, "is still the .env.example placeholder")

    # --- credential vault ---------------------------------------------------------
    from src.market_scraper import credential_vault

    backend = (_env("CREDENTIAL_VAULT_KMS_BACKEND") or "local").lower()
    if backend == "local":
        problem = credential_vault.master_key_problem(_env("CREDENTIAL_VAULT_MASTER_KEY"))
        if problem:
            add(ERROR, "CREDENTIAL_VAULT_MASTER_KEY", f"{problem} - saving and syncing data connectors is refused until it is fixed")
        for index, old in enumerate(credential_vault.previous_master_keys(), 1):
            old_problem = credential_vault.master_key_problem(old)
            if old_problem:
                add(ERROR, "CREDENTIAL_VAULT_PREVIOUS_KEYS", f"entry {index} {old_problem}")
        if credential_vault.previous_master_keys():
            add(WARNING, "CREDENTIAL_VAULT_PREVIOUS_KEYS", "is set - finish the rotation with `python -m scripts.vault_key rewrap`, then remove it")
    elif backend == "aws_kms":
        if not _env("AWS_KMS_KEY_ID"):
            add(ERROR, "AWS_KMS_KEY_ID", "is required when CREDENTIAL_VAULT_KMS_BACKEND=aws_kms")
    else:
        add(ERROR, "CREDENTIAL_VAULT_KMS_BACKEND", "must be 'local' or 'aws_kms'")

    # --- addresses and CORS ---------------------------------------------------------
    frontend = _env("FRONTEND_BASE_URL")
    app_base = _env("APP_BASE_URL")
    for name, value in (("FRONTEND_BASE_URL", frontend), ("APP_BASE_URL", app_base)):
        if not value:
            if is_deployed:
                add(ERROR, name, "is not set - links in emails and Stripe's return pages would point at localhost")
            continue
        problem = _url_problem(value, is_deployed)
        if problem:
            add(ERROR if is_deployed else WARNING, name, problem)
    if frontend and app_base and frontend != app_base:
        add(WARNING, "APP_BASE_URL", "differs from FRONTEND_BASE_URL - both should be the frontend's public address")
    origins = [o.strip() for o in (_env("CORS_ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    if not origins:
        if is_deployed:
            add(ERROR, "CORS_ALLOWED_ORIGINS", "is not set - the deployed frontend can't call the API")
    else:
        for origin in origins:
            problem = _origin_problem(origin, is_deployed)
            if problem:
                add(ERROR if is_deployed else WARNING, "CORS_ALLOWED_ORIGINS", f"entry {origin!r} {problem}")
        if frontend:
            front_origin = f"{urlparse(frontend).scheme}://{urlparse(frontend).netloc}"
            if front_origin not in origins:
                add(WARNING, "CORS_ALLOWED_ORIGINS", "doesn't include the FRONTEND_BASE_URL origin - "
                                                     "it must list the frontend's address, not the API's")

    # --- email ------------------------------------------------------------------------
    if _env("SMTP_HOST"):
        for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM_ADDRESS"):
            if not _env(name):
                add(WARNING, name, "is not set while SMTP_HOST is - most providers reject unauthenticated mail")
    elif is_deployed:
        add(WARNING, "SMTP_HOST", "is not set - sign-up codes, password resets and invitations are not emailed")
    if _env("EMAIL_LOG_UNSENT_BODIES").lower() in ("1", "true", "yes") and is_deployed:
        add(ERROR, "EMAIL_LOG_UNSENT_BODIES", "is on - real sign-in codes would be written to the server log")

    # --- file storage ------------------------------------------------------------------
    storage = [n for n in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD") if _env(n)]
    if storage and len(storage) < 3:
        for name in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
            if name not in storage:
                add(ERROR, name, "is not set while the other storage settings are - uploads will fail")
    elif not storage and is_deployed:
        add(WARNING, "MINIO_ENDPOINT", "file storage is not configured - uploads and stored images are unavailable")

    # --- integrations ------------------------------------------------------------------
    for first, second in PAIRS:
        if bool(_env(first)) != bool(_env(second)):
            missing = second if _env(first) else first
            add(WARNING, missing, f"must be set together with {first if missing == second else second}")
    if _env("STRIPE_SECRET_KEY").startswith("sk_live_") and not is_deployed:
        add(WARNING, "STRIPE_SECRET_KEY", "is a live key outside staging/production - use an sk_test_ key")
    for name in IGNORED_NAMES:
        if _env(name):
            add(WARNING, name, "is not read by KEEL (see KEYS_AND_ACCOUNTS_NEEDED.md for the right name) - remove it")
    if active_llm_provider() is None:
        add(WARNING, "GROQ_API_KEY", "no AI language model is configured - the assistant and AI analysis are unavailable")
    from src.market_scraper import web_search

    if not web_search.is_configured():
        add(WARNING, "TAVILY_API_KEY", "no web search provider is configured - the assistant cannot research public "
                                       "information (customs, taxes, prices) and discovery finds nothing; set "
                                       "TAVILY_API_KEY (free tier), BRAVE_SEARCH_API_KEY, SEARXNG_INSTANCE_URL or "
                                       "GOOGLE_CUSTOM_SEARCH_API_KEY + GOOGLE_CUSTOM_SEARCH_CX")
    return out


def check_billing(conn) -> List[Finding]:
    """Paid integrations that are configured but have no confirmed price:
    their calls are refused until one is recorded (never run unbilled)."""
    out: List[Finding] = []

    def priced(budget: str, provider: str, operation: str, units) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT unit, bool_or(unit_cost_usd IS NOT NULL) FROM provider_cost_schedules "
                "WHERE budget_kind = %s AND provider = %s AND operation IN (%s, '*') GROUP BY unit;",
                (budget, provider, operation),
            )
            have = {unit for unit, ok in cursor.fetchall() if ok}
        return all(u in have for u in units)

    llm = active_llm_provider()
    if llm and llm[0] != "local" and not priced("ai", llm[0], llm[1], ("input_token", "output_token")):
        out.append(Finding(WARNING, "provider_cost_schedules",
                           f"AI model {llm[1]!r} ({llm[0]}) has no confirmed input/output token price - every AI call is "
                           "refused until one is set with scripts.billing_admin set-price"))
    for label, (settings, budget, provider, operation, units) in PAID_INTEGRATIONS.items():
        if any(_env(s) for s in settings) and not priced(budget, provider, operation, units):
            out.append(Finding(WARNING, "provider_cost_schedules",
                               f"{label} is configured but has no confirmed price - its calls are refused until one is set"))
    with conn.cursor() as cursor:
        cursor.execute("SELECT kill_switch FROM provider_spend_controls WHERE provider = '*';")
        row = cursor.fetchone()
    if row and row[0]:
        out.append(Finding(WARNING, "provider_spend_controls", "the global kill switch is on - every paid provider is off"))
    return out


def log_findings(logger, findings: List[Finding]) -> None:
    for finding in findings:
        (logger.error if finding.level == ERROR else logger.warning)("configuration: %s", finding.line())
