"""
CEOPRO AI - CSV Source Adapter.
Converts a CSV file into the (headers, rows) shape ingestion_pipeline.process_file
expects. Uses Python's stdlib csv module - no external dependency, no cost.
"""
import csv
from typing import Dict, List, Tuple


def read_csv_file(file_path: str, encoding: str = "utf-8-sig") -> Tuple[List[str], List[Dict[str, object]]]:
    """
    utf-8-sig strips a leading byte-order mark if present. Regional POS
    exports and Excel-generated CSVs commonly include one, and it would
    otherwise attach to the first header, causing that column to fail
    every synonym match in template_detection.py.
    """
    with open(file_path, "r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return headers, rows
