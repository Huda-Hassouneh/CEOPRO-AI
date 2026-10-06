"""
CEOPRO AI - Extraction. Runs the unmodified CEOPRO-AI extraction code:
  - file:  src/ai/extraction/file_dispatch.read_source_file() + ingestion_pipeline.process_records()
           (template detection, header mapping, typed row parsing, validation, regex/NER fallback)
  - text:  src/ai/extraction/extractor.extract_entities() (regex tier + optional catalog tier)
"""
import base64
import binascii
import csv
import dataclasses
import json
import os
import tempfile
import zipfile
from itertools import islice

import gradio as gr
import pdfplumber
from openpyxl import load_workbook

from memdb import MemConn
from src.ai.extraction import extractor, file_dispatch, ingestion_pipeline
from src.ai.extraction.adapters import pdf_adapter

TENANT_ID = "public-demo-tenant"
JOB_ID = "public-demo-job"
# Largest file this public service accepts (decoded size). Chosen from live
# measurements on this Space (see deploy/huggingface_spaces/UPLOAD_LIMITS.md):
# the request path carries 700 MB+ bodies, and since only the first MAX_ROWS
# data rows are processed, files are read in a bounded way (_read_bounded) -
# memory and time no longer grow with the file, only the upload itself does.
MAX_UPLOAD_MB = int(os.getenv("EXTRACTION_MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_ROWS = 1000
# A PDF page yields at least one row when it has any text, so reading more
# than MAX_ROWS + 1 pages can never be needed; this also bounds the time
# spent on long image-only PDFs (measured ~0.14 s per page).
MAX_PDF_PAGES = MAX_ROWS + 1
# .xlsx/.xlsm are zip archives: a small upload can expand to gigabytes. The
# shared-strings part is held in memory whole, so it gets its own cap
# (a 1,048,576-row Excel sheet of unique text measured 163 MB).
MAX_XLSX_UNPACKED_MB = 2048
MAX_XLSX_SHARED_STRINGS_MB = 256
_DECODE_CHUNK = 4 * 1024 * 1024  # base64 characters per decode step (multiple of 4)
HERE = os.path.dirname(__file__)
EXAMPLE_IMPORT = open(os.path.join(HERE, "example_import.csv"), encoding="utf-8").read()
EXAMPLE_TEXT = ("Invoice INV-20458 for order ORD-99231: 3 x Premium Olive Oil 1L at 24.50 JOD each, 10% discount, "
                "total 66.15 JOD, paid 30/08/2026. Contact customer@example.com or +962791234567. Cheaper at Rival Store.")


class _CacheMiss:
    """Redis stand-in that always misses, so catalog_cache.get_known_names() falls through to the (in-memory) DB loaders."""
    def get(self, key):
        return None

    def set(self, *a, **k):
        return True

    def delete(self, *a, **k):
        return 0


def _company_route(country_code, currency):
    return (r"FROM companies", lambda q, p: [(country_code, [currency] if currency else None, None)] if country_code else [])


def _read_bounded(path, ext):
    """The same parsing as file_dispatch.read_source_file()'s CSV/XLSX/PDF
    adapters, but it stops once MAX_ROWS + 1 data rows are known instead of
    loading the whole file - only the first MAX_ROWS rows are processed per
    request, so a 500 MB export costs no more memory than a 1 MB one."""
    if ext == ".csv":  # adapters/csv_adapter.read_csv_file, bounded
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            rows = [dict(row) for row in islice(reader, MAX_ROWS + 1)]
        return headers, rows, len(rows) > MAX_ROWS
    if ext in (".xlsx", ".xlsm"):  # adapters/xlsx_adapter.read_xlsx_file, bounded (streaming read-only mode)
        _check_xlsx_unpacked_size(path)
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows_iter = sheet.iter_rows(values_only=True)
            header_row = next(rows_iter, None)
            if header_row is None:
                return [], [], False
            headers = [str(h).strip() if h is not None else "" for h in header_row]
            rows = []
            for raw_row in rows_iter:
                if all(cell is None for cell in raw_row):
                    continue
                rows.append({headers[i]: raw_row[i] for i in range(len(headers)) if i < len(raw_row)})
                if len(rows) > MAX_ROWS:
                    break
        finally:
            workbook.close()
        return headers, rows, len(rows) > MAX_ROWS
    # .pdf: adapters/pdf_adapter.read_pdf_file, page by page, stopping once enough rows are found
    canonical_headers, structured_rows, fallback_rows = None, [], []
    with pdfplumber.open(path) as pdf:
        pages_left = len(pdf.pages) > MAX_PDF_PAGES
        for page in pdf.pages[:MAX_PDF_PAGES]:
            canonical_headers, page_rows = pdf_adapter._process_page_tables(page, canonical_headers)
            if page_rows:
                structured_rows.extend(page_rows)
            else:
                text = page.extract_text() or ""
                if text.strip():
                    fallback_rows.append({pdf_adapter.PAGE_TEXT_HEADER: text})
            page.close()  # release this page's parsed objects
            if len(structured_rows) > MAX_ROWS or (not structured_rows and len(fallback_rows) > MAX_ROWS):
                break
    if structured_rows:
        return canonical_headers, structured_rows, pages_left or len(structured_rows) > MAX_ROWS
    return [pdf_adapter.PAGE_TEXT_HEADER], fallback_rows, pages_left or len(fallback_rows) > MAX_ROWS


def _check_xlsx_unpacked_size(path):
    try:
        members = zipfile.ZipFile(path).infolist()
    except zipfile.BadZipFile:
        raise gr.Error("This .xlsx/.xlsm file is not a valid Excel workbook.")
    total = sum(m.file_size for m in members)
    shared = sum(m.file_size for m in members if m.filename.lower().endswith("sharedstrings.xml"))
    if total > MAX_XLSX_UNPACKED_MB * 1048576 or shared > MAX_XLSX_SHARED_STRINGS_MB * 1048576:
        raise gr.Error(f"This workbook unpacks to {total / 1048576:.0f} MB ({shared / 1048576:.0f} MB of text); the maximum is "
                       f"{MAX_XLSX_UNPACKED_MB} MB ({MAX_XLSX_SHARED_STRINGS_MB} MB of text). Save the sheet as CSV and upload that instead.")


def _run_file(path, source_name, country_code, currency):
    headers, rows, truncated = _read_bounded(path, os.path.splitext(path)[1].lower())
    rows = rows[:MAX_ROWS]
    conn = MemConn([_company_route(country_code, currency)])
    summary = ingestion_pipeline.process_records(tenant_id=TENANT_ID, job_id=JOB_ID, source_name=source_name,
                                                 headers=headers, rows=rows, conn=conn)
    out = dataclasses.asdict(summary) if dataclasses.is_dataclass(summary) else dict(vars(summary))
    return json.loads(json.dumps(out, default=str)), headers, len(rows), truncated, conn.persisted


def _too_large(size_bytes: int) -> gr.Error:
    return gr.Error(f"File is {size_bytes / 1048576:.1f} MB; the maximum is {MAX_UPLOAD_MB} MB ({MAX_UPLOAD_BYTES} bytes).")


def _check_type(file_name):
    try:
        return file_dispatch.detect_file_type(file_name or "")
    except file_dispatch.UnsupportedFileTypeError as exc:
        raise gr.Error(str(exc))


def _decode_to_temp(file_base64: str, ext: str) -> str:
    """Rejects an oversized file from its base64 length alone (before
    decoding anything), then decodes in fixed-size steps straight to a temp
    file, so a large upload never needs a second full copy in memory."""
    encoded = file_base64 or ""
    padding = len(encoded) - len(encoded.rstrip("="))
    decoded_size = len(encoded) // 4 * 3 - padding
    if decoded_size > MAX_UPLOAD_BYTES:
        raise _too_large(decoded_size)
    if not encoded or len(encoded) % 4:
        raise gr.Error("file_base64 is not valid base64.")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        path = tmp.name
        try:
            for start in range(0, len(encoded), _DECODE_CHUNK):
                tmp.write(base64.b64decode(encoded[start:start + _DECODE_CHUNK], validate=True))
        except (binascii.Error, ValueError):
            tmp.close()
            os.remove(path)
            raise gr.Error("file_base64 is not valid base64.")
    return path


def _extract_path(path, file_name, ext, country_code, currency):
    summary, headers, n, truncated, persisted = _run_file(path, file_name, country_code or None, currency or None)
    staged = [p for p in persisted if p["table"] == "import_staging_rows" and p.get("op") != "UPDATE"]
    return {"file_name": file_name, "detected_type": ext, "headers": headers, "rows_processed": n,
            "rows_truncated_to_limit": truncated, "summary": summary, "staged_row_count": len(staged),
            "max_upload_bytes": MAX_UPLOAD_BYTES}


def extract_file(file_name: str, file_base64: str, country_code: str = "JO", currency: str = "JOD") -> dict:
    """Extract structured sales records from a .csv/.xlsx/.xlsm/.pdf file (base64-encoded; max EXTRACTION_MAX_UPLOAD_MB, default 500 MB)."""
    ext = _check_type(file_name)
    path = _decode_to_temp(file_base64, ext)
    try:
        return _extract_path(path, file_name, ext, country_code, currency)
    finally:
        os.remove(path)


def _run_text(text, known_products, known_competitors):
    conn = MemConn([
        (r"FROM products", lambda q, p: [({"en": n},) for n in known_products]),
        (r"FROM tenant_competitors", lambda q, p: [(n,) for n in known_competitors]),
    ])
    use_catalog = bool(known_products or known_competitors)
    ents = extractor.extract_entities(text, tenant_id=TENANT_ID if use_catalog else None,
                                      redis_client=_CacheMiss() if use_catalog else None, conn=conn if use_catalog else None)
    return [dataclasses.asdict(e) for e in ents]


def extract_text(text: str, known_products: list = None, known_competitors: list = None) -> dict:
    """Extract entities (dates, amounts, currencies, invoice/order IDs, emails, phones, products, competitors) from free text."""
    if not text or not text.strip():
        raise gr.Error("Provide some text.")
    if len(text) > 20000:
        raise gr.Error("Text is limited to 20,000 characters.")
    ents = _run_text(text, [str(x) for x in (known_products or [])], [str(x) for x in (known_competitors or [])])
    return {"entity_count": len(ents), "entities": ents}


def _ui_file(file_obj, csv_text, cc, cur):
    if file_obj is not None:
        # The uploaded file is already on disk: process it in place (no
        # base64 round trip, no full read into memory).
        upload_path = file_obj if isinstance(file_obj, str) else file_obj.name
        name = os.path.basename(upload_path)
        ext = _check_type(name)
        if os.path.getsize(upload_path) > MAX_UPLOAD_BYTES:
            raise _too_large(os.path.getsize(upload_path))
        out = _extract_path(upload_path, name, ext, cc, cur)
    else:
        out = extract_file("pasted.csv", base64.b64encode((csv_text or "").encode("utf-8")).decode(), cc, cur)
    s = out["summary"]
    md = (f"**{out['file_name']}** · template mode **{s.get('template_mode')}** · header coverage {s.get('header_coverage_ratio')} · "
          f"{s.get('rows_processed')} rows processed ({s.get('rows_partial')} partial, {s.get('rows_failed')} failed) · "
          f"{s.get('total_fields_extracted')}/{s.get('total_fields_expected')} fields extracted"
          + (" · *truncated to first 1000 rows*" if out["rows_truncated_to_limit"] else ""))
    rows = []
    for r in (s.get("row_outcomes") or [])[:200]:
        pr = r.get("parse_result") or {}
        rows.append([r.get("row_index"), r.get("mode"), json.dumps(pr.get("typed_fields") or {}, ensure_ascii=False, default=str)[:400],
                     json.dumps(r.get("field_errors") or {}, ensure_ascii=False), r.get("error")])
    return md, rows, out


def _ui_text(text, products, competitors):
    split = lambda s: [x.strip() for x in (s or "").split(",") if x.strip()]
    out = extract_text(text, split(products), split(competitors))
    rows = [[e["entity_type"], e["text"], e.get("normalized_value"), e.get("confidence")] for e in out["entities"]]
    return rows, out


def build_ui():
    gr.Markdown("## CEOPRO AI - Extraction\nRuns CEOPRO-AI's extraction code unchanged: file ingestion "
                "(`file_dispatch` + `ingestion_pipeline.process_records()`: template detection, header mapping, typed parsing, validation) "
                "and free-text entity extraction (`extractor.extract_entities()`). Deterministic, rule-based - no ML model.")
    with gr.Tab("File (CSV / XLSX / PDF)"):
        f_in = gr.File(label=f"Upload .csv / .xlsx / .xlsm / .pdf, up to {MAX_UPLOAD_MB} MB (optional - otherwise the CSV text below is used)",
                       file_types=[".csv", ".xlsx", ".xlsm", ".pdf"])
        csv_in = gr.Textbox(lines=4, label="Or paste CSV", value=EXAMPLE_IMPORT)
        with gr.Row():
            cc = gr.Textbox(value="JO", label="Company country code (date/decimal locale)")
            cur = gr.Textbox(value="JOD", label="Company currency")
        b1 = gr.Button("Extract file", variant="primary")
        md = gr.Markdown()
        tbl = gr.Dataframe(headers=["row", "mode", "typed fields", "field errors", "error"], label="Rows", wrap=True)
        raw1 = gr.JSON(label="Raw output")
        b1.click(_ui_file, [f_in, csv_in, cc, cur], [md, tbl, raw1], api_name="extract_file_ui")
    with gr.Tab("Free text"):
        t_in = gr.Textbox(lines=4, label="Text", value=EXAMPLE_TEXT)
        with gr.Row():
            kp = gr.Textbox(value="Premium Olive Oil 1L", label="Known products (comma-separated, optional)")
            kc = gr.Textbox(value="Rival Store", label="Known competitors (comma-separated, optional)")
        b2 = gr.Button("Extract entities", variant="primary")
        tbl2 = gr.Dataframe(headers=["type", "text", "normalized", "confidence"], label="Entities")
        raw2 = gr.JSON(label="Raw output")
        b2.click(_ui_text, [t_in, kp, kc], [tbl2, raw2], api_name="extract_text_ui")
    gr.api(extract_file, api_name="extract_file")
    gr.api(extract_text, api_name="extract_text")
