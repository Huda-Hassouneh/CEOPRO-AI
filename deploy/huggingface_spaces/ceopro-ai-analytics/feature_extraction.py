"""
CEOPRO AI - Extraction. Runs the unmodified CEOPRO-AI extraction code:
  - file:  src/ai/extraction/file_dispatch.read_source_file() + ingestion_pipeline.process_records()
           (template detection, header mapping, typed row parsing, validation, regex/NER fallback)
  - text:  src/ai/extraction/extractor.extract_entities() (regex tier + optional catalog tier)
"""
import base64
import dataclasses
import json
import os
import tempfile

import gradio as gr

from memdb import MemConn
from src.ai.extraction import extractor, file_dispatch, ingestion_pipeline

TENANT_ID = "public-demo-tenant"
JOB_ID = "public-demo-job"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # same 10MB cap as src/ai/main.py
MAX_ROWS = 1000
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


def _run_file(path, source_name, country_code, currency):
    headers, rows = file_dispatch.read_source_file(path)
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    conn = MemConn([_company_route(country_code, currency)])
    summary = ingestion_pipeline.process_records(tenant_id=TENANT_ID, job_id=JOB_ID, source_name=source_name,
                                                 headers=headers, rows=rows, conn=conn)
    out = dataclasses.asdict(summary) if dataclasses.is_dataclass(summary) else dict(vars(summary))
    return json.loads(json.dumps(out, default=str)), headers, len(rows), truncated, conn.persisted


def extract_file(file_name: str, file_base64: str, country_code: str = "JO", currency: str = "JOD") -> dict:
    """Extract structured sales records from a .csv/.xlsx/.xlsm/.pdf file (base64-encoded)."""
    try:
        ext = file_dispatch.detect_file_type(file_name or "")
    except file_dispatch.UnsupportedFileTypeError as exc:
        raise gr.Error(str(exc))
    try:
        data = base64.b64decode(file_base64, validate=True)
    except Exception:
        raise gr.Error("file_base64 is not valid base64.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise gr.Error(f"File exceeds the {MAX_UPLOAD_BYTES}-byte limit.")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        summary, headers, n, truncated, persisted = _run_file(path, file_name, country_code or None, currency or None)
    finally:
        os.remove(path)
    staged = [p for p in persisted if p["table"] == "import_staging_rows" and p.get("op") != "UPDATE"]
    return {"file_name": file_name, "detected_type": ext, "headers": headers, "rows_processed": n,
            "rows_truncated_to_limit": truncated, "summary": summary, "staged_row_count": len(staged)}


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
        name = os.path.basename(file_obj if isinstance(file_obj, str) else file_obj.name)
        data = open(file_obj if isinstance(file_obj, str) else file_obj.name, "rb").read()
    else:
        name, data = "pasted.csv", (csv_text or "").encode("utf-8")
    out = extract_file(name, base64.b64encode(data).decode(), cc, cur)
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
        f_in = gr.File(label="Upload .csv / .xlsx / .xlsm / .pdf (optional - otherwise the CSV text below is used)",
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
