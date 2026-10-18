"""
KEEL - Application Knowledge Registry staleness check.

This is the "synchronization mechanism" for src/ai/knowledge/
application_registry.py: NOT automatic regeneration (a real route/
component static-analysis generator is real future work - see
RAG_BUSINESS_COPILOT_ARCHITECTURE.md), but a real, runnable check that
detects drift instead of silently trusting an old registry:

  1. Every ApplicationFeature.route (when set) must still exist as a
     value in frontend/src/app/router/routePaths.js.
  2. Every ApplicationFeature.frontend_source_file must still exist on
     disk.
  3. Every ApplicationFeature.backend_service module path must still
     import successfully (catches a renamed/deleted function or module,
     not just a renamed file).

Exits non-zero (and prints exactly which entries are stale and why) if
anything fails - meant to run in CI on every PR that touches
frontend/src/app/router/routePaths.js, frontend/src/features/**/pages/**,
or backend/src/ai/routers/**, and to be run manually after any route/
component change. Does not modify the registry itself - a human decides
how to fix a flagged entry (this deliberately does not auto-repair a
knowledge entry the same way this repo's own honesty requirements do not
allow it to auto-fabricate one).

Usage: python backend/scripts/validate_application_knowledge.py
       (run from the repo root or from backend/ - both resolve correctly)
"""

import importlib
import os
import re
import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_BACKEND_ROOT = _THIS_FILE.parent.parent  # backend/
_REPO_ROOT = _BACKEND_ROOT.parent

sys.path.insert(0, str(_BACKEND_ROOT))

# This script only ever imports backend_service modules to check they still
# exist - it never opens a real DB connection or issues a real token. Several
# modules (src.ai.core.security in particular) raise RuntimeError at IMPORT
# time if these env vars are unset, which would otherwise make every route
# whose backend_service touches auth/DB look "broken" here for a reason that
# has nothing to do with staleness. Only set when not already set, so a real
# environment's real values (if this happens to run alongside the app) are
# never overridden.
os.environ.setdefault("JWT_SECRET", "validate-application-knowledge-placeholder")
os.environ.setdefault("DATABASE_URL", "postgresql://placeholder:placeholder@localhost:5432/placeholder")
os.environ.setdefault("APP_DB_PASSWORD", "placeholder")

from src.ai.knowledge.application_registry import APPLICATION_FEATURES  # noqa: E402

ROUTE_PATHS_FILE = _REPO_ROOT / "frontend" / "src" / "app" / "router" / "routePaths.js"


def _load_real_route_values() -> set:
    """Parses routePaths.js's own `key: '/path'` lines - not a full JS
    parser, deliberately: this file is a flat object literal of string
    values, and a real JS parser is a heavier dependency than this one
    regex needs to earn."""
    if not ROUTE_PATHS_FILE.exists():
        raise FileNotFoundError(f"routePaths.js not found at {ROUTE_PATHS_FILE} - repo layout may have changed.")
    text = ROUTE_PATHS_FILE.read_text(encoding="utf-8")
    return set(re.findall(r":\s*'([^']+)'", text))


def validate() -> list:
    """Returns a list of human-readable problem strings - empty means clean."""
    problems = []
    real_routes = _load_real_route_values()

    for feature in APPLICATION_FEATURES:
        label = f"[{feature.feature_id}]"

        if feature.route is not None and feature.route not in real_routes:
            problems.append(
                f"{label} route {feature.route!r} not found in routePaths.js - "
                f"was it renamed or removed? (or is this entry correctly route=None "
                f"for a modal/non-routed action, in which case route should be None, not a string)"
            )

        if feature.frontend_source_file:
            fs_path = _REPO_ROOT / feature.frontend_source_file
            if not fs_path.exists():
                problems.append(f"{label} frontend_source_file {feature.frontend_source_file!r} does not exist on disk.")

        if feature.backend_service:
            module_path = feature.backend_service
            # backend_service may name a specific function
            # ("module.path.function_name") or just a module
            # ("module.path") - try the longest importable prefix.
            parts = module_path.split(".")
            imported = False
            last_error = None
            for cutoff in range(len(parts), 0, -1):
                candidate = ".".join(parts[:cutoff])
                try:
                    module = importlib.import_module(candidate)
                    remainder = parts[cutoff:]
                    obj = module
                    for attr in remainder:
                        obj = getattr(obj, attr)
                    imported = True
                    break
                except (ImportError, AttributeError) as exc:
                    last_error = exc
                    continue
            if not imported:
                problems.append(f"{label} backend_service {module_path!r} could not be imported/resolved: {last_error}")

    return problems


def main() -> int:
    problems = validate()
    if not problems:
        print(f"Application Knowledge Registry OK - all {len(APPLICATION_FEATURES)} entries verified against the current repository.")
        return 0

    print(f"Application Knowledge Registry is STALE - {len(problems)} problem(s) found:\n")
    for problem in problems:
        print(f"  - {problem}")
    print(
        "\nFix src/ai/knowledge/application_registry.py (update the affected "
        "entry/entries), then re-run this script. Do not ignore this in CI - "
        "a stale entry means the AI Business Copilot will describe a UI flow "
        "that no longer exists."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
