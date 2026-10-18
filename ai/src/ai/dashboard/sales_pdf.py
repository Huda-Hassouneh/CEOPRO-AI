"""
KEEL - Sales report as a printable PDF (Reports -> Download PDF).

For reading and sharing, not for re-importing: the period's totals, monthly
totals, the best-selling products and the most recent sale lines, in
English or Arabic (right to left). The complete line list stays in the CSV
and JSON exports (routers/reports.py), which stream any size; a PDF of tens
of thousands of lines helps nobody, so it shows the latest RECENT_LINES and
says where the rest is.

Totals are grouped by currency so a company that invoices in more than one
never sees them added together. Gross profit only counts lines whose product
has a cost price (the same rule as reports.py and financial_summary.py) and
says how much revenue that covers.

Fonts: DejaVu Sans (bundled in reports_pdf_fonts/, Bitstream Vera licence),
which covers Latin and Arabic. Arabic text is shaped with arabic-reshaper
and put in visual order with python-bidi, since the PDF library draws
glyphs left to right.
"""
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.ai.dashboard import reports as dashboard_reports

RECENT_LINES = 300
TOP_PRODUCTS = 20
_FONT_DIR = Path(__file__).resolve().parent.parent / "reports_pdf_fonts"
_fonts_ready = False

TEXT = {
    "en": {
        "title": "Sales report", "period": "Period", "all_time": "All recorded sales", "generated": "Generated",
        "summary": "Summary", "currency": "Currency", "lines": "Sale lines", "units": "Units sold",
        "revenue": "Revenue", "gross_profit": "Gross profit", "margin": "Gross margin",
        "profit_note": "Gross profit and margin count only lines whose product has a cost price ({covered}% of revenue).",
        "monthly": "Monthly totals", "month": "Month",
        "top": "Best-selling products (by revenue)", "product": "Product", "qty": "Qty",
        "recent": "Most recent sale lines", "date": "Date", "invoice": "Invoice", "unit_price": "Unit price",
        "total": "Total", "recent_note": "Showing the latest {shown} of {total} lines. The CSV and JSON exports contain every line.",
        "empty": "No sales were recorded in this period.", "page": "Page {n}",
    },
    "ar": {
        "title": "تقرير المبيعات", "period": "الفترة", "all_time": "كل المبيعات المسجلة", "generated": "تاريخ الإنشاء",
        "summary": "الملخص", "currency": "العملة", "lines": "بنود البيع", "units": "الوحدات المباعة",
        "revenue": "الإيرادات", "gross_profit": "إجمالي الربح", "margin": "هامش الربح الإجمالي",
        "profit_note": "يُحسب إجمالي الربح والهامش للبنود التي لمنتجها سعر تكلفة فقط ({covered}٪ من الإيرادات).",
        "monthly": "الإجماليات الشهرية", "month": "الشهر",
        "top": "المنتجات الأكثر مبيعًا (حسب الإيرادات)", "product": "المنتج", "qty": "الكمية",
        "recent": "أحدث بنود البيع", "date": "التاريخ", "invoice": "الفاتورة", "unit_price": "سعر الوحدة",
        "total": "الإجمالي", "recent_note": "يعرض أحدث {shown} من أصل {total} بندًا. ملفات CSV وJSON تحتوي على كل البنود.",
        "empty": "لا توجد مبيعات مسجلة في هذه الفترة.", "page": "صفحة {n}",
    },
}

_PARAMS = """
    ii.tenant_id = %(tenant_id)s
    AND (%(start_date)s::timestamptz IS NULL OR i.issue_date >= %(start_date)s)
    AND (%(end_date)s::timestamptz IS NULL OR i.issue_date < %(end_date)s)
"""
_FROM = """
    FROM invoice_items ii
    JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
    JOIN products p ON p.tenant_id = ii.tenant_id AND p.product_id = ii.product_id
"""
_PROFIT = "CASE WHEN p.cost_price IS NOT NULL THEN (ii.unit_price - p.cost_price) * ii.quantity END"


