#!/usr/bin/env bash
# Codespaces postStartCommand - runs on every Codespace start (first
# create AND every resume). Brings up the minimal infra subset via the
# repo's own backend/docker-compose.yml (reused unmodified - nothing in
# that file is changed by this script or by anything else in this PR),
# runs migrations, and rewrites the Codespaces-specific forwarded URLs
# into .env/frontend/.env. Idempotent: safe to re-run any time (e.g. after
# `docker compose down` or a manual restart).
#
# Deliberately starts ONLY postgres/redis/minio - not the 5 market_scraper
# background workers, not the Prometheus/Loki/Promtail/Grafana monitoring
# stack, not llm-local. Those stay available on request (see
# CODESPACES_DEVELOPMENT.md's "Optional services" section) but are not
# auto-started, per the "do not automatically start unnecessary heavy
# services" requirement.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root
source .devcontainer/env_utils.sh

echo "==> [1/5] Starting Postgres+pgvector, Redis, MinIO (docker compose)"
(cd backend && docker compose up -d postgres redis minio)

echo "==> [2/5] Running database migrations (Final_schema.sql + migrations/)"
# `migrate` is a one-shot job, not a long-running service - `docker
# compose run --rm` (not `up`) is the correct primitive for that: `run`
# always creates a brand-new, uniquely-named container and removes it on
# exit, so there is no existing `ceopro_migrate` container for it to ever
# reuse. This replaced a prior `docker compose up --force-recreate
# migrate` here, which was only a partial fix - it stopped THIS script
# from reusing a stale container, but `--force-recreate` lives on the
# command line, not in docker-compose.yml, so any *other* invocation of
# `docker compose up migrate` (a developer running it by hand, which is
# exactly what happened next) got no protection from it and could still
# reuse a leftover container whose bind mount was resolved against an
# earlier, no-longer-current workspace path - surfacing as "python: can't
# open file '/app/scripts/apply_migrations.py'" even though that file is
# right there in the current checkout. `run --rm` fixes this for every
# call site, including a manual `docker compose up -d migrate`, because
# there is nothing left for a manual `up` to find and reuse in the first
# place. scripts/apply_migrations.py itself is unchanged and still the
# one real migration runner; see docker-compose.yml's own comment on the
# `migrate` service for the same guidance if invoking it directly.
(cd backend && docker compose run --rm migrate)

echo "==> [3/5] Codespaces secrets"
# backend/.env (from .env.example) has empty lines such as GROQ_API_KEY= -
# loaded with `set -a && source .env` they would blank the Codespaces secret.
defer_empty_to_environment backend/.env

echo "==> [4/5] Recording the assistant model's price in this Codespace's database (if missing)"
# Every AI call is refused (COST_NOT_CONFIGURED) until the model has a
# confirmed price (docs/SUBSCRIPTIONS_AND_CREDITS.md section 4). This is the
# same operator step, on this Codespace's own local database only - never a
# remote one - and an already-recorded price is kept (--if-missing).
env_value() { grep -E "^$1=" backend/.env | tail -1 | cut -d= -f2-; }
MODEL="$(env_value GROQ_MODEL)"; MODEL="${MODEL:-openai/gpt-oss-20b}"
DB_URL="$(env_value DATABASE_URL)"
case "$DB_URL" in
  *@localhost:*|*@127.0.0.1:*) LOCAL_DB=1 ;;
  *) LOCAL_DB=0 ;;
esac
if [ "$LOCAL_DB" != 1 ]; then
  echo "    DATABASE_URL in backend/.env is not this Codespace's local database - not touching it."
elif [ "$MODEL" != "openai/gpt-oss-20b" ]; then
  echo "    GROQ_MODEL=$MODEL has no known price here. Record its real price before asking the assistant:"
  echo "    cd backend && python -m scripts.billing_admin set-price --budget ai --provider groq --operation $MODEL ..."
