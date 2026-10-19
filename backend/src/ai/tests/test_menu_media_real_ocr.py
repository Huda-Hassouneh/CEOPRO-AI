"""Menu pictures through the REAL tesseract (English, Arabic, scanned PDF). Skipped when tesseract, its Arabic data
or a font is missing - e.g. on the CI runner; run inside the worker image (Dockerfile.market-workers) to exercise it.
Verified 2026-10-19 on tesseract 5.5.0 (python:3.11-slim) and 5.3.4 (ubuntu 24.04, the Playwright worker base)."""
import io
import os

import pytest

from src.market_scraper.market_discovery import intel, menu_media

FONT = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                         "/Library/Fonts/Arial Unicode.ttf") if os.path.exists(p)), None)
READY = menu_media.ocr_available() and FONT is not None
pytestmark = pytest.mark.skipif(not READY, reason="tesseract or a Unicode font is not installed")
PIL = pytest.importorskip("PIL")


def _picture(rows, width=900, size=34, arabic=False):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(FONT, size)
    image = Image.new("RGB", (width, 120 + len(rows) * (size * 2)), "white")
    draw = ImageDraw.Draw(image)
    for index, row in enumerate(rows):
        if arabic:
            import arabic_reshaper
            from bidi.algorithm import get_display
            draw.text((width - 500, 30 + index * size * 2), get_display(arabic_reshaper.reshape(row)), fill="black", font=font, anchor="ra")
        else:
            draw.text((40, 30 + index * size * 2), row, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return image, buffer.getvalue()


def _facts(lines, method):
    return {(f["name"], f["price"]) for f in menu_media.media_facts(lines, method, "https://x/menu", "now", "JO", intel.text_prices)}


def test_an_english_menu_picture_is_read_into_priced_items():
    _image, data = _picture(["Mansaf  8.50 JD", "Falafel sandwich  1.25 JD", "Shawarma chicken  2.75 JD", "Kunafa Nabulsieh  3.50 JD", "Tea  0.75 JD"])
    lines, method = menu_media.read_media(data, "image/png")
    assert method == "ocr"
    assert _facts(lines, method) >= {("Mansaf", 8.5), ("Falafel sandwich", 1.25), ("Shawarma chicken", 2.75), ("Tea", 0.75)}


def test_a_scanned_pdf_is_read_through_ocr():
    image, _data = _picture(["Mansaf  8.50 JD", "Falafel sandwich  1.25 JD", "Tea  0.75 JD"])
    pdf = io.BytesIO()
    image.save(pdf, "PDF", resolution=150)
    lines, method = menu_media.read_media(pdf.getvalue(), "application/pdf")
    assert method == "ocr" and ("Tea", 0.75) in _facts(lines, method)


def test_an_arabic_menu_picture_keeps_prices_currency_and_logical_order():
    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    if "ara" not in __import__("pytesseract").get_languages(config=""):
        pytest.skip("tesseract Arabic data is not installed")
    _image, data = _picture(["منسف 8.50 دينار", "شاورما دجاج 2.75 دينار", "كنافة نابلسية 3.50 دينار", "فلافل 1.25 دينار"], width=1400, size=60, arabic=True)
    lines, method = menu_media.read_media(data, "image/png")
    facts = menu_media.media_facts(lines, method, "https://x/menu", "now", "JO", intel.text_prices)
    # Arabic is a weaker read than Latin: on this synthetic picture 2-3 of the 4 lines come back usable (a line
    # whose currency word is misread as Latin junk is lost, and its pieces can come back in visual order). What
    # must hold: the usable lines keep the right amount and currency and a logical-order Arabic name. For menus
    # where this is not enough, DISCOVERY_VISION_OCR=fallback is the remedy (pending action #92).
    assert len(facts) >= 2 and all(f["currency"] == "JOD" for f in facts)
    assert any(f["name"] == "شاورما دجاج" and f["price"] == 2.75 for f in facts)
