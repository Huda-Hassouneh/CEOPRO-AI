"""
CEOPRO AI - Regenerates the distributed import template files
(templates/ceopro_sales_transaction_import_v1.csv/.xlsx) directly from
src/ai/extraction/template_contract.py, the single source of truth for
the template's fields/order/example values. Run this after any change to
TEMPLATE_FIELDS so the committed template files never drift from what the
code actually validates against.

Usage: python scripts/generate_import_templates.py
"""
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from openpyxl import Workbook  # noqa: E402

from src.ai.extraction.template_contract import (  # noqa: E402
    CURRENT_TEMPLATE_VERSION, EXAMPLE_ROW, TEMPLATE_HEADER_ROW, TEMPLATE_ID,
)

TEMPLATES_DIR = REPO_ROOT / "templates"


def _write_csv(path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(TEMPLATE_HEADER_ROW)
        writer.writerow([EXAMPLE_ROW[field] for field in TEMPLATE_HEADER_ROW])


def _write_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(TEMPLATE_HEADER_ROW)
    sheet.append([EXAMPLE_ROW[field] for field in TEMPLATE_HEADER_ROW])
    # "Data" stays the active/first sheet deliberately - xlsx_adapter.py
    # reads workbook.active by default when no sheet_name is passed, so a
    # user who doesn't rename/reorder sheets still gets parsed correctly.
    workbook.save(path)


def main() -> None:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    csv_path = TEMPLATES_DIR / f"{TEMPLATE_ID}_v1.csv"
    xlsx_path = TEMPLATES_DIR / f"{TEMPLATE_ID}_v1.xlsx"
    _write_csv(csv_path)
    _write_xlsx(xlsx_path)
    print(f"Generated (template version {CURRENT_TEMPLATE_VERSION}):")
    print(f"  {csv_path}")
    print(f"  {xlsx_path}")


if __name__ == "__main__":
    main()