def report_data(conn, tenant_id: str, start_date: Optional[datetime], end_date: Optional[datetime]) -> dict:
    """Everything the PDF shows, read with the caller's tenant-scoped connection."""
    params = {"tenant_id": tenant_id, "start_date": start_date, "end_date": end_date, "top": TOP_PRODUCTS}
    with conn.cursor() as cursor:
        cursor.execute("SELECT business_name, COALESCE(timezone, 'UTC') FROM companies WHERE tenant_id = %(tenant_id)s;", params)
        company, tz_name = cursor.fetchone() or ("", "UTC")
        params["tz"] = tz_name
        cursor.execute(f"""
            SELECT i.currency, COUNT(*), SUM(ii.quantity), SUM(ii.total_price), SUM({_PROFIT}),
                   SUM(CASE WHEN p.cost_price IS NOT NULL THEN ii.total_price END)
            {_FROM} WHERE {_PARAMS} GROUP BY i.currency ORDER BY SUM(ii.total_price) DESC;""", params)
        totals = [dict(zip(("currency", "lines", "units", "revenue", "gross_profit", "revenue_with_cost"), row))
                  for row in cursor.fetchall()]
        cursor.execute(f"""
            SELECT to_char(date_trunc('month', i.issue_date AT TIME ZONE %(tz)s), 'YYYY-MM'), i.currency,
                   COUNT(*), SUM(ii.total_price), SUM({_PROFIT})
            {_FROM} WHERE {_PARAMS} GROUP BY 1, 2 ORDER BY 1 DESC, 2;""", params)
        monthly = [dict(zip(("month", "currency", "lines", "revenue", "gross_profit"), row)) for row in cursor.fetchall()]
        cursor.execute(f"""
            SELECT localized_text(p.product_name), i.currency, SUM(ii.quantity), SUM(ii.total_price), SUM({_PROFIT})
            {_FROM} WHERE {_PARAMS} GROUP BY p.product_id, 1, 2 ORDER BY SUM(ii.total_price) DESC LIMIT %(top)s;""", params)
        top = [dict(zip(("product", "currency", "units", "revenue", "gross_profit"), row)) for row in cursor.fetchall()]
    recent = dashboard_reports.get_sales_report(conn, tenant_id, start_date=start_date, end_date=end_date, limit=RECENT_LINES)
    return {"company": company, "start_date": start_date, "end_date": end_date, "totals": totals, "monthly": monthly,
            "top": top, "recent": recent["rows"], "total_lines": recent["total_row_count"]}


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("KeelSans", str(_FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("KeelSans-Bold", str(_FONT_DIR / "DejaVuSans-Bold.ttf")))
    _fonts_ready = True


def _shape(text, rtl: bool) -> str:
    text = "" if text is None else str(text)
    if not rtl:
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text), base_dir="R")


def _money(value) -> str:
    return "-" if value is None else f"{float(value):,.2f}"


def _number(value) -> str:
    if value is None:
        return "-"
    value = float(value)
    return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"


def _margin(profit, revenue_with_cost) -> str:
    if profit is None or not revenue_with_cost:
        return "-"
    return f"{float(profit) / float(revenue_with_cost) * 100:.1f}%"


