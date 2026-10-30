"""Reuse the established CSV-to-Dashboard fixture against the persistent test DB."""
from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.data_import_browser_verification import _seed


def main() -> None:
    state = Path(os.environ["KEEL_VERIFICATION_STATE"])
    fixture = _seed(os.environ["DATABASE_URL"], os.environ["JWT_SECRET"])
    path = state / "import-browser-fixture.json"
    path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(f"Synthetic CSV/Dashboard fixture stored outside Git at {path}.")


if __name__ == "__main__":
    main()
