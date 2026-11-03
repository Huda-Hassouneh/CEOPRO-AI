"""
Arabic / bidirectional-text regressions (docs/ARABIC_AI_QUALITY_REPORT.md).

Every PDF here is made at test time; the Chromium/tesseract cases skip when
those tools are not installed. Text is compared by Unicode code point in
LOGICAL order - what search, citations and copy/paste see - never by how a
viewer happens to display it.
"""
import io
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from scripts.arabic_benchmark import ground_truth as gt
from scripts.arabic_benchmark import metrics as m
from src.ai.extraction import pdf_text
from src.ai.rag import data_access

ARABIC_LINES = [
    "تلتزم شركة الندى بتوصيل الطلبات داخل عمان خلال 48 ساعة",
    "رسوم التوصيل 2.50 دينار والتوصيل مجاني فوق 40 دينار",
    "لا تقبل إعادة المنتجات تحت الرمز SKU-AN-1042 لأسباب صحية",
    "للاستفسار زوروا https://alnada.example/returns أو اتصلوا بنا",
    "الإجمالي المستحق: ٢١٩٫٥٩ دينار (شامل الضريبة)",
]


class _Minio:
    def __init__(self, data):
        self.data = data

    def get_object(self, bucket, key):
        obj = MagicMock()
        obj.read.return_value = self.data
        return obj