def render_pdf(data: dict, lang: str = "en") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    text = TEXT.get(lang, TEXT["en"])
    rtl = lang == "ar"
    align = TA_RIGHT if rtl else TA_LEFT
    s = lambda value: _shape(value, rtl)  # noqa: E731
    title_style = ParagraphStyle("title", fontName="KeelSans-Bold", fontSize=18, leading=22, alignment=align)
    h_style = ParagraphStyle("h", fontName="KeelSans-Bold", fontSize=12, leading=16, alignment=align, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", fontName="KeelSans", fontSize=9, leading=12, alignment=align, textColor=colors.HexColor("#3c4150"))

    def table(header, rows, widths, numeric_from):
        # Right-to-left: columns run from the right, so the table is mirrored.
        cells = [[s(h) for h in header]] + [[s(c) for c in row] for row in rows]
        if rtl:
            cells = [list(reversed(r)) for r in cells]
            widths = list(reversed(widths))
        n = len(header)
        numeric_cols = [(n - 1 - i) if rtl else i for i in range(numeric_from, n)]
        text_cols = [c for c in range(n) if c not in numeric_cols]
        style = [
            ("FONTNAME", (0, 0), (-1, 0), "KeelSans-Bold"), ("FONTNAME", (0, 1), (-1, -1), "KeelSans"),
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3f3d9e")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#5b5bd6")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f8")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        style += [("ALIGN", (c, 0), (c, -1), "RIGHT") for c in numeric_cols]
        style += [("ALIGN", (c, 0), (c, -1), "RIGHT" if rtl else "LEFT") for c in text_cols]
        result = Table(cells, colWidths=[w * mm for w in widths], repeatRows=1, hAlign="RIGHT" if rtl else "LEFT")
        result.setStyle(TableStyle(style))
        return result

    period = text["all_time"]
    if data["start_date"] or data["end_date"]:
        start = data["start_date"].date().isoformat() if data["start_date"] else "…"
        end = data["end_date"].date().isoformat() if data["end_date"] else "…"
        period = f"{start} – {end}"
    story = [
        Paragraph(s(f"{data['company']} · {text['title']}"), title_style), Spacer(1, 3 * mm),
        Paragraph(s(f"{text['period']}: {period}"), body),
        Paragraph(s(f"{text['generated']}: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"), body),
    ]
    if not data["totals"]:
        story += [Spacer(1, 8 * mm), Paragraph(s(text["empty"]), body)]
    else:
        story.append(Paragraph(s(text["summary"]), h_style))
        story.append(table(
            [text["currency"], text["lines"], text["units"], text["revenue"], text["gross_profit"], text["margin"]],
            [[t["currency"], _number(t["lines"]), _number(t["units"]), _money(t["revenue"]), _money(t["gross_profit"]),
              _margin(t["gross_profit"], t["revenue_with_cost"])] for t in data["totals"]],
            [22, 26, 28, 36, 36, 30], 1))
        covered = sum(float(t["revenue_with_cost"] or 0) for t in data["totals"])
        revenue = sum(float(t["revenue"] or 0) for t in data["totals"])
        if revenue and covered < revenue:
            story.append(Paragraph(s(text["profit_note"].format(covered=round(covered / revenue * 100))), body))
        story.append(Paragraph(s(text["monthly"]), h_style))
        story.append(table([text["month"], text["currency"], text["lines"], text["revenue"], text["gross_profit"]],
                           [[m["month"], m["currency"], _number(m["lines"]), _money(m["revenue"]), _money(m["gross_profit"])]
                            for m in data["monthly"]], [30, 24, 30, 45, 45], 2))
        story.append(Paragraph(s(text["top"]), h_style))
        story.append(table([text["product"], text["currency"], text["qty"], text["revenue"], text["gross_profit"]],
                           [[p["product"], p["currency"], _number(p["units"]), _money(p["revenue"]), _money(p["gross_profit"])]
                            for p in data["top"]], [72, 20, 22, 30, 30], 2))
        story.append(Paragraph(s(text["recent"]), h_style))
        if data["total_lines"] > len(data["recent"]):
            story.append(Paragraph(s(text["recent_note"].format(shown=len(data["recent"]), total=f"{data['total_lines']:,}")), body))
        story.append(table(
            [text["date"], text["invoice"], text["product"], text["qty"], text["unit_price"], text["total"], text["gross_profit"]],
            [[r["issue_date"][:10], r["invoice_number"] or "", r["product_name"], _number(r["quantity"]), _money(r["unit_price"]),
              _money(r["total_price"]), _money(r["line_gross_profit"])] for r in data["recent"]],
            [20, 26, 54, 14, 22, 22, 22], 3))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("KeelSans", 7)
        canvas.setFillColor(colors.HexColor("#7a8090"))
        label = s(f"KEEL · {text['page'].format(n=doc.page)}")
        (canvas.drawString if rtl else canvas.drawRightString)(
            15 * mm if rtl else A4[0] - 15 * mm, 10 * mm, label)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=18 * mm, title=f"{data['company']} - {TEXT['en']['title']}", author="KEEL")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
