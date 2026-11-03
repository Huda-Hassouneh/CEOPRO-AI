"""
KEEL Arabic quality benchmark runner.

    python -m scripts.arabic_benchmark.run_benchmark [--corpus DIR] [--json OUT] [--sections extraction,rag,rtl,image]

Runs KEEL's REAL code paths on the synthetic corpus (build_corpus.py):
- extraction: rag/data_access.fetch_document_text() - the knowledge-base
  ingestion path - and extraction/file_dispatch.read_source_file() - the Data
  Connections import path - scored against ground_truth.py.
- rag: the knowledge-base retrieval stack (chunking.chunk_text ->
  BM25Index (+ FAISS/re-ranker when their model weights are obtainable) ->
  RRF -> the advisor's own chunk admission filter), 43 questions, P@K / R@K /
  MRR / nDCG@K. Answer generation runs only with --llm (a hosted LLM call per
  question; needs a working provider key) - never implicitly.
- rtl: logical-order round trips through JSON, PostgreSQL-style UTF-8 bytes,
  the CSV export encoder, and the Arabic PDF export (rendered, then OCR'd).
- image: the Arabic typography layer on a generated/background image,
  verified by OCR.

Nothing here calls a paid service unless --llm is given.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import time
from typing import Dict, List

from scripts.arabic_benchmark import ground_truth as gt
from scripts.arabic_benchmark import metrics as m


class _FakeObject:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinio:
    """Serves local files as MinIO objects so fetch_document_text() runs unchanged."""

    def __init__(self, directory: str):
        self.directory = directory

    def get_object(self, bucket, key):
        with open(os.path.join(self.directory, key), "rb") as handle:
            return _FakeObject(handle.read())


def _round(value, digits=4):
    return round(value, digits) if isinstance(value, float) else value


def score_text(doc: dict, text: str) -> Dict[str, float]:
    reference = gt.reference_text(doc)
    result = {"cer": m.cer(reference, text), "wer": m.wer(reference, text), "chars_out": len(text)}
    result.update(m.word_stats(reference, text))
    result.update(m.arabic_preservation(reference, text))
    result["numeric_accuracy"] = m.numeric_accuracy(doc.get("numbers", []), text)
    result.update(m.reading_order([p for _, p in gt.paragraphs(doc)], text))
    rows = [r for t in doc.get("tables", []) for r in t["rows"]]
    if "sheets" in doc:
        rows = [[str(c) for c in r] for s in doc["sheets"].values() for r in s["rows"]]
    if rows:
        result["table_row_accuracy"] = m.table_row_accuracy(rows, text)
    if doc.get("fields"):
        result["field_accuracy"] = m.field_accuracy(doc["fields"], doc["field_labels"], text)
    return {k: _round(v) for k, v in result.items()}


def _rows_to_text(headers, rows) -> str:
    lines = ["\t".join(str(h) for h in headers)]
    for row in rows:
        lines.append("\t".join("" if v is None else str(v) for v in row.values()))
    return "\n".join(lines)


def run_extraction(corpus: str) -> dict:
    from src.ai.rag.data_access import fetch_document_text
    from src.ai.extraction.file_dispatch import read_source_file, SUPPORTED_EXTENSIONS

    minio = FakeMinio(corpus)
    results = {}
    for name, doc_id, kind in gt.FILES:
        doc = gt.DOCUMENTS[doc_id]
        entry = {"document": doc_id, "producer": kind, "lang": doc["lang"]}
        started = time.perf_counter()
        try:
            text = fetch_document_text(minio, "bench", name)
            entry["knowledge_base"] = score_text(doc, text)
            entry["knowledge_base"]["ok"] = bool(text.strip())
            entry["knowledge_base_sample"] = m.ws(text)[:160]
        except Exception as err:  # noqa: BLE001 - a failure is a result
            entry["knowledge_base"] = {"ok": False, "error": f"{type(err).__name__}: {err}"[:200]}
        entry["knowledge_base"]["seconds"] = round(time.perf_counter() - started, 3)
        ext = os.path.splitext(name)[1]
        if ext in SUPPORTED_EXTENSIONS:
            started = time.perf_counter()
            try:
                headers, rows = read_source_file(os.path.join(corpus, name))
                text = _rows_to_text(headers, rows)
                entry["data_import"] = score_text(doc, text)
                entry["data_import"]["ok"] = bool(rows)
                entry["data_import"]["headers"] = [str(h) for h in headers][:8]
            except Exception as err:  # noqa: BLE001
                entry["data_import"] = {"ok": False, "error": f"{type(err).__name__}: {err}"[:200]}
            entry["data_import"]["seconds"] = round(time.perf_counter() - started, 3)
        results[name] = entry
    return results


def _relevant(chunk_text: str, question: dict) -> bool:
    return bool(question["evidence"]) and m.search_norm(question["evidence"]) in m.search_norm(chunk_text)


def run_rag(corpus: str, files: List[str], k_values=(1, 3, 5), llm: bool = False, chunk_words: int = None) -> dict:
    from src.ai.rag import advisor
    from src.ai.rag.bm25_index import BM25Index
    from src.ai.rag.chunking import chunk_text
    from src.ai.rag.data_access import fetch_document_text
    from src.ai.rag.embeddings import try_embed
    from src.ai.rag.faiss_index import FAISSIndex
    from src.ai.rag.hybrid_retrieval import reciprocal_rank_fusion

    minio = FakeMinio(corpus)
    chunks = []  # (chunk_id, text)
    for name in files:
        try:
            text = fetch_document_text(minio, "bench", name)
        except Exception:  # noqa: BLE001
            text = ""
        pieces = chunk_text(text, chunk_words, max(1, chunk_words // 4)) if chunk_words else chunk_text(text)
        for n, chunk in enumerate(pieces):
            chunks.append((f"{name}#{n}", chunk))
    bm25 = BM25Index(chunks)
    vectors = try_embed([c for _, c in chunks]) if chunks else None
    semantic = vectors is not None
    faiss = FAISSIndex(chunks, vectors) if semantic else None

    reranker_ok = False
    if semantic and os.getenv("RAG_RERANKER_ENABLED", "true").lower() not in ("0", "false"):
        try:
            from src.ai.rag.reranking import get_model
            get_model()
            reranker_ok = True
        except Exception:  # noqa: BLE001
            reranker_ok = False

    per_question = []
    for question in gt.QUESTIONS:
        started = time.perf_counter()
        lexical = bm25.query(question["q"], top_k=20)
        if semantic:
            query_vector = try_embed([question["q"]])[0]
            fused = reciprocal_rank_fusion(lexical, faiss.query(query_vector, top_k=20), top_k=20)
        else:
            fused = lexical[:20]
        if reranker_ok and fused:
            from src.ai.rag.reranking import rerank
            fused = rerank(question["q"], fused, top_k=20)
        admits = advisor._chunk_filter(question["q"], [c.text for c in fused])
        admitted = [c for c in fused if admits(c.text)]
        seconds = time.perf_counter() - started
        total_relevant = sum(_relevant(text, question) for _, text in chunks)
        row = {"id": question["id"], "kind": question["kind"], "relevant_chunks": total_relevant,
               "seconds": round(seconds, 4)}
        for label, ranked in (("retrieval", fused), ("admitted", admitted)):
            rel = [_relevant(c.text, question) for c in ranked]
            row[label] = {
                "mrr": m.mrr(rel),
                **{f"p@{k}": m.precision_at_k(rel, k) for k in k_values},
                **{f"r@{k}": m.recall_at_k(rel, k, total_relevant) for k in k_values},
                **{f"hit@{k}": m.hit_at_k(rel, k) for k in k_values},
                **{f"ndcg@{k}": m.ndcg_at_k(rel, k, total_relevant) for k in k_values},
                "returned": len(ranked),
                "top": [c.chunk_id for c in ranked[:3]],
            }
        per_question.append(row)

    answerable = [r for r in per_question if gt.QUESTIONS[[q["id"] for q in gt.QUESTIONS].index(r["id"])]["gold"]]
    unanswerable = [r for r in per_question if r not in answerable]

    def mean(rows, label, key):
        return round(sum(r[label][key] for r in rows) / max(1, len(rows)), 4)

    keys = ["mrr"] + [f"{p}@{k}" for p in ("p", "r", "hit", "ndcg") for k in k_values]
    summary = {label: {key: mean(answerable, label, key) for key in keys} for label in ("retrieval", "admitted")}
    by_kind = {}
    for kind in sorted({r["kind"] for r in answerable}):
        rows = [r for r in answerable if r["kind"] == kind]
        by_kind[kind] = {"n": len(rows), **{f"admitted_{key}": mean(rows, "admitted", key) for key in ("mrr", "hit@1", "hit@5", "r@5")}}
    result = {
        "files": files, "chunk_words": chunk_words or "default (200/40)", "chunks": len(chunks), "semantic_model": semantic, "reranker": reranker_ok,
        "answerable_questions": len(answerable), "unanswerable_questions": len(unanswerable),
        "unanswerable_with_admitted_evidence": sum(r["admitted"]["returned"] > 0 for r in unanswerable),
        "answerable_with_no_relevant_chunk_in_corpus": sum(r["relevant_chunks"] == 0 for r in answerable),
        "summary": summary, "by_kind": by_kind, "per_question": per_question,
        "mean_query_seconds": round(sum(r["seconds"] for r in per_question) / len(per_question), 4),
    }
    if llm:
        result["answers"] = run_answers(chunks, bm25)
    return result


def run_answers(chunks, bm25) -> dict:
    """Optional, explicit: one hosted LLM call per question through KEEL's
    own llm_client (provider, prompt, metering rules unchanged)."""
    from src.ai.rag import llm_client
    from src.ai.rag.pipeline import assemble_context

    rows = []
    for question in gt.QUESTIONS:
        context = assemble_context(question["q"], bm25.query(question["q"], top_k=5))
        messages = [{"role": "system", "content": llm_client.SYSTEM_PROMPT},
                    {"role": "user", "content": f"Context:\n{context.context_text}\n\nQuestion: {question['q']}"}]
        try:
            answer = llm_client.chat_completion(messages, temperature=0, max_tokens=900)
            error = None
        except Exception as err:  # noqa: BLE001
            answer, error = "", f"{type(err).__name__}: {err}"[:200]
        norm = m.search_norm(answer)
        facts_ok = all(m.search_norm(f) in norm for f in question["facts"]) if question["facts"] else None
        rows.append({"id": question["id"], "kind": question["kind"], "answer": answer, "error": error,
                     "facts_present": facts_ok})
    return {"rows": rows, "errors": sum(1 for r in rows if r["error"])}


def run_rtl() -> dict:
    """Logical order must survive every hop untouched - compared by code point."""
    import csv

    results = []
    for case in gt.RTL_CASES:
        hops = {}
        hops["json"] = json.loads(json.dumps({"v": case}, ensure_ascii=False))["v"] == case
        hops["utf8_bytes"] = case.encode("utf-8").decode("utf-8") == case
        buffer = io.StringIO()
        csv.writer(buffer).writerow([case])
        hops["csv"] = next(csv.reader(io.StringIO(buffer.getvalue())))[0] == case
        results.append({"case": case, **hops})
    return {"cases": results, "all_pass": all(all(v for k, v in r.items() if k != "case") for r in results)}


def run_pdf_export_ocr() -> dict:
    """Renders KEEL's Arabic sales-report PDF (dashboard/sales_pdf.py) and
    reads it back by OCR, so the check is what a person SEES, not the PDF's
    internal glyph order."""
    import subprocess

    from src.ai.dashboard import sales_pdf

    from decimal import Decimal

    company = "شركة الندى للتجارة والتوزيع والخدمات اللوجستية في المملكة الأردنية الهاشمية"  # long: forces a wrap
    data = {
        "company": company, "start_date": None, "end_date": None,
        "totals": [{"currency": "JOD", "lines": 3, "units": 19, "revenue": Decimal("189.30"),
                    "gross_profit": Decimal("40.10"), "revenue_with_cost": Decimal("150.00")}],
        "monthly": [{"month": "2026-02", "currency": "JOD", "lines": 3, "revenue": Decimal("189.30"), "gross_profit": Decimal("40.10")}],
        "top": [{"product": "زيت زيتون بكر ممتاز 1 لتر", "currency": "JOD", "units": 12, "revenue": Decimal("106.80"), "gross_profit": Decimal("20.00")}],
        "recent": [{"issue_date": "2026-02-15", "invoice_number": "INV-2026-0042", "product_name": "تمر مجدول 1 كغم",
                    "quantity": 5, "unit_price": Decimal("9.00"), "total_price": Decimal("45.00"), "line_gross_profit": Decimal("10.00")}],
        "total_lines": 1,
    }
    try:
        pdf = sales_pdf.render_pdf(data, lang="ar")
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": f"{type(err).__name__}: {err}"[:300]}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "r.pdf")
        with open(path, "wb") as handle:
            handle.write(pdf)
        subprocess.run(["pdftoppm", "-r", "250", "-png", "-f", "1", "-l", "1", path, os.path.join(tmp, "p")], check=True)
        png = [f for f in os.listdir(tmp) if f.endswith(".png")][0]
        out = subprocess.run(["tesseract", os.path.join(tmp, png), "-", "-l", "ara+eng", "--psm", "4"],
                             capture_output=True, text=True).stdout
    title = f"{company} · {sales_pdf.TEXT['ar']['title']}"
    norm_out = m.search_norm(out).replace("·", " ")
    found = {}
    for label, value in {"summary heading": sales_pdf.TEXT["ar"]["summary"], "product name cell": "زيت زيتون بكر ممتاز 1 لتر",
                         "invoice code": "INV-2026-0042", "amount": "189.30"}.items():
        want = m.ws(m.search_norm(value))
        found[label] = want in m.ws(norm_out) or m.cer(want, _best_window(want, norm_out)) < 0.12
    # Seen on the page: the generation date drawn in reading order (UBA alone draws "03-11-2026").
    today = time.strftime("%Y-%m-%d", time.gmtime())
    found["generation date displayed in reading order (OCR)"] = today in out
    # Read back in logical order from the drawn glyphs (extraction/pdf_text.py, verified against the UBA):
    # a wrapped Arabic title must still start with its first words. Tesseract skips the large title line.
    from src.ai.extraction import pdf_text

    logical, _ = pdf_text.extract_text(pdf, ocr=False)
    found["wrapped title in reading order (logical read-back)"] = m.ws(logical).startswith(m.ws(title))
    return {"ok": all(found.values()), "found": found, "ocr_sample": m.ws(out)[:400],
            "logical_sample": m.ws(logical)[:200]}


def _best_window(want: str, text: str) -> str:
    """The span of `text` (same length as `want`) closest to it - OCR tolerance for long strings."""
    text = m.ws(text)
    if len(text) <= len(want):
        return text
    best, best_d = text[:len(want)], len(want)
    step = max(1, len(want) // 8)
    for start in range(0, len(text) - len(want) + 1, step):
        window = text[start:start + len(want)]
        d = m.levenshtein(want, window)
        if d < best_d:
            best, best_d = window, d
    return best


def run_image() -> dict:
    """Arabic text layer drawn over an image, read back by OCR."""
    from PIL import Image

    try:
        from src.ai.marketing import typography
    except ImportError:
        return {"ok": False, "error": "no typography layer (src/ai/marketing/typography.py) in this checkout"}
    cases = [
        ("زيت زيتون بكر ممتاز من الندى", "اطلب الآن"),
        ("عسل سدر 500 غرام – طعم الأصالة", "تسوق اليوم"),
        ("خصم خاص على OL-1000 هذا الأسبوع", None),
        ("قهوة عربية بالهيل، رفيقة صباحك اليومي مع العائلة والأصدقاء", "اكتشف المزيد"),
        ("Fresh Sidr honey for Ramadan", "Shop now"),
    ]
    rows = []
    fonts = {"default (first available)": None}
    bundled = os.path.join(os.path.dirname(__file__), "..", "..", "src", "ai", "reports_pdf_fonts", "DejaVuSans-Bold.ttf")
    fonts["bundled DejaVu Sans Bold (Docker image)"] = os.path.abspath(bundled)
    for font_label, font_path in fonts.items():
        if font_path:
            typography._FONTS = (font_path,)
        else:
            typography._FONTS = typography.__dict__.get("_DEFAULT_FONTS", typography._FONTS)
        typography._DEFAULT_FONTS = typography.__dict__.get("_DEFAULT_FONTS", typography._FONTS)
        for headline, cta in cases:
            background = Image.new("RGB", (1080, 1080), (120, 150, 110))
            png = typography.compose(background, headline=headline, cta=cta)
            composed = _ocr_typography(png, headline, cta)
            scores, texts = {}, {}
            for label, value in (("headline", headline), ("cta", cta)):
                if not value:
                    continue
                texts[label] = _ocr_line(typography.render_line(value), value)
                want, got = m.search_norm(value), m.ws(m.search_norm(texts[label]))
                scores[label] = round(m.cer(want, got), 4)
            composed_want = m.search_norm(headline)
            composed_got = m.ws(m.search_norm(composed.get("headline", "")))
            scores["headline_in_composed_image"] = round(
                0.0 if composed_want in composed_got else m.cer(composed_want, _best_window(composed_want, composed_got)), 4)
            out = " | ".join(texts.values())
            rows.append({"font": font_label, "headline": headline, "cta": cta, "rtl": typography.is_rtl(headline),
                         "ocr": m.ws(out)[:160], "cer": scores})
    typography._FONTS = typography._DEFAULT_FONTS
    element_cers = [v for r in rows for k, v in r["cer"].items() if k != "headline_in_composed_image"]
    return {"ok": all(v <= 0.10 for v in element_cers), "libraqm": typography.RAQM, "rows": rows,
            "mean_element_cer": round(sum(element_cers) / len(element_cers), 4),
            "method": "Each headline/CTA rendered by typography.render_line() (the exact shaping path compose() "
                      "uses) black on white, read by tesseract as one line (psm 7, Arabic model for Arabic text); CER "
                      "vs the expected string (search-normalised). Secondary: the headline read back from the composed "
                      "image (mask of its white pixels, psm 6) - noisier, reported, not gated."}


def _ocr_line(image, text: str) -> str:
    import subprocess

    has_arabic = any("\u0600" <= ch <= "\u06ff" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text)
    lang = ("ara+eng" if has_latin else "ara") if has_arabic else "eng"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "l.png")
        image.save(path)
        return subprocess.run(["tesseract", path, "-", "-l", lang, "--psm", "7"], capture_output=True, text=True).stdout


def _ocr_typography(png: bytes, headline: str, cta) -> dict:
    """Tesseract language per element: Arabic-only for pure Arabic text (the
    mixed model misreads Arabic words as Latin), Arabic+English when mixed."""
    def lang_for(text):
        if not text:
            return "eng"
        has_latin = any("a" <= ch.lower() <= "z" for ch in text)
        return ("ara+eng" if has_latin else "ara") if any("\u0600" <= ch <= "\u06ff" for ch in text) else "eng"
    langs = (lang_for(headline), lang_for(cta))
    has_cta = bool(cta)
    import subprocess

    import numpy as np
    from PIL import Image

    image = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    found = {}

    def read(array, text_lang):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.png")
            Image.fromarray(array.astype("uint8")).save(path)
            return subprocess.run(["tesseract", path, "-", "-l", text_lang, "--psm", "6"], capture_output=True, text=True).stdout

    white = (image.min(axis=2) >= 250)
    found["headline"] = read(np.where(white, 0, 255), langs[0])
    if has_cta:
        pill = (image.min(axis=2) >= 225) & (image.max(axis=2) <= 248)
        rows = np.where(pill.sum(axis=1) > 80)[0]
        cols = np.where(pill[rows].sum(axis=0) > 0.3 * len(rows))[0] if len(rows) else []
        if len(rows) and len(cols):
            crop = image[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
            found["cta"] = read(np.where(crop.mean(axis=2) < 128, 0, 255), langs[1])
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=os.path.join(tempfile.gettempdir(), "keel-arabic-benchmark"))
    parser.add_argument("--json", dest="json_out")
    parser.add_argument("--sections", default="extraction,rag,rtl,image")
    parser.add_argument("--llm", action="store_true", help="also generate answers with the configured hosted LLM (costs provider quota)")
    args = parser.parse_args(argv)

    from scripts.arabic_benchmark.build_corpus import build

    build(args.corpus)
    sections = set(args.sections.split(","))
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if "extraction" in sections:
        report["extraction"] = run_extraction(args.corpus)
    if "rag" in sections:
        report["rag_native"] = run_rag(args.corpus, gt.RAG_CORPUS, llm=args.llm)
        report["rag_scanned"] = run_rag(args.corpus, gt.RAG_CORPUS_SCANNED)
        # Passage-level sensitivity run: the benchmark documents are short, so
        # with the default 200-word window each is one chunk (document-level retrieval).
        report["rag_native_passages"] = run_rag(args.corpus, gt.RAG_CORPUS, chunk_words=40)
    if "rtl" in sections:
        report["rtl_roundtrip"] = run_rtl()
        report["pdf_export_ocr"] = run_pdf_export_ocr()
    if "image" in sections:
        report["image_typography"] = run_image()
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(text)
    print_summary(report)
    return 0


def print_summary(report: dict) -> None:
    out = sys.stdout
    if "extraction" in report:
        out.write("\n## Extraction (knowledge-base path)\n")
        out.write("file | CER | WER | missing | reversed | ar-letters | pres-forms | numbers | order | table | fields | ok\n")
        for name, entry in report["extraction"].items():
            kb = entry["knowledge_base"]
            if "cer" not in kb:
                out.write(f"{name} | ERROR {kb.get('error')}\n")
                continue
            out.write(" | ".join(str(x) for x in [
                name, kb["cer"], kb["wer"], kb["missing_word_rate"], kb["reversed_arabic_word_rate"],
                kb["arabic_letter_recall"], kb["presentation_form_chars"], kb["numeric_accuracy"],
                kb["reading_order_accuracy"], kb.get("table_row_accuracy", "-"), kb.get("field_accuracy", "-"), kb["ok"]]) + "\n")
        out.write("\n## Extraction (data-import path)\n")
        for name, entry in report["extraction"].items():
            di = entry.get("data_import")
            if di is None:
                continue
            if "cer" not in di:
                out.write(f"{name} | ERROR {di.get('error')}\n")
                continue
            out.write(f"{name} | CER {di['cer']} | numbers {di['numeric_accuracy']} | table {di.get('table_row_accuracy', '-')} | headers {di.get('headers')}\n")
    for key in ("rag_native", "rag_scanned", "rag_native_passages"):
        if key in report:
            rag = report[key]
            out.write(f"\n## RAG {key}: chunks={rag['chunks']} semantic={rag['semantic_model']} reranker={rag['reranker']}\n")
            for label, values in rag["summary"].items():
                out.write(f"{label}: " + ", ".join(f"{k}={v}" for k, v in values.items()) + "\n")
            out.write("by kind (admitted): " + json.dumps(rag["by_kind"], ensure_ascii=False) + "\n")
            out.write(f"unanswerable with admitted evidence: {rag['unanswerable_with_admitted_evidence']}/{rag['unanswerable_questions']}\n")
    if "rtl_roundtrip" in report:
        out.write(f"\n## RTL round trip all pass: {report['rtl_roundtrip']['all_pass']}\n")
        out.write(f"PDF export OCR: {json.dumps(report['pdf_export_ocr'], ensure_ascii=False)}\n")
    if "image_typography" in report:
        out.write(f"\n## Image typography: {json.dumps(report['image_typography'], ensure_ascii=False)[:1200]}\n")


if __name__ == "__main__":
    raise SystemExit(main())
