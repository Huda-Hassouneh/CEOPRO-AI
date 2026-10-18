"""
KEEL - OpenAPI Schema Extractor.

.github/workflows/staging-deployment.yml already referenced this exact path
(python src/infrastructure/openapi_extractor.py) before this file existed, so
that CI step failed on every run - the same "referenced before it existed"
gap PENDING_ACTIONS.md #8 flagged.

Importing src.ai.main:app never touches a live database (src/ai/db.py's
connection pool is created lazily on first real request, not at import
time), so this only needs JWT_SECRET set (core/security.py reads it at
import time) - not a real DATABASE_URL. The workflow already sets both as
CI-only placeholder secrets; DATABASE_URL is accepted but never actually
connected to here.

Writes the real, current FastAPI-generated OpenAPI 3.x schema (every route
this app actually serves, not a hand-maintained copy that can drift) to
openapi.json at the repo root - the real API contract a frontend team, an
API-gateway config, or a Swagger/Redoc viewer can consume without needing a
running server.

Usage: JWT_SECRET=<any value> python src/infrastructure/openapi_extractor.py [output_path]
"""
import json
import sys
from pathlib import Path

DEFAULT_OUTPUT_PATH = "openapi.json"


def extract_openapi_schema(output_path: str = DEFAULT_OUTPUT_PATH) -> dict:
    from src.ai.main import app

    schema = app.openapi()
    Path(output_path).write_text(json.dumps(schema, indent=2, sort_keys=True))
    return schema


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTPUT_PATH
    schema = extract_openapi_schema(path)
    print(f"Wrote OpenAPI schema ({len(schema.get('paths', {}))} paths) to {path}")
