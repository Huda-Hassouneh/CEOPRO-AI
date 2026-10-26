# Environment configuration

## Two workflows

The root developer command generates required local configuration in private `.dev/config.json` and derives application environment variables at launch. It **never reads or changes** root/backend/frontend `.env` files. Existing `backend/.env.example` remains untouched for manual/deployment users.

Optional integration settings are literal `NAME=value` lines in `.dev/integrations.env`, based on [the example](../tools/dev/integrations.env.example). Empty values leave features unconfigured. Values are not evaluated as shell code. Restart affected processes after edits. Never put secrets in `VITE_*` variables; those become public browser code.

## Managed local settings

All rows below require a restart after changes. Setup supplies them; missing/invalid values cause startup or readiness failure. Do not override them in integrations.env.

| Variable | Owner / purpose | Development value / format | Missing consequence |
|---|---|---|---|
| DATABASE_URL | Migration connection or restricted runtime endpoint | Generated loopback PostgreSQL URL for keel_dev_<id>; admin only in migration commands | DB operations fail |
| APP_DB_PASSWORD | API/worker restricted password | Generated unique secret | Restricted login fails |
| SCRAPER_DATABASE_URL | Market/commerce worker DB | Same local DB, ceopro_app | Worker cannot operate |
| JWT_SECRET | Python session signatures | Generated 32-byte secret, retained | Authentication fails |
| CREDENTIAL_VAULT_MASTER_KEY | Connector credential encryption | Generated Fernet key, retained | Stored credentials cannot be opened; never rotate casually |
| REDIS_URL | Shared Redis client/streams | redis://127.0.0.1:<port>/0, dedicated instance | Queues/cache/rate limits fail |
| REDIS_HOST / REDIS_PORT | Consumers supporting split form | 127.0.0.1 / generated port | Older split readers fail |
| MINIO_ENDPOINT | Storage API | 127.0.0.1:<port>, no scheme | Upload/storage operations fail |
| MINIO_ROOT_USER / MINIO_ROOT_PASSWORD | Local object storage access | keeldev / generated secret | Storage authentication fails |
| SMTP_HOST / SMTP_PORT / SMTP_USE_TLS | Real local OTP delivery | 127.0.0.1 / generated SMTP port / false | Signup mail unavailable |
| EMAIL_FROM_ADDRESS | Transactional email sender | local@keel.example | Uses application default |
| EMAIL_LOG_UNSENT_BODIES | Sensitive email-body logging | false | No OTP secrets printed in logs |
| FRONTEND_BASE_URL | Links and payment return origin | http://127.0.0.1:<frontend-port> | Links may target wrong frontend |
| CORS_ALLOWED_ORIGINS | FastAPI browser origins | Exact frontend origin | Cross-origin requests denied |
| VITE_API_BASE_URL | Public frontend transport | /api | Browser reaches wrong/no API |
| KEEL_DEV_ISOLATED | Vite configuration-file isolation | 1 under launcher; disables legacy dotenv loading | Without it, manual Vite retains normal dotenv behavior |
| KEEL_API_PROXY_TARGET | Vite server-side proxy | http://127.0.0.1:<api-port> | Proxy fails |
| AI_SERVICE_ACTOR_USER_ID / SCRAPER_ACTOR_USER_ID | Existing restricted service principal | Existing zero-UUID system actor | Worker authorization fails |
| SCRAPER_METRICS_PORT / SCRAPER_MAINTENANCE_METRICS_PORT | Worker metrics | Per-checkout free ports | Metric bind conflict |
| SENTRY_ENVIRONMENT | Runtime environment classification | development | Existing app defaults apply |
| API_DOCS_ENABLED | FastAPI docs/OpenAPI | true locally | Docs may be unavailable |
| PYTHONUNBUFFERED / PYTHONIOENCODING | Process logging | 1 / utf-8 | Delayed or damaged diagnostics |

The generated Compose configuration supplies POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB and MinIO container credentials only to owned infrastructure. There is no configurable remote DB URL in this workflow. Runtime processes receive ceopro_app, not the migration password.

## Optional feature settings

All require process restart unless the source reference states otherwise. Missing credentials keep the associated integration unavailable; they do not authorize fake success.

| Variables | Owner / purpose | Example format/default | Feature / consequence |
|---|---|---|---|
| STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET | Billing TEST account / exact listener signing | sk_test_<private> / whsec_<private>; unset | Checkout unavailable; both required together; LIVE refused |
| GROQ_API_KEY / GROQ_MODEL | Hosted assistant | private key / existing model default | No configured Groq inference; verified costs still required |
| HUGGINGFACE_API_TOKEN / HUGGINGFACE_LLM_MODEL | Hosted AI | private token / model identifier; unset | Hosted capability unavailable |
| LOCAL_LLM_BASE_URL | Existing local inference service | http://127.0.0.1:<port>/v1; unset | No local LLM |
| RAG_EMBEDDING_BACKEND | Existing semantic encoder | torch default; setup --models installs libraries | Missing libraries/weights prevent semantic model loading; no substitute added |
| SENTIMENT_MODEL | Existing classifier weights | cardiffnlp/twitter-xlm-roberta-base-sentiment | Default model; first-use download may require network |
| TAVILY_API_KEY / BRAVE_SEARCH_API_KEY / SERPAPI_API_KEY | External market search | private credentials; unset | Respective search providers unavailable |
| GOOGLE_CUSTOM_SEARCH_API_KEY / GOOGLE_CUSTOM_SEARCH_CX | Google CSE | private key / engine ID; unset | CSE unavailable |
| APIFY_API_TOKEN | Provider collection | private token; unset | Apify unavailable |
| SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET | OAuth and authenticated webhook integration | App ID / private secret; unset | Shopify connection/webhook configuration unavailable |
| SEARXNG_INSTANCE_URL | Optional self-hosted discovery | http://127.0.0.1:<port>; unset | No local SearXNG fallback |
| SENTRY_DSN | Optional error monitoring | Private project DSN; unset | Monitoring disabled |
| VITE_SPLINE_HERO_SCENE / VITE_SENTRY_DSN / VITE_SUPPORT_EMAIL | Public frontend presentation/monitoring | Empty by default | Static hero/no browser reporting/no optional contact override |

WooCommerce store credentials are per-source vaulted business configuration, not global example rates or shared environment secrets.

## Full source inventory

[Generated environment inventory](reference/ENVIRONMENT_INVENTORY.md) lists statically referenced settings with their owning module, default/required expression and exact source locations. It includes worker scheduling, ingestion, storage, provider, quota and test flags beyond everyday setup. Read the linked implementation before changing advanced controls.

Regenerate with `python tools/dev/environment_inventory.py`; check freshness with `--check`. Dynamic provider/catalog settings are identified separately; they cannot be inferred safely as one universal credential.

Every advanced setting is tied to its source module; absence uses its recorded default or follows that module's validation branch. Runtime flags do not override approved financial/privacy/automation policy. In particular KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION is never enabled by the local launcher.
