import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from src.ai import db
from src.ai.core import usage
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.dashboard import financial_summary as dashboard_financial_summary
from src.ai.dashboard import reports as dashboard_reports
from src.ai.dashboard import sales_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales")
def sales_report(
    start_date: Optional[datetime] = Query(default=None, description="Inclusive - ISO 8601, e.g. 2026-01-01"),
    end_date: Optional[datetime] = Query(default=None, description="Exclusive - ISO 8601"),
    limit: int = Query(default=dashboard_reports.DEFAULT_ROW_LIMIT, ge=1, le=dashboard_reports.MAX_ROW_LIMIT),
    offset: int = Query(default=0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    One page of this tenant's invoice line items, most recent first
    (`offset`/`limit`; `total_row_count` covers the whole period). The full
    period downloads from /reports/sales/export.
    """
    _check_range(start_date, end_date)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_reports.get_sales_report(
            conn, ctx.tenant_id, start_date=start_date, end_date=end_date, limit=limit, offset=offset)
        conn.commit()
        return result
    finally:
        conn.close()


# Column order and headers match the Reports page's own table.
EXPORT_COLUMNS = ("issue_date", "invoice_number", "product_name", "quantity", "unit_price", "total_price", "line_gross_profit")
EXPORT_HEADERS = {
    "en": ("Date", "Invoice", "Product", "Qty", "Unit Price", "Total", "Gross Profit"),
    "ar": ("التاريخ", "الفاتورة", "المنتج", "الكمية", "سعر الوحدة", "الإجمالي", "إجمالي الربح"),
}


def _check_range(start_date: Optional[datetime], end_date: Optional[datetime]) -> None:
    if start_date and end_date and start_date >= end_date:
        raise HTTPException(status_code=422, detail="start_date must be before end_date.")


def _csv_safe(value):
    """Spreadsheets run cells that start with = + - @ as formulas; a product
    or invoice name must never be able to do that in someone's export."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


def _csv_lines(rows: Iterator[dict], lang: str) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    # A byte-order mark so Excel opens Arabic text as UTF-8.
    buffer.write("\ufeff")
    writer.writerow(EXPORT_HEADERS.get(lang, EXPORT_HEADERS["en"]))
    for count, row in enumerate(rows, 1):
        writer.writerow([_csv_safe(row[column]) for column in EXPORT_COLUMNS])
        if count % 500 == 0:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue()


def _json_chunks(rows: Iterator[dict], start_date, end_date) -> Iterator[str]:
    yield '{"rows": ['
    count = 0
    for count, row in enumerate(rows, 1):
        yield ("," if count > 1 else "") + json.dumps(row, ensure_ascii=False)
    yield "], " + json.dumps({
        "total_row_count": count,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False)[1:]


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,120}$")
REPORT_DEDUP_SECONDS = 600


def report_key(ctx: TenantContext, idempotency_key: Optional[str], *parts) -> str:
    """Which report this request is, for counting: the client's
    Idempotency-Key when it sends one, otherwise the same person asking for
    the same export within ten minutes (a double click or a retry)."""
    if idempotency_key is not None:
        if not _IDEMPOTENCY_KEY.match(idempotency_key):
            raise HTTPException(status_code=422, detail="Idempotency-Key must be 8-120 letters, digits, '-', '_', '.' or ':'.")
        return f"client:{ctx.user_id}:{idempotency_key}"
    material = ":".join([ctx.user_id, *[str(p) for p in parts], str(int(time.time() // REPORT_DEDUP_SECONDS))])
    return "auto:" + hashlib.sha256(material.encode()).hexdigest()[:48]


def count_report(ctx: TenantContext, key: str, fingerprint: Optional[str] = None) -> Optional[dict]:
    """One report against the plan's monthly allowance (402 when used up)."""
    try:
        return usage.reserve_request(ctx.tenant_id, usage.MONTHLY_REPORTS, key, ctx.user_id,
                                     request_fingerprint=fingerprint)
    except usage.PlanLimitReached as err:
        raise err.as_http()


@router.get("/sales/export")
def export_sales_report(
    format: str = Query(default="csv", pattern="^(csv|json|pdf)$"),
    lang: str = Query(default="en", pattern="^(en|ar)$"),
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Every line item in the period as CSV or JSON, streamed in batches -
    not limited to what the page has loaded. PDF is a printable summary of
    the period (dashboard/sales_pdf.py). Each export counts as one report
    against the plan's monthly allowance; a failed export is given back."""
    _check_range(start_date, end_date)
    parts = ("sales", format, lang, start_date, end_date)
    fingerprint = hashlib.sha256(json.dumps(parts, default=str, ensure_ascii=True).encode()).hexdigest()
    counted = count_report(ctx, report_key(ctx, idempotency_key, *parts), fingerprint)
    try:
        conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    except Exception:
        usage.release_request(counted)
        raise
    if format == "pdf":
        try:
            data = sales_pdf.report_data(conn, ctx.tenant_id, start_date, end_date)
            conn.commit()
            content = sales_pdf.render_pdf(data, lang)
        except Exception:
            usage.release_request(counted)
            raise
        finally:
            conn.close()
        filename = f"keel-sales-report-{datetime.now(timezone.utc):%Y-%m-%d}.pdf"
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    def body() -> Iterator[bytes]:
        try:
            rows = dashboard_reports.iter_sales_rows(conn, ctx.tenant_id, start_date=start_date, end_date=end_date)
            chunks = _csv_lines(rows, lang) if format == "csv" else _json_chunks(rows, start_date, end_date)
            for chunk in chunks:
                yield chunk.encode("utf-8")
            conn.commit()
        except Exception:
            usage.release_request(counted)
            raise
        finally:
            conn.close()

    filename = f"keel-sales-report-{datetime.now(timezone.utc):%Y-%m-%d}.{format}"
    media_type = "text/csv; charset=utf-8" if format == "csv" else "application/json"
    return StreamingResponse(body(), media_type=media_type,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/financial-summary")
def financial_summary_report(
    window_days: int = Query(default=dashboard_financial_summary.DEFAULT_WINDOW_DAYS, ge=1, le=365),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    The same deterministic gross-profit/gross-margin numbers the
    Business Copilot's financial answers already use
    (dashboard/financial_summary.py::get_profitability_summary) - now
    also directly viewable/exportable as a report, not only reachable by
    asking the chat. Gross profit only - see that module's own docstring
    for why this is never labeled "net profit".
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = dashboard_financial_summary.get_profitability_summary(conn, ctx.tenant_id, window_days=window_days)
        conn.commit()
        return result
    finally:
        conn.close()
