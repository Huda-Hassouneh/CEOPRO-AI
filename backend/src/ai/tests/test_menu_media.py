"""Menus published as PDFs or pictures: found on a competitor's own pages,
read (text layer or OCR), parsed by the page reader's price parser, tagged
with how they were read, and merged with - never overwriting - page facts.
OCR is injected, so these tests need no tesseract."""
import io

from src.market_scraper.market_discovery import intel, menu_media

HOME = """<html><body><a href="/menu">Menu</a><a href="/files/price-list.pdf">Price list</a>
<img src="/img/logo.png" alt="logo"><img src="/img/dinner-menu-page1.jpg" alt="Dinner menu">
<a href="https://other.example.com/menu.pdf">Partner menu</a></body></html>"""
MENU_PAGE = '<html><body><p>Kunafa Nabulsieh 3.50 JD</p><img src="/uploads/IMG_2041.jpg" alt=""><img src="/img/icon-phone.png"></body></html>'


def _pdf(lines):
    """A one-page PDF with a real text layer (hand-built, no dependency)."""
    stream = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


def _png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_menu_files_are_found_and_logos_icons_and_other_sites_are_not():
    same = lambda url, base: intel._same_site(url, base)  # noqa: SLF001
    links = menu_media.media_links(HOME, "https://cafe.jo/", False, same)
    assert links == ["https://cafe.jo/files/price-list.pdf", "https://cafe.jo/img/dinner-menu-page1.jpg"]
    # On a menu page an unnamed photo counts, an icon still does not.
    assert menu_media.media_links(MENU_PAGE, "https://cafe.jo/menu", True, same) == ["https://cafe.jo/uploads/IMG_2041.jpg"]
    assert menu_media.media_links(MENU_PAGE, "https://cafe.jo/about", False, same) == []


def test_ocr_confusions_are_repaired_only_inside_numbers():
    lines = menu_media.clean_ocr_lines("Mansaf  1O.5O JD\nSOS sauce\nShawarma 2,5O\n|||\n")
    assert lines == ["Mansaf 10.50 JD", "SOS sauce", "Shawarma 2,50"]


def test_a_pdf_with_a_text_layer_is_read_without_ocr():
    lines, method = menu_media.read_media(_pdf(["Mansaf 8.50 JD", "Falafel sandwich 1.25 JD"]), "application/pdf",
                                          ocr=None, ocr_ready=False)
    assert method == "pdf_text" and "Mansaf 8.50 JD" in lines


def test_a_picture_without_an_ocr_engine_is_reported_not_silently_dropped():
    assert menu_media.read_media(_png(), "image/png", ocr=None, ocr_ready=False) == ([], "skipped_no_ocr")
    assert menu_media.read_media(b"<html>", "text/html", ocr_ready=False) == ([], "not_media")


def _collect(files, ocr):
    pages = {"https://cafe.jo": HOME, "https://cafe.jo/menu": MENU_PAGE}
    return intel.collect("https://cafe.jo", fetch=lambda url: pages.get(url.rstrip("/")), country="JO",
                         fetch_media=lambda url: files.get(url), ocr=ocr)


def test_menu_picture_prices_join_the_facts_tagged_as_ocr():
    files = {"https://cafe.jo/img/dinner-menu-page1.jpg": (_png(), "image/png"),
             "https://cafe.jo/files/price-list.pdf": (_pdf(["Grilled chicken 6.50 JD"]), "application/pdf")}
    result = _collect(files, ocr=lambda image: "Mansaf 1O.5O JD\nFalafel sandwich 1.25 JD\nKunafa Nabulsieh 3.50 JD")
    products = {f["name"]: f for f in result["facts"] if f["kind"] == "product"}
    assert products["Mansaf"]["price"] == 10.5 and products["Mansaf"]["extracted_by"] == "ocr"
    assert products["Mansaf"]["confidence"] == menu_media.CONFIDENCE_OCR
    assert products["Mansaf"]["source_url"] == "https://cafe.jo/img/dinner-menu-page1.jpg"
    assert products["Grilled chicken"]["extracted_by"] == "pdf_text"
    assert result["media"]["found"] >= 2 and result["media"]["read"] == 2 and result["status"] == intel.STATUS_PRICES


