#!/usr/bin/env bash
# Codespaces postCreateCommand - runs ONCE, when the Codespace container is
# first created. Installs dependencies and creates real .env files from the
# repo's own backend/.env.example / frontend/.env.example templates - the
# exact same templates a non-Codespaces local dev setup already uses, not a
# separate Codespaces-only config format. Does not start any service (that
# is start-services.sh, run on every start via postStartCommand) and never
# touches Render/Neon/production - this only ever writes files inside the
# Codespace's own throwaway filesystem.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root
source .devcontainer/env_utils.sh

echo "==> [1/5] Creating backend/.env from backend/.env.example (if missing)"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
fi

# Host-based dev: the `ai` FastAPI service runs directly on the Codespace
# host (via uvicorn --reload, for fast iteration - see
# CODESPACES_DEVELOPMENT.md for why this beats rebuilding Dockerfile.ai's
# image per code change), not as a docker-compose container. It therefore
# reaches Postgres/Redis/MinIO via the ports docker-compose.yml already
# publishes to the host (5432/6379/9000-9001), i.e. `localhost`, not the
# `postgres`/`redis` service-name DNS that only resolves *inside* the
# compose network. Redis/MinIO already default to localhost in
# .env.example; only Postgres needs overriding here.
set_env_var backend/.env POSTGRES_HOST "localhost"
set_env_var backend/.env DATABASE_URL "postgresql://ceopro_admin:change_this_password@localhost:5432/ceopro_platform"
set_env_var backend/.env SCRAPER_DATABASE_URL "postgresql://ceopro_app:change_this_password@localhost:5432/ceopro_platform"

# JWT_SECRET is empty in .env.example on purpose ("the application must
# fail to start if this is not set") - a real per-Codespace random secret
# is generated once here rather than shipping one hardcoded value every
# Codespace/contributor would otherwise share.
if ! grep -q "^JWT_SECRET=.\+" backend/.env 2>/dev/null; then
  JWT_SECRET_VALUE=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  set_env_var backend/.env JWT_SECRET "$JWT_SECRET_VALUE"
fi

# CORS_ALLOWED_ORIGINS/FRONTEND_BASE_URL/VITE_API_BASE_URL are intentionally
# left at their .env.example localhost defaults here - they get rewritten
# to the real Codespaces forwarded URLs by start-services.sh on every
# start, since the forwarded URL is only known once port forwarding is
# actually live (and differs on a fresh Codespace vs. a rebuilt one).

echo "==> [2/5] Creating frontend/.env from frontend/.env.example (if missing)"
if [ ! -f frontend/.env ]; then
  cp frontend/.env.example frontend/.env
fi

echo "==> [3/5] Installing backend Python dependencies (backend/.venv)"
# A real venv, not --user/system-wide - keeps this isolated and matches
# Dockerfile.ai's own pip install (same requirements.txt, same versions).
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip --quiet
# On Linux, PyPI's default torch wheel bundles ~3.4 GB of NVIDIA CUDA
# libraries this service never uses (every model runs on CPU). Installing
# the CPU build first keeps the venv ~4 GB smaller; requirements.txt's
# torch>=2.0,<3.0 is then already satisfied. macOS/Windows wheels are
# CPU-only already.
if [ "$(uname -s)" = "Linux" ]; then
  backend/.venv/bin/pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.0,<3.0" \
    || echo "    (download.pytorch.org unreachable - falling back to the default PyPI torch wheel)"
fi
backend/.venv/bin/pip install --no-cache-dir -r backend/src/ai/requirements.txt

echo "==> [4/5] Installing frontend dependencies"
npm --prefix frontend install

echo "==> [5/5] Setup complete."
echo ""
echo "GROQ_API_KEY is NOT set yet - required for the RAG Assistant chat"
echo "endpoint (/rag/query) to work. Get a free key at"
echo "https://console.groq.com/ and add it to backend/.env yourself -"
echo "this is a real secret, so it is deliberately never auto-generated."
echo ""
echo "Next: the Codespace will now run start-services.sh automatically"
echo "(postStartCommand) to bring up Postgres/pgvector/Redis/MinIO and run"
echo "migrations. See CODESPACES_DEVELOPMENT.md for how to start the"
echo "backend and frontend after that."
