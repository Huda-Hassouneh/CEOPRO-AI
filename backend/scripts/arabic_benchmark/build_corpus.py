"""
Builds the synthetic Arabic benchmark files from ground_truth.py.

    python -m scripts.arabic_benchmark.build_corpus --out <dir>

Producers (each a real-world way an Arabic file reaches KEEL):
- pdf_chromium: HTML printed to PDF by headless Chromium (Skia/HarfBuzz, the
  same text pipeline as "Save as PDF" in Chrome/Edge).
- pdf_libreoffice: the .docx converted by LibreOffice (an office-suite PDF).
- pdf_reportlab: arabic-reshaper + python-bidi + ReportLab - KEEL's own export
  technique (dashboard/sales_pdf.py), i.e. presentation-form glyphs in
  visual order.
- pdf_scanned: the Chromium PDF rasterised at 200 dpi, slightly rotated,
  blurred and noised, saved as an image-only PDF (no text layer).
- docx: python-docx with RTL paragraphs (w:bidi) and a real Word table.
- xlsx: openpyxl, Arabic sheet names/headers, Arabic-Indic digits as text.

Deterministic apart from producer version strings; needs Chromium
(/opt/pw-browsers or CHROMIUM_PATH), LibreOffice (soffice) and pdftoppm.
"""
import argparse
import glob
import html
import os
import random
import shutil
import subprocess
import tempfile

from scripts.arabic_benchmark import ground_truth as gt

AR_FONT = "Noto Naskh Arabic"


def _chromium() -> str:
    for candidate in [os.getenv("CHROMIUM_PATH", "")] + sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux64/chrome")) + [
            shutil.which("chromium") or "", shutil.which("google-chrome") or ""]:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("Chromium not found (set CHROMIUM_PATH)")


def _dir(doc) -> str:
    return "ltr" if doc["lang"] == "en" else "rtl"


def _html(doc) -> str:
    tables = gt.tables_of(doc)
    body = [f"<h1>{html.escape(doc['title'])}</h1>"]
    if "columns" in doc:
        cols = "".join("<div class='col'>" + "".join(f"<p>{html.escape(t)}</p>" for _, t in column) + "</div>"
                       for column in doc["columns"])
        body.append(f"<div class='cols'>{cols}</div>")
    else:
        for n, page in enumerate(doc["pages"]):
            if n:
                body.append("<div style='page-break-before: always'></div>")
            for pid, text in page:
                if pid == "TABLE":
                    table = tables[text]
                    head = "".join(f"<th>{html.escape(h)}</th>" for h in table["header"])
                    rows = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in table["rows"])
                    body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
                else:
                    body.append(f"<p>{html.escape(text)}</p>")
    return f"""<!doctype html><html lang="{'en' if doc['lang'] == 'en' else 'ar'}" dir="{_dir(doc)}"><head><meta charset="utf-8">
<style>
 @page {{ size: A4; margin: 18mm; }}
 body {{ font-family: '{AR_FONT}', 'DejaVu Sans', sans-serif; font-size: 13pt; line-height: 1.7; }}
 h1 {{ font-size: 18pt; }}
 table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
 td, th {{ border: 1px solid #444; padding: 4px 8px; }}
 .cols {{ display: flex; gap: 28px; }} .col {{ flex: 1; }}
</style></head><body>{''.join(body)}</body></html>"""


def build_pdf_chromium(doc, out_path):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "doc.html")
        with open(src, "w", encoding="utf-8") as handle:
            handle.write(_html(doc))
        subprocess.run([_chromium(), "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={out_path}", f"file://{src}"], check=True, capture_output=True, timeout=120)


def _rtl_paragraph(paragraph, rtl: bool):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    if rtl:
        ppr = paragraph._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        ppr.insert(0, bidi)
    for run in paragraph.runs:
        rpr = run._r.get_or_add_rPr()
        fonts = OxmlElement("w:rFonts")
        fonts.set(qn("w:cs"), AR_FONT)
        fonts.set(qn("w:ascii"), "DejaVu Sans")
        fonts.set(qn("w:hAnsi"), "DejaVu Sans")
        rpr.insert(0, fonts)
        if rtl:
            rpr.append(OxmlElement("w:rtl"))


