"""
Unit tests for routers/reports.py - same offline-unit convention as
test_products.py/test_marketing.py: DB fully mocked, assertions on the
HTTP contract and on exactly what the endpoint hands down to
dashboard/reports.py and dashboard/financial_summary.py. Real behavior of
those two modules is covered by test_dashboard_reports_integration_db.py
(live-DB) and the existing financial_summary live-DB tests.
"""
import os
from unittest.mock import MagicMock, patch

import time

import jwt
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.main import app  # noqa: E402

client = TestClient(app)
_SECRET = os.environ["JWT_SECRET"]


def _token(tenant_id="t1", user_id="u1"):
    return jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "exp": int(time.time()) + 3600}, _SECRET, algorithm="HS256")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_sales_report_requires_auth():
    response = client.get("/reports/sales")
    assert response.status_code == 401


def test_sales_report_returns_the_real_result():
    fake_conn = MagicMock()
    fake_result = {"rows": [], "returned_row_count": 0, "total_row_count": 0, "truncated": False, "start_date": None, "end_date": None, "generated_at": "2026-01-01T00:00:00+00:00"}
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.reports.dashboard_reports.get_sales_report", return_value=fake_result) as mock_get:
        response = client.get("/reports/sales", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.close.assert_called_once()  # a read: the connection goes back, nothing to commit
    mock_get.assert_called_once_with(fake_conn, "t1", start_date=None, end_date=None, limit=1000, offset=0)


def test_sales_report_passes_through_date_range_and_limit():
    fake_conn = MagicMock()
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.reports.dashboard_reports.get_sales_report", return_value={"rows": []}) as mock_get:
        response = client.get(
            "/reports/sales",
            params={"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-02-01T00:00:00Z", "limit": 50},
            headers=_auth(),
        )

    assert response.status_code == 200
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["limit"] == 50
    assert call_kwargs["start_date"] is not None
    assert call_kwargs["end_date"] is not None


def test_sales_report_rejects_start_date_after_end_date():
    response = client.get(
        "/reports/sales",
        params={"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-01-01T00:00:00Z"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_sales_report_rejects_limit_over_the_cap():
    response = client.get("/reports/sales", params={"limit": 999999}, headers=_auth())
    assert response.status_code == 422


def test_financial_summary_report_requires_auth():
    response = client.get("/reports/financial-summary")
    assert response.status_code == 401


def test_financial_summary_report_returns_the_real_result():
    fake_conn = MagicMock()
    fake_result = {"revenue": 100.0, "gross_profit": 40.0, "gross_margin_pct": 40.0, "cost_data_coverage_pct": 90.0}
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.reports.dashboard_financial_summary.get_profitability_summary", return_value=fake_result) as mock_get:
        response = client.get("/reports/financial-summary", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.close.assert_called_once()  # a read: the connection goes back, nothing to commit
    mock_get.assert_called_once_with(fake_conn, "t1", window_days=30)


def test_sales_report_passes_the_page_offset():
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.reports.dashboard_reports.get_sales_report", return_value={"rows": []}) as mock_get:
        response = client.get("/reports/sales", params={"limit": 50, "offset": 150}, headers=_auth())
    assert response.status_code == 200
    assert mock_get.call_args.kwargs["offset"] == 150
    assert client.get("/reports/sales", params={"offset": -1}, headers=_auth()).status_code == 422


_EXPORT_ROWS = [
    {"issue_date": "2026-03-02T10:00:00+00:00", "invoice_number": "INV-2", "product_name": "=HYPERLINK(\"x\")",
     "quantity": 2.0, "unit_price": 1.5, "total_price": 3.0, "line_gross_profit": None},
    {"issue_date": "2026-03-01T10:00:00+00:00", "invoice_number": "INV-1", "product_name": "Zaatar, 1 kg",
     "quantity": 1.0, "unit_price": 4.0, "total_price": 4.0, "line_gross_profit": 1.0},
]


def test_export_requires_auth():
    assert client.get("/reports/sales/export").status_code == 401


def test_csv_export_streams_every_row_with_localized_headers_and_no_formulas():
    fake_conn = MagicMock()
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.reports.usage.reserve_request", return_value=None), \
         patch("src.ai.routers.reports.dashboard_reports.iter_sales_rows", return_value=iter(_EXPORT_ROWS)):
        response = client.get("/reports/sales/export", params={"format": "csv", "lang": "ar"}, headers=_auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="keel-sales-report-' in response.headers["content-disposition"]
    import csv as _csv, io as _io
    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    rows = list(_csv.reader(_io.StringIO(text.lstrip("\ufeff"))))
    assert rows[0][0] == "التاريخ" and len(rows) == 3
    assert rows[1][2] == "'=HYPERLINK(\"x\")"      # can't run as a formula
    assert rows[2][2] == "Zaatar, 1 kg" and rows[1][6] == ""
    fake_conn.commit.assert_called_once()
    fake_conn.close.assert_called_once()


def test_json_export_is_one_valid_document():
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.reports.usage.reserve_request", return_value=None), \
         patch("src.ai.routers.reports.dashboard_reports.iter_sales_rows", return_value=iter(_EXPORT_ROWS)):
        response = client.get("/reports/sales/export", params={"format": "json"}, headers=_auth())
    body = response.json()
    assert body["total_row_count"] == 2 and body["rows"][1]["invoice_number"] == "INV-1"
    assert "generated_at" in body


def test_export_rejects_unknown_formats_and_bad_ranges():
    assert client.get("/reports/sales/export", params={"format": "xlsx"}, headers=_auth()).status_code == 422
    bad = {"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-01-01T00:00:00Z"}
    assert client.get("/reports/sales/export", params=bad, headers=_auth()).status_code == 422


def test_an_export_counts_as_one_report_and_is_given_back_if_it_fails():
    counted = {"tenant_id": "t1", "feature_code": "monthly_reports", "period_start": None, "amount": 1, "idempotency_key": "k"}
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.reports.usage.reserve_request", return_value=counted) as reserve, \
         patch("src.ai.routers.reports.usage.release_request") as release, \
         patch("src.ai.routers.reports.sales_pdf.report_data", side_effect=RuntimeError("boom")):
        failing = TestClient(app, raise_server_exceptions=False)
        assert failing.get("/reports/sales/export", params={"format": "pdf"}, headers=_auth()).status_code == 500
    reserve.assert_called_once()
    release.assert_called_once_with(counted)


def test_the_report_allowance_answers_402_when_used_up():
    from src.ai.core import usage

    used_up = usage.PlanLimitReached("QUOTA_EXHAUSTED", usage.MONTHLY_REPORTS, 5, 5, "billing_period", None)
    with patch("src.ai.routers.reports.usage.reserve_request", side_effect=used_up), \
         patch("src.ai.routers.reports.db.app_role_connection") as connect:
        response = client.get("/reports/sales/export", params={"format": "csv"}, headers=_auth())
    assert response.status_code == 402 and response.json()["detail"]["feature_code"] == "monthly_reports"
    connect.assert_not_called()  # nothing is generated


def test_a_retry_with_the_same_idempotency_key_is_the_same_report():
    from src.ai.routers import reports
    from src.ai.core.security import TenantContext

    ctx = TenantContext(tenant_id="t1", user_id="u1")
    assert reports.report_key(ctx, "retry-key-001", "csv") == reports.report_key(ctx, "retry-key-001", "pdf")
    assert reports.report_key(ctx, None, "csv", "en") == reports.report_key(ctx, None, "csv", "en")
    assert reports.report_key(ctx, None, "csv", "en") != reports.report_key(ctx, None, "pdf", "en")
    bad = client.get("/reports/sales/export", params={"format": "csv"}, headers={**_auth(), "Idempotency-Key": "bad key!"})
    assert bad.status_code == 422


def test_a_repeated_report_is_read_once_until_the_company_writes():
    """The sales report and financial summary are shared between visits
    (core/tenant_cache.py); a write by the company makes the next one fresh."""
    from src.ai.core import tenant_cache

    with patch("src.ai.routers.reports.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.reports.dashboard_reports.get_sales_report", return_value={"rows": []}) as mock_get:
        for _ in range(3):
            assert client.get("/reports/sales", headers=_auth()).status_code == 200
        assert mock_get.call_count == 1
        tenant_cache.bump("t1")
        assert client.get("/reports/sales", headers=_auth()).status_code == 200
        assert mock_get.call_count == 2
        # Another page is another report.
        assert client.get("/reports/sales", params={"offset": 1000}, headers=_auth()).status_code == 200
        assert mock_get.call_count == 3
