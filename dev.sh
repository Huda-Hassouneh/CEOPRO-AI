#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.dev/venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="${KEEL_PYTHON:-python3}"; fi
exec "$PYTHON" "$ROOT/tools/dev/dev.py" "$@"
