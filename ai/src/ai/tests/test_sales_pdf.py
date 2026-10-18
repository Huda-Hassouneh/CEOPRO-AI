"""The sales report PDF renderer (dashboard/sales_pdf.py), without a database."""
from datetime import datetime, timezone

from src.ai.dashboard import sales_pdf


def _data(**overrides):
    data = {
        "company": "Zaytouna Fine Foods", "start_date": datetime(2026, 9, 1, tzinfo=timezone.utc), "end_date": None,
        "totals": [{"currency": "JOD", "lines": 2, "units": 3, "revenue": 30, "gross_profit": 12, "revenue_with_cost": 20}],
        "monthly": [{"month": "2026-09", "currency": "JOD", "lines": 2, "revenue": 30, "gross_profit": 12}],
        "top": [{"product": "زيت زيتون بكر", "currency": "JOD", "units": 3, "revenue": 30, "gross_profit": 12}],
        "recent": [{"issue_date": "2026-09-02T00:00:00+00:00", "invoice_number": "=HYPERLINK(1)", "product_name": "Olive Oil",
                    "quantity": 1.0, "unit_price": 10.0, "total_price": 10.0, "line_gross_profit": None}],
        "total_lines": 5000,
    }
    data.update(overrides)
    return data


def test_renders_english_and_arabic():
    for lang in ("en", "ar"):
        pdf = sales_pdf.render_pdf(_data(), lang)
        assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")


def test_an_empty_period_still_renders():
    assert sales_pdf.render_pdf(_data(totals=[], monthly=[], top=[], recent=[], total_lines=0), "ar").startswith(b"%PDF-")


def test_arabic_text_is_shaped_for_right_to_left():
    shaped = sales_pdf._shape("تقرير المبيعات", rtl=True)
    assert shaped != "تقرير المبيعات"           # joined letter forms, visual order
    assert sales_pdf._shape("Sales", rtl=False) == "Sales"


def test_number_formatting_and_unknown_profit():
    assert sales_pdf._money(1234.5) == "1,234.50" and sales_pdf._money(None) == "-"
    assert sales_pdf._number(3.0) == "3" and sales_pdf._number(2.5) == "2.50"
    assert sales_pdf._margin(12, 20) == "60.0%" and sales_pdf._margin(None, 20) == "-"


def test_every_label_exists_in_both_languages():
    assert set(sales_pdf.TEXT["en"]) == set(sales_pdf.TEXT["ar"])