def _reportlab_pdf(lines=ARABIC_LINES, columns=None, table=None) -> bytes:
    """A PDF drawn the way KEEL's own exports are: reshaped + bidi-reordered
    presentation-form glyphs, laid out left to right."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = os.path.join(os.path.dirname(__file__), "..", "reports_pdf_fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("TestDejaVu", font))
    visual = lambda text: get_display(arabic_reshaper.reshape(text), base_dir="R")  # noqa: E731
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setFont("TestDejaVu", 12)
    y = height - 60
    for line in lines or []:
        pdf.drawRightString(width - 50, y, visual(line))
        y -= 22
    if columns:
        right, left = columns
        for n, (r, l) in enumerate(zip(right, left)):
            pdf.drawRightString(width - 50, y - n * 22, visual(r))
            pdf.drawRightString(width / 2 - 30, y - n * 22, visual(l))
    if table:
        from reportlab.platypus import Table, TableStyle

        cells = [[visual(c) for c in reversed(row)] for row in table]  # RTL table: first column on the right
        grid = Table(cells, colWidths=[110] * len(table[0]))
        grid.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "TestDejaVu"), ("GRID", (0, 0), (-1, -1), 0.8, "black")]))
        grid.wrapOn(pdf, width, height)
        grid.drawOn(pdf, 60, y - 120)
    pdf.save()
    return buffer.getvalue()


# --- bidi inversion -------------------------------------------------------------

def test_visual_to_logical_inverts_the_bidi_algorithm_exactly():
    """For every benchmark paragraph and tricky mixed string: render it with the
    UBA, read it back, get the original code points."""
    from bidi.algorithm import get_display

    cases = list(gt.RTL_CASES) + [t for d in gt.DOCUMENTS.values() for _, t in gt.paragraphs(d)] + [
        "رقم الهاتف 079-123-4567 للتواصل", "من 3 إلى 5 أيام", "السعر (8.90 دينار) شامل", "الطلب #1042 جاهز",
        "زيت OL-500 و OL-1000 متوفران", "Price: 8.90 دينار", "اتصل: +962 79 123 4567",
    ]
    for logical in cases:
        assert pdf_text.visual_to_logical(list(get_display(logical, base_dir="R")), "R") == logical


def test_a_wrapped_line_is_read_with_its_paragraph_context():
    """Digits continuing a Latin code on the previous line (an IBAN wrapped
    after "JO71 CBJO") are rendered as part of that LTR run."""
    visual = list(".0131 0003 02")
    assert pdf_text.visual_to_logical(visual, "R", context="L") == "0131 0003 02."
    assert pdf_text.visual_to_logical(visual, "R") == "02 0003 0131."  # without context: the standalone reading


# --- PDF extraction (knowledge base + data import) --------------------------------

def test_keel_style_pdf_arabic_comes_back_in_logical_order_not_reversed_glyphs():
    text = data_access.fetch_document_text(_Minio(_reportlab_pdf()), "b", "policy.pdf")
    for line in ARABIC_LINES:
        assert line in text
    assert not any("ﹰ" <= ch <= "\ufeff" for ch in text), "presentation-form glyphs leaked into the text"


def test_two_columns_are_read_right_column_first():
    right = ["العمود الأيمن السطر الأول", "العمود الأيمن السطر الثاني", "العمود الأيمن السطر الثالث", "العمود الأيمن السطر الرابع"]
    left = ["العمود الأيسر السطر الأول", "العمود الأيسر السطر الثاني", "العمود الأيسر السطر الثالث", "العمود الأيسر السطر الرابع"]
    text = data_access.fetch_document_text(_Minio(_reportlab_pdf(lines=[], columns=(right, left))), "b", "news.pdf")
    positions = [text.index(line) for line in right + left]
    assert positions == sorted(positions)


def test_pdf_table_headers_and_cells_are_logical_arabic(tmp_path):
    from src.ai.extraction.adapters.pdf_adapter import read_pdf_file

    table = [["رمز المنتج", "اسم المنتج", "السعر"], ["OL-500", "زيت زيتون 500 مل", "4.75"], ["OL-1000", "زيت زيتون 1 لتر", "8.90"]]
    path = tmp_path / "prices.pdf"
    path.write_bytes(_reportlab_pdf(lines=[], table=table))
    headers, rows = read_pdf_file(str(path))
    assert headers == table[0]
    assert rows == [dict(zip(table[0], row)) for row in table[1:]]


def test_kb_pdf_table_rows_stay_together_in_logical_column_order():
    table = [["الصنف", "الكمية"], ["تمر مجدول", "٥"]]
    text = data_access.fetch_document_text(_Minio(_reportlab_pdf(lines=["فاتورة"], table=table)), "b", "inv.pdf")
    assert "الصنف\tالكمية" in text and "تمر مجدول\t٥" in text


@pytest.mark.skipif(not shutil.which("soffice") and not any(os.path.exists(p) for p in ["/opt/pw-browsers"]), reason="no PDF producer")
def test_browser_made_arabic_pdf_extracts_with_near_zero_character_errors():
    from scripts.arabic_benchmark.build_corpus import build_pdf_chromium

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.pdf")
            build_pdf_chromium(gt.POLICY_AR, path)
            raw = open(path, "rb").read()
    except Exception as err:  # noqa: BLE001
        pytest.skip(f"Chromium unavailable: {err}")
    text, _ = pdf_text.extract_text(raw, ocr=False)
    # Measured 0.0018: Chromium itself writes one shadda+fatha glyph with no Unicode mapping.
    assert m.cer(gt.reference_text(gt.POLICY_AR), text) < 0.01


@pytest.mark.skipif(not pdf_text.ocr_available(), reason="tesseract not installed")
def test_a_scanned_arabic_pdf_is_read_by_ocr_instead_of_failing_empty():
    import pdfplumber

    with pdfplumber.open(io.BytesIO(_reportlab_pdf(lines=ARABIC_LINES[:2]))) as pdf:
        image = pdf.pages[0].to_image(resolution=200).original.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF", resolution=200)
    text = data_access.fetch_document_text(_Minio(buffer.getvalue()), "b", "scan.pdf")
    assert text.strip(), "a scan must not become an empty (Failed) document"
    assert m.cer(m.search_norm(" ".join(ARABIC_LINES[:2])), m.search_norm(text)) < 0.15


# --- Word / text files --------------------------------------------------------------

def test_docx_tables_are_extracted_in_document_order():
    import docx

    document = docx.Document()
    document.add_paragraph("قائمة الأسعار")
    table = document.add_table(rows=2, cols=2)
    for r, row in enumerate([["المنتج", "السعر"], ["زيت زيتون 1 لتر", "8.90"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    document.add_paragraph("غرامة التأخير 1.5%")
    buffer = io.BytesIO()
    document.save(buffer)
    text = data_access.fetch_document_text(_Minio(buffer.getvalue()), "b", "contract.docx")
    assert text.index("قائمة الأسعار") < text.index("زيت زيتون 1 لتر\t8.90") < text.index("غرامة التأخير 1.5%")


def test_windows_1256_arabic_text_files_are_decoded_not_failed():
    raw = "سياسة الإرجاع: خلال 14 يوماً".encode("cp1256")
    assert data_access.fetch_document_text(_Minio(raw), "b", "policy.txt") == "سياسة الإرجاع: خلال 14 يوماً"
    assert data_access.fetch_document_text(_Minio("\ufeffنص".encode("utf-8")), "b", "a.txt") == "نص"


# --- retrieval --------------------------------------------------------------------

def test_keyword_search_ignores_diacritics_letter_variants_and_digit_scripts():
    from src.ai.rag.bm25_index import BM25Index, tokenize

    assert tokenize("إِنَّ رِضا العَميلِ") == ["ان", "رضا", "عميل"]  # not split into "إ", "ن", ...
    index = BM25Index([("policy", "قال المدير: إِنَّ رِضا العَميلِ غايتُنا. ساعات خدمة العملاء 9:00"),
                       ("invoice", "الإجمالي المستحق: ٢١٩٫٥٩ دينار"), ("other", "Warehouse handbook")])
    assert index.query("ما هي غاية الشركة حسب رضا العميل؟")[0].chunk_id == "policy"
    assert index.query("اوقات خدمه العملاء")[0].chunk_id == "policy"
    assert index.query("الاجمالي 219.59")[0].chunk_id == "invoice"


def test_relevance_filter_matches_words_with_attached_prepositions():
    from src.ai.rag import advisor

    assert advisor._relevant("كل كم نقطة بتعطيني قسيمة؟", "يمكن استبدال كل 100 نقطة بقسيمة شراء قيمتها 5 دنانير")
    assert not advisor._relevant("ما هي شروط الدفع؟", "payment terms are net 45 days")


# --- exports ------------------------------------------------------------------------

def _sales_data(company):
    from decimal import Decimal

    return {"company": company, "start_date": None, "end_date": None,
            "totals": [{"currency": "JOD", "lines": 1, "units": 5, "revenue": Decimal("45.00"),
                        "gross_profit": Decimal("10.00"), "revenue_with_cost": Decimal("45.00")}],
            "monthly": [], "top": [], "total_lines": 1,
            "recent": [{"issue_date": "2026-02-15", "invoice_number": "INV-2026-0042", "product_name": "تمر مجدول 1 كغم",
                        "quantity": 5, "unit_price": Decimal("9.00"), "total_price": Decimal("45.00"),
                        "line_gross_profit": Decimal("10.00")}]}


def test_arabic_sales_report_keeps_wrapped_lines_in_reading_order():
    """A title long enough to wrap used to show its END on the first line."""
    from src.ai.dashboard import sales_pdf

    company = "شركة الندى للتجارة والتوزيع والخدمات اللوجستية في المملكة الأردنية الهاشمية"
    pdf = sales_pdf.render_pdf(_sales_data(company), lang="ar")
    text, _ = pdf_text.extract_text(pdf, ocr=False)
    title = m.ws(text[:text.index(sales_pdf.TEXT["ar"]["title"]) + len(sales_pdf.TEXT["ar"]["title"])])
    assert title == f"{company} · {sales_pdf.TEXT['ar']['title']}"
    assert "INV-2026-0042" in text and "2026-02-15" in text and "تمر مجدول 1 كغم" in text


def test_sales_report_dates_after_arabic_stay_in_reading_order_and_markup_is_escaped():
    from src.ai.dashboard import sales_pdf

    assert "2026-11-03 18:49 UTC" in sales_pdf._shape("تاريخ الإنشاء: 2026-11-03 18:49 UTC", True)
    assert sales_pdf._shape("INV-2026-0042", True) == "INV-2026-0042"
    assert sales_pdf.render_pdf(_sales_data("Salt & Pepper <Demo>"), lang="en")[:4] == b"%PDF"
    assert sales_pdf.render_pdf(_sales_data("الملح & الفلفل <تجريبي>"), lang="ar")[:4] == b"%PDF"


# --- marketing typography -------------------------------------------------------------

def test_typography_wraps_in_logical_order_and_right_aligns_arabic():
    from PIL import Image, ImageDraw

    from src.ai.marketing import typography

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    text = "قهوة عربية بالهيل رفيقة صباحك اليومي مع العائلة والأصدقاء"
    lines = typography.wrap(draw, text, typography._font(80, text), 600, True)
    assert len(lines) > 1 and " ".join(lines) == text

    def ink_columns(png):
        """Leftmost / rightmost columns holding the white headline glyphs."""
        image = Image.open(io.BytesIO(png)).convert("L")
        band = image.crop((0, image.height // 2, image.width, image.height)).point(lambda v: 255 if v >= 250 else 0)
        box = band.getbbox()
        return box[0], box[2]

    background = Image.new("RGB", (1080, 1080), (90, 110, 90))
    ar_left, ar_right = ink_columns(typography.compose(background, "زيت زيتون"))
    en_left, en_right = ink_columns(typography.compose(background, "Olive oil"))
    assert ar_right > 1080 - 120 and ar_left > 300  # a short Arabic headline hugs the right margin
    assert en_left < 120 and en_right < 780        # a short English one the left


@pytest.mark.skipif(not pdf_text.ocr_available(), reason="tesseract not installed")
def test_typography_arabic_is_shaped_and_readable_by_ocr():
    import subprocess

    from src.ai.marketing import typography

    for text in ("زيت زيتون بكر ممتاز من الندى", "اطلب الآن"):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "l.png")
            typography.render_line(text).save(path)
            out = subprocess.run(["tesseract", path, "-", "-l", "ara", "--psm", "7"], capture_output=True, text=True).stdout
        assert m.cer(m.search_norm(text), m.search_norm(out)) <= 0.05, out


def test_generate_image_with_text_overlay_draws_the_campaign_copy_on_the_ai_image(monkeypatch):
    from fastapi.testclient import TestClient
    from PIL import Image

    from src.ai.main import app
    from src.ai.marketing.image_generation import GeneratedImage
    from src.ai.tests.test_marketing import _auth, _fake_campaign_row_for_image

    monkeypatch.setenv("MARKETING_IMAGE_PROVIDER", "pollinations")
    plain = io.BytesIO()
    Image.new("RGB", (1024, 1024), (40, 80, 60)).save(plain, format="PNG")
    row = _fake_campaign_row_for_image(content={"INSTAGRAM": [{"headline": "زيت زيتون بكر ممتاز", "cta": "اطلب الآن", "body_copy": "x", "hashtags": []}]})
    generated = GeneratedImage(content=plain.getvalue(), content_type="image/png", provider="pollinations")
    with patch("src.ai.routers.marketing.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.data_access.get_campaign", return_value=row), \
         patch("src.ai.routers.marketing.image_generation.generate_campaign_image", return_value=generated), \
         patch("src.ai.routers.marketing.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.marketing.image_storage.upload_generated_image", return_value="t1/c1/g.png") as upload, \
         patch("src.ai.routers.marketing.data_access.save_generated_image"):
        response = TestClient(app).post("/marketing/campaigns/c1/generate-image", headers=_auth(), json={"text_overlay": True})
    assert response.status_code == 200, response.text
    assert response.json()["text_overlay"] is True
    stored = Image.open(io.BytesIO(upload.call_args.args[1])).convert("RGB")
    assert stored.size == (1024, 1024)
    assert stored.getpixel((10, 10)) == (40, 80, 60)                      # background kept
    assert max(stored.crop((0, 700, 1024, 1024)).convert("L").getdata()) > 240  # text drawn in the lower part


# --- marketing copy -------------------------------------------------------------------

def test_arabic_hashtags_are_joined_into_single_platform_tags():
    from src.ai.marketing.content_generator import _parse_response

    raw = ('{"audience_summary": "a", "creative_direction": "b", "platforms": {"INSTAGRAM": [{"headline": "h", '
           '"body_copy": "c", "hashtags": ["#زيت زيتون", "زيت_زيتون", "#Olive-Oil", "##عسل!", "#olive_oil"], "cta": "d"}]}}')
    campaign = _parse_response(raw, ("INSTAGRAM",))
    assert campaign.variants_by_platform["INSTAGRAM"][0].hashtags == ["#زيت_زيتون", "#Olive_Oil", "#عسل"]