def build_docx(doc, out_path):
    import docx
    from docx.oxml import OxmlElement

    rtl = doc["lang"] != "en"
    document = docx.Document()
    tables = gt.tables_of(doc)
    _rtl_paragraph(document.add_heading(doc["title"], level=1), rtl)
    for n, page in enumerate(doc.get("pages", [])):
        if n:
            document.add_page_break()
        for pid, text in page:
            if pid == "TABLE":
                table = tables[text]
                word_table = document.add_table(rows=1 + len(table["rows"]), cols=len(table["header"]))
                word_table.style = "Table Grid"
                if rtl:
                    tbl_pr = word_table._tbl.tblPr
                    tbl_pr.append(OxmlElement("w:bidiVisual"))
                for r, row in enumerate([table["header"]] + table["rows"]):
                    for c, value in enumerate(row):
                        cell = word_table.cell(r, c)
                        cell.text = value
                        for paragraph in cell.paragraphs:
                            _rtl_paragraph(paragraph, rtl)
            else:
                _rtl_paragraph(document.add_paragraph(text), rtl)
    document.save(out_path)


def build_pdf_libreoffice(doc, out_path):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "doc.docx")
        build_docx(doc, src)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, src],
                       check=True, capture_output=True, timeout=180)
        shutil.move(os.path.join(tmp, "doc.pdf"), out_path)


def build_pdf_reportlab(doc, out_path):
    """KEEL's export technique: reshape + bidi to visual order, draw left to right."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src", "ai", "reports_pdf_fonts")
    pdfmetrics.registerFont(TTFont("BenchDejaVu", os.path.join(font_dir, "DejaVuSans.ttf")))

    pdf = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    margin = 50

    def visual(text):
        return get_display(arabic_reshaper.reshape(text), base_dir="R")

    for n, page in enumerate(doc["pages"]):
        if n:
            pdf.showPage()
        y = height - margin
        lines = ([doc["title"]] if n == 0 else []) + [text for pid, text in page if pid != "TABLE"]
        for text in lines:
            # Wrap in logical order first, then reorder each line (as sales_pdf.py does per cell).
            words, current, wrapped = text.split(), "", []
            for word in words:
                trial = f"{current} {word}".strip()
                if pdfmetrics.stringWidth(visual(trial), "BenchDejaVu", 12) > width - 2 * margin and current:
                    wrapped.append(current)
                    current = word
                else:
                    current = trial
            wrapped.append(current)
            for line in wrapped:
                pdf.setFont("BenchDejaVu", 12)
                pdf.drawRightString(width - margin, y, visual(line))
                y -= 20
            y -= 6
    pdf.save()


def build_pdf_scanned(doc, out_path, seed=7):
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        native = os.path.join(tmp, "native.pdf")
        build_pdf_chromium(doc, native)
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", native, os.path.join(tmp, "page")], check=True)
        pages = []
        for path in sorted(glob.glob(os.path.join(tmp, "page*.png"))):
            image = Image.open(path).convert("L")
            image = image.rotate(rng.uniform(-0.8, 0.8), expand=False, fillcolor=255, resample=Image.BICUBIC)
            image = image.filter(ImageFilter.GaussianBlur(0.6))
            noise = Image.effect_noise(image.size, 18)
            image = Image.blend(image, noise, 0.08)
            pages.append(image.convert("RGB"))
        pages[0].save(out_path, save_all=True, append_images=pages[1:], resolution=200)


def build_xlsx(doc, out_path):
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, data in doc["sheets"].items():
        sheet = workbook.create_sheet(name)
        sheet.sheet_view.rightToLeft = True
        sheet.append(data["header"])
        for row in data["rows"]:
            sheet.append(row)
    workbook.save(out_path)


BUILDERS = {"pdf_chromium": build_pdf_chromium, "pdf_libreoffice": build_pdf_libreoffice,
            "pdf_reportlab": build_pdf_reportlab, "pdf_scanned": build_pdf_scanned, "docx": build_docx,
            "xlsx": build_xlsx}


def build(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    built = {}
    for name, doc_id, kind in gt.FILES:
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            BUILDERS[kind](gt.DOCUMENTS[doc_id], path)
        built[name] = path
    return built


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "keel-arabic-benchmark"))
    args = parser.parse_args()
    for name, path in build(args.out).items():
        print(f"{name}\t{os.path.getsize(path)} bytes")