else
  # Groq's listed price for openai/gpt-oss-20b (console.groq.com/docs/models, checked 2026-10-17).
  for price in "input_token 0.075" "output_token 0.30"; do
    set -- $price
    (cd backend && DATABASE_URL="$DB_URL" .venv/bin/python -m scripts.billing_admin set-price --budget ai \
      --provider groq --operation "$MODEL" --unit "$1" --usd-per-million "$2" --if-missing \
      --source "Groq Supported Models page (console.groq.com/docs/models)" --verified-on 2026-10-17 \
      --by "Codespace setup" --reason "Groq list price, this Codespace's local database") \
      || echo "    WARNING: could not record the $1 price - see docs/SUBSCRIPTIONS_AND_CREDITS.md section 4."
  done
fi

echo "==> [5/5] Configuring Codespaces forwarded URLs"
if [ -n "${CODESPACE_NAME:-}" ]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  FRONTEND_URL="https://${CODESPACE_NAME}-5173.${DOMAIN}"
  BACKEND_URL="https://${CODESPACE_NAME}-8000.${DOMAIN}"

  # Sanity-check before writing: if CODESPACE_NAME/DOMAIN were ever empty,
  # truncated, or otherwise not what GitHub normally injects, the string
  # substitution above silently degrades to something that isn't a real
  # per-Codespace forwarded URL (e.g. just "https://github.dev") - and
  # nothing downstream (the frontend, CORS) errors on that, it just fails
  # to connect with no obvious link back to this script. Refuse to write a
  # URL that doesn't actually contain this Codespace's own name and the
  # expected port, instead of silently propagating a bad value.
  case "$FRONTEND_URL" in
    "https://${CODESPACE_NAME}-5173."*) ;;
    *)
      echo "ERROR: computed FRONTEND_URL ('$FRONTEND_URL') does not look like a" >&2
      echo "       real Codespaces forwarded URL for CODESPACE_NAME='$CODESPACE_NAME'." >&2
      echo "       GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN='${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-<unset, used default app.github.dev>}'" >&2
      echo "       Not touching backend/.env or frontend/.env. Re-run this script;" >&2
      echo "       if it fails again, the Codespace's env vars aren't populated yet." >&2
      exit 1
      ;;
  esac

  set_env_var backend/.env CORS_ALLOWED_ORIGINS "${FRONTEND_URL},http://localhost:5173,http://127.0.0.1:5173"
  set_env_var backend/.env FRONTEND_BASE_URL "$FRONTEND_URL"
  # Same-origin API: the browser calls <frontend>/api/..., which the Vite
  # dev server forwards to the backend on localhost:8000 (vite.config.js).
  # Only port 5173 has to be opened - it can stay private, and port 8000
  # never needs to be made public.
  set_env_var frontend/.env VITE_API_BASE_URL "/api"

  echo "    Codespace detected ($CODESPACE_NAME) - backend/.env and"
  echo "    frontend/.env now point at:"
  echo "      Frontend: $FRONTEND_URL"
  echo "      Backend:  $BACKEND_URL (reached through the frontend at /api)"
else
  echo "    \$CODESPACE_NAME not set - not running inside a Codespace"
  echo "    (e.g. a local devcontainer). Left backend/.env and"
  echo "    frontend/.env pointed at localhost - no rewrite needed."
fi

echo ""
echo "Infra is up. Next steps (see CODESPACES_DEVELOPMENT.md for detail):"
echo ""
echo "  Terminal 1 (backend):"
echo "    cd backend && source .venv/bin/activate"
echo "    set -a && source .env && set +a"
echo "    uvicorn src.ai.main:app --reload --host 0.0.0.0 --port 8000"
echo "    (the 'set -a && source .env' step loads JWT_SECRET/DATABASE_URL/etc"
echo "    into this shell - .env is a plain file on disk, nothing reads it"
echo "    automatically, so skipping this fails with 'JWT_SECRET environment"
echo "    variable is not set.' Matches docker-entrypoint.sh's own invocation"
echo "    otherwise - see there.)"
echo ""
echo "  Terminal 2 (frontend):"
echo "    cd frontend && npm run dev -- --host 0.0.0.0"
echo ""
echo "  Then open the forwarded 5173 port (Ports tab, or the URL printed"
echo "  above) in a browser and use KEEL as a real user. Or run ./keel start to start everything at once."
