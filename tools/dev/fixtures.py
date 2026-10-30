"""Small optional import files from the existing committed synthetic fixture."""
import csv
from itertools import islice
from pathlib import Path


def generate(root: Path, destination: Path) -> tuple[Path, bool]:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "sales-synthetic.csv"
    if target.exists():
        return target, False  # Developer-edited fixtures are never overwritten.
    source = root / "backend/mocks/e2e_pipeline_demo.csv"
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(islice(reader, 20))
        fields = reader.fieldnames
    with target.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (destination / "README.txt").write_text(
        "SYNTHETIC DEVELOPMENT IMPORT ONLY. First 20 rows of the committed e2e_pipeline_demo.csv.\n"
        "No account, plan, credit, quote or provider cost is created.\n"
        "Use a disposable workspace and the ordinary upload/preview/review flow.\n"
        "Create/review matching product identities as required; conflicts must remain held.\n",
        encoding="utf-8")
    return target, True
