"""
KEEL - CSV Source Adapter.
Converts a CSV file into the (headers, rows) shape ingestion_pipeline.process_file
expects. Uses Python's stdlib csv module plus charset-normalizer (already a
requests dependency) for legacy-encoding detection.
"""
import csv
import io
from typing import Dict, List, Optional, Tuple

import charset_normalizer

# Legacy encodings real business exports actually arrive in when they are
# not UTF-8: Excel/older POS systems save CSV in the Windows code page of
# the machine's locale - Windows-1256 for Arabic, Windows-1252 for Western
# European languages - and some tools write UTF-16. Detection is restricted
# to these on purpose: unrestricted detection on a short file confidently
# picks a wrong neighbouring code page (e.g. cp1250, turning "crème" into
# "crčme"), and silently corrupted product names are worse than an honest
# "please re-save as UTF-8" error.
LEGACY_ENCODING_CANDIDATES = ["cp1256", "cp1252", "utf_16"]

# Excel in many locales (French, German, Arabic, ...) uses ';' as the CSV
# list separator because ',' is the decimal separator there; tab- and
# pipe-separated exports are common from POS/ERP systems.
CANDIDATE_DELIMITERS = ",;\t|"


def _decode(raw: bytes, encoding: Optional[str]) -> str:
    if encoding:
        return raw.decode(encoding)
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        best = charset_normalizer.from_bytes(raw, cp_isolation=LEGACY_ENCODING_CANDIDATES).best()
        if best is None:
            raise
        return str(best)


def _detect_delimiter(text: str) -> str:
    first_line = text.splitlines()[0] if text else ""
    try:
        dialect = csv.Sniffer().sniff(text[:64 * 1024], delimiters=CANDIDATE_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    # The sniffer can be fooled by data rows; only trust it when it splits
    # the header into more columns than a plain comma would.
    if delimiter != "," and first_line.count(delimiter) <= first_line.count(","):
        return ","
    return delimiter


def read_csv_file(file_path: str, encoding: Optional[str] = None) -> Tuple[List[str], List[Dict[str, object]]]:
    """
    UTF-8 (with or without the byte-order mark Excel adds - left in place
    it would attach to the first header and fail every synonym match in
    template_detection.py) is tried first; a file that is not valid UTF-8
    falls back to the legacy encodings above. A file that matches none of
    them still raises UnicodeDecodeError, which the upload endpoint reports
    as a clear 400.
    """
    with open(file_path, "rb") as f:
        text = _decode(f.read(), encoding)
    if text.startswith("﻿"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=_detect_delimiter(text))
    headers = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    return headers, rows
