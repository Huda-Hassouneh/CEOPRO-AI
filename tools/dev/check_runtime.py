"""Read-only compatibility check for an explicitly reused development virtualenv."""
import importlib.metadata as metadata
from pathlib import Path
import sys
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]

def requirements(path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            yield Requirement(line)

def main():
    if sys.prefix == sys.base_prefix or not (3, 11) <= sys.version_info[:2] <= (3, 12) or sys.maxsize <= 2**32:
        raise SystemExit("Reuse requires a 64-bit Python 3.11/3.12 virtual environment.")
    core = list(requirements(ROOT / "tools/dev/requirements.txt"))
    constraints = list(requirements(ROOT / "backend/src/ai/requirements.txt")) + list(requirements(ROOT / "backend/src/market_scraper/requirements.txt"))
    mandatory = core + (constraints if "--models" in sys.argv else [])
    failures = set()
    for req in mandatory:
        if req.marker and not req.marker.evaluate():
            continue
        try:
            version = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            failures.add(req.name + " (missing)")
            continue
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            failures.add(req.name + " (incompatible)")
    for req in constraints:
        if req.marker and not req.marker.evaluate():
            continue
        try:
            version = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            continue
        if req.specifier and not req.specifier.contains(version, prereleases=True):
            failures.add(req.name + " (outside repository constraints)")
    if failures:
        raise SystemExit("Existing Python is incompatible: " + ", ".join(sorted(failures)) + ". No packages were installed or changed.")
    print("Existing virtualenv is compatible; reuse is read-only.")

if __name__ == "__main__":
    main()
