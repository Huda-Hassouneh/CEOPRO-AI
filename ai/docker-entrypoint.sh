#!/bin/sh
# KEEL - ai service entrypoint.
#
# Single-container platforms (Render's free web service, in particular)
# have no separate init/migrate container the way docker-compose.yml's
# own dedicated `migrate` service does - this applies the schema/
# migrations here instead, right before starting the API. Safe to run on
# every boot: scripts/apply_migrations.py already tracks what's applied
# in its own schema_migrations table and skips anything already there,
# the same idempotent behavior docker-compose.yml's `migrate` service
# already relies on.
set -e

echo "Applying database schema and migrations..."
python scripts/apply_migrations.py

echo "Starting API server..."
# Render (and most single-container PaaS hosts) inject a real PORT env
# var and route/health-check exactly that port - a hardcoded 8000 here
# means the app is alive but Render's edge never finds it ("No open
# ports detected"). Falls back to 8000 when PORT isn't set (docker-
# compose.yml's own `ai` service, local runs) - unchanged behavior there.
exec uvicorn src.ai.main:app --host 0.0.0.0 --port "${PORT:-8000}"
