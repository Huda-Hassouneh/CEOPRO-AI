#!/usr/bin/env bash
# Run the live-DB (*_integration_db.py) suites against a throwaway Postgres + Redis (PENDING_ACTIONS #87).
#
# Usage, from backend/:
#   scripts/run_live_db_suites.sh                 # competitor / enrichment suites (default)
#   scripts/run_live_db_suites.sh all             # every *_integration_db.py file
#   scripts/run_live_db_suites.sh <pytest args>   # e.g. -k pricing src/ai/tests/test_pricing_integration_db.py
#
# Starts pgvector/pgvector:pg15 and redis:7-alpine on Docker-assigned free local ports (loopback only), applies every migration with
# scripts/apply_migrations.py, runs pytest, then removes both containers. Needs Docker and the packages in
# src/ai/requirements.txt in the active Python (set PYTHON=/path/to/python to override). Touches no other container.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
SUFFIX="$$"
PG="live_db_pg_$SUFFIX"
RD="live_db_redis_$SUFFIX"

command -v docker >/dev/null || { echo "docker is required" >&2; exit 2; }
PYTHONPATH=. "$PYTHON" -c "import pytest, psycopg2, redis; import src.ai.db" 2>"${TMPDIR:-/tmp}/live_db_import.err" \
  || { cat "${TMPDIR:-/tmp}/live_db_import.err" >&2; echo "$PYTHON cannot import the test dependencies: install src/ai/requirements.txt or set PYTHON" >&2; exit 2; }

cleanup() { docker rm -f "$PG" "$RD" >/dev/null 2>&1 || true; }
trap cleanup EXIT

ADMIN_PW=ci_test_admin_password
docker run -d --name "$PG" -e POSTGRES_USER=ceopro_admin -e POSTGRES_PASSWORD="$ADMIN_PW" \
  -e POSTGRES_DB=ceopro_platform -p 127.0.0.1::5432 pgvector/pgvector:pg15 >/dev/null
docker run -d --name "$RD" -p 127.0.0.1::6379 redis:7-alpine >/dev/null

echo "Waiting for Postgres..."
for _ in $(seq 1 60); do
  # The image restarts once after its init scripts, so require two consecutive successes.
  if docker exec "$PG" pg_isready -U ceopro_admin -d ceopro_platform >/dev/null 2>&1; then
    sleep 2
    docker exec "$PG" pg_isready -U ceopro_admin -d ceopro_platform >/dev/null 2>&1 && break
  fi
  sleep 1
done
docker exec "$PG" pg_isready -U ceopro_admin -d ceopro_platform >/dev/null \
  || { echo "Postgres did not become ready" >&2; exit 3; }

PG_PORT="$(docker port "$PG" 5432/tcp | head -1 | sed 's/.*://')"
REDIS_PORT="$(docker port "$RD" 6379/tcp | head -1 | sed 's/.*://')"
URL="postgresql://ceopro_admin:$ADMIN_PW@127.0.0.1:$PG_PORT/ceopro_platform"
export DATABASE_URL="$URL" AI_TEST_DATABASE_URL="$URL" SCRAPER_DATABASE_URL="$URL"
export APP_DB_PASSWORD=ci_test_app_password REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0" PYTHONPATH=.

"$PYTHON" scripts/apply_migrations.py

if [ "$#" -eq 0 ]; then
  set -- src/market_scraper/tests/test_competitor_enrichment_integration_db.py \
         src/market_scraper/tests/test_manual_competitor_integration_db.py \
         src/ai/tests/test_competitor_*_integration_db.py \
         src/ai/tests/test_apex_competitor_landscape_integration_db.py \
         src/ai/tests/test_dashboard_competitor*_integration_db.py \
         src/ai/tests/test_pricing_competitor_classification_integration_db.py
elif [ "$1" = "all" ]; then
  shift
  set -- $(find src -name '*_integration_db.py' | sort) "$@"
fi

"$PYTHON" -m pytest -q --no-header "$@"