def test_a_price_seen_in_the_page_text_and_the_picture_is_corroborated_not_duplicated():
    files = {"https://cafe.jo/img/dinner-menu-page1.jpg": (_png(), "image/png")}
    result = _collect(files, ocr=lambda image: "Kunafa Nabulsieh 3.50 JD\nBaklava 2.00 JD")
    kunafa = [f for f in result["facts"] if f["kind"] == "product" and f["name"] == "Kunafa Nabulsieh"]
    assert len(kunafa) == 1 and kunafa[0].get("extracted_by") is None
    assert kunafa[0]["also_seen_in"] == ["https://cafe.jo/img/dinner-menu-page1.jpg"]
    assert kunafa[0]["confidence"] == intel.CONFIDENCE_TEXT + menu_media.CONFIDENCE_CORROBORATED_BONUS


def test_a_conflicting_picture_price_is_kept_and_flagged():
    files = {"https://cafe.jo/img/dinner-menu-page1.jpg": (_png(), "image/png")}
    result = _collect(files, ocr=lambda image: "Kunafa Nabulsieh 4.50 JD")
    prices = sorted((f["price"], f.get("conflicts_with_price")) for f in result["facts"]
                    if f["kind"] == "product" and f["name"] == "Kunafa Nabulsieh")
    assert prices == [(3.5, None), (4.5, 3.5)]


def test_no_ocr_engine_is_visible_in_the_result():
    files = {"https://cafe.jo/img/dinner-menu-page1.jpg": (_png(), "image/png")}
    pages = {"https://cafe.jo": HOME}
    result = intel.collect("https://cafe.jo", fetch=lambda url: pages.get(url.rstrip("/")), country="JO",
                           fetch_media=lambda url: files.get(url))
    if not menu_media.ocr_available():
        assert result["media"]["skipped_no_ocr"] >= 1 and result["media"]["ocr_available"] is False


def test_deep_reads_more_pages_than_the_standard_read(monkeypatch):
    monkeypatch.setattr(intel, "MAX_PAGES", 1)
    monkeypatch.setattr(intel, "DEEP_MAX_PAGES", 4)
    home = '<html><body><a href="/menu">Menu</a><a href="/prices">Prices</a><a href="/offers">Offers</a></body></html>'
    pages = {"https://cafe.jo": home, "https://cafe.jo/menu": "<p>Mansaf 8 JD</p>", "https://cafe.jo/prices": "<p>Tea 1 JD</p>",
             "https://cafe.jo/offers": "<p>Cake 2 JD</p>"}
    fetch = lambda url: pages.get(url.rstrip("/"))  # noqa: E731
    standard = intel.collect("https://cafe.jo", fetch=fetch, country="JO")
    deep = intel.collect("https://cafe.jo", fetch=fetch, country="JO", deep=True)
    assert len(deep["pages_read"]) > len(standard["pages_read"])
    assert {f["name"] for f in deep["facts"] if f["kind"] == "product"} >= {"Mansaf", "Tea", "Cake"}


def test_a_reread_that_could_not_open_the_menu_files_keeps_what_they_gave_earlier():
    from unittest.mock import MagicMock

    from src.ai.market_inputs import competitor_intel
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    base = {"facts": [], "pages_read": ["https://cafe.jo"], "status": intel.STATUS_PRICES}
    competitor_intel.save_site_intel(conn, "t", "c", {**base, "media": {"found": 2, "read": 0, "skipped_no_ocr": 2}})
    deletes = [c.args[0] for c in cursor.execute.call_args_list if c.args[0].startswith("DELETE")]
    assert "source_media" in deletes[-1]
    cursor.reset_mock()
    competitor_intel.save_site_intel(conn, "t", "c", {**base, "media": {"found": 2, "read": 2}})
    deletes = [c.args[0] for c in cursor.execute.call_args_list if c.args[0].startswith("DELETE")]
    assert "source_media" not in deletes[-1]
