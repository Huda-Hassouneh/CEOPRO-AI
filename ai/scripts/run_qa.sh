#!/usr/bin/env bash
# One-command QA run for the backend (see QA_TEST_STRATEGY.md / QA_TEST_REPORT.md).
#
#   ./scripts/run_qa.sh            offline tests only (no services needed, ~1 min)
#   ./scripts/run_qa.sh security   only the P0 security/auth contract tests (seconds)
#   ./scripts/run_qa.sh full       offline + live-DB integration tests. Uses the
#                                  Postgres/Redis already pointed to by DATABASE_URL /
#                                  REDIS_HOST, or starts them with docker compose.
#
# Extra pytest args can be appended:  ./scripts/run_qa.sh unit -k pricing
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:-unit}"
[ $# -gt 0 ] && shift || true

PY="${PYTHON:-python3}"
"$PY" -c "import pytest, fastapi, jwt" 2>/dev/null || {
  echo "Missing Python deps. Run: $PY -m pip install -r src/ai/requirements.txt pytest pytest-timeout" >&2; exit 2; }

# macOS: xgboost needs the OpenMP runtime.
if [ "$(uname)" = "Darwin" ] && ! "$PY" -c "import xgboost" 2>/dev/null; then
  echo "xgboost can't load. On macOS run: brew install libomp" >&2; exit 2
fi

# Only a unit-test default; never overrides a value the caller already set.
export JWT_SECRET="${JWT_SECRET:-qa-run-jwt-secret}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export KMP_DUPLICATE_LIB_OK="${KMP_DUPLICATE_LIB_OK:-TRUE}"   # torch + xgboost both ship OpenMP
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

TIMEOUT_ARGS=()
"$PY" -c "import pytest_timeout" 2>/dev/null && TIMEOUT_ARGS=(--timeout=120 --timeout-method=thread)

case "$mode" in
  security)
    exec "$PY" -m pytest src/ai/tests/test_api_security_contract.py src/infrastructure/tests -q -p no:cacheprovider "${TIMEOUT_ARGS[@]}" "$@" ;;
  unit)
    exec "$PY" -m pytest src -q -p no:cacheprovider "${TIMEOUT_ARGS[@]}" "$@" ;;
  full)
    if [ -z "${DATABASE_URL:-}" ]; then
      command -v docker >/dev/null || { echo "full mode needs DATABASE_URL (a running Postgres+pgvector) or docker." >&2; exit 2; }
      [ -f .env ] || cp .env.example .env
      set -a; . ./.env; set +a
      docker compose up -d postgres redis minio
      docker compose run --rm migrate
      export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB}"
      export REDIS_HOST=localhost REDIS_PORT=6379
      export AI_TEST_MINIO_ENDPOINT="localhost:9000" AI_TEST_MINIO_ROOT_USER="${MINIO_ROOT_USER:-}" AI_TEST_MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-}"
    else
      "$PY" scripts/apply_migrations.py
    fi
    export AI_TEST_DATABASE_URL="${AI_TEST_DATABASE_URL:-$DATABASE_URL}"
    export SCRAPER_DATABASE_URL="${SCRAPER_DATABASE_URL:-$DATABASE_URL}"
    export PGCLIENTENCODING=UTF8
    : "${APP_DB_PASSWORD:?set APP_DB_PASSWORD (the password the migrations give the ceopro_app role)}"
    exec "$PY" -m pytest src -q -p no:cacheprovider "${TIMEOUT_ARGS[@]}" "$@" ;;
  *) echo "usage: $0 [unit|security|full] [pytest args]" >&2; exit 2 ;;
esac
