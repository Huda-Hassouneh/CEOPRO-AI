"""
Unit tests for src/ai/main.py - zero test coverage before this file. Auth/
security-check logic and request/response shape, all offline (DB/MinIO/
ingestion_pipeline calls mocked out) - the real end-to-end path (a real
upload landing in Postgres + MinIO) is covered separately by
test_main_integration_db.py, matching this repo's established
offline-unit/live-integration split.
"""
import os
from unittest.mock import MagicMock, patch

import jwt
import redis
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.main import app  # noqa: E402

client = TestClient(app)
_SECRET = os.environ["JWT_SECRET"]


def _token(tenant_id="t1", user_id="u1"):
    return jwt.encode({"tenant_id": tenant_id, "user_id": user_id}, _SECRET, algorithm="HS256")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_health_requires_no_auth():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_requires_auth():
    response = client.post("/extraction/upload", files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")})
    assert response.status_code == 401


def test_upload_rejects_invalid_token():
    response = client.post(
        "/extraction/upload",
        files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_upload_rejects_unsupported_extension():
    response = client.post(
        "/extraction/upload", files={"file": ("t.docx", b"whatever", "application/octet-stream")}, headers=_auth()
    )
    assert response.status_code == 400
    assert "docx" in response.json()["detail"]


def test_upload_rejects_empty_file():
    response = client.post("/extraction/upload", files={"file": ("t.csv", b"", "text/csv")}, headers=_auth())
    assert response.status_code == 400


def test_upload_rejects_oversized_file():
    with patch("src.ai.main._MAX_UPLOAD_BYTES", 10):
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"x" * 100, "text/csv")}, headers=_auth()
        )
    assert response.status_code == 413


def test_upload_rejects_content_that_does_not_match_extension():
    """Magic-byte check: a file renamed to .xlsx without real XLSX (ZIP)
    content must be rejected, not silently parsed as garbage."""
    response = client.post(
        "/extraction/upload",
        files={"file": ("t.xlsx", b"this is not a real xlsx file", "application/octet-stream")},
        headers=_auth(),
    )
    assert response.status_code == 400
    assert "extension" in response.json()["detail"]


def test_upload_accepts_a_genuine_pdf_magic_header():
    """The magic-byte check itself must not falsely reject real content -
    downstream parsing is mocked out here, only the content-sniffing gate
    is under test."""
    fake_conn = MagicMock()
    fake_summary = MagicMock(
        template_mode="FALLBACK", is_template_compliant=False, rows_processed=1, rows_partial=0,
        rows_failed=0, data_loss_pct=0.0, header_coverage_ratio=0.0, minio_object_key=None, row_outcomes=[],
    )
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.main.file_dispatch.read_source_file", return_value=(["page_text"], [{"page_text": "x"}])), \
         patch("src.ai.main.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.main.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.main.job_management.finalize_ingestion_job"), \
         patch("src.ai.main.ingestion_pipeline.process_records", return_value=fake_summary):
        response = client.post(
            "/extraction/upload",
            files={"file": ("t.pdf", b"%PDF-1.4\n...", "application/pdf")},
            headers=_auth(),
        )
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"


def test_upload_response_surfaces_compliance_and_loss_metrics():
    """The whole point of the endpoint for 'testing template ingestion
    live': the response must directly surface is_template_compliant/
    data_loss_pct/rows_partial, not just a generic success flag."""
    fake_conn = MagicMock()
    fake_summary = MagicMock(
        template_mode="TEMPLATE_COMPLIANT", is_template_compliant=False, rows_processed=1, rows_partial=1,
        rows_failed=0, data_loss_pct=20.0, header_coverage_ratio=1.0, minio_object_key="key.json",
        row_outcomes=[MagicMock(row_index=0, mode="TEMPLATE_COMPLIANT", field_errors={"quantity": "bad"}, error=None)],
    )
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.main.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.main.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.main.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.main.job_management.finalize_ingestion_job"), \
         patch("src.ai.main.ingestion_pipeline.process_records", return_value=fake_summary):
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"product_name\nx\n", "text/csv")}, headers=_auth()
        )
    body = response.json()
    assert response.status_code == 200
    assert body["is_template_compliant"] is False
    assert body["data_loss_pct"] == 20.0
    assert body["rows_partial"] == 1
    assert body["row_outcomes"][0]["field_errors"] == {"quantity": "bad"}


def test_upload_publishes_a_discovery_request_when_new_products_are_created():
    """
    The real fix (production-hardening audit): nothing in production ever
    triggered tenant_discovery.py's competitor discovery automatically -
    this is that trigger. Fires only when promote_ingested_rows() actually
    created new products, matching persistence.py's own "only publish on
    real signal" convention for market.analysis.requested.
    """
    fake_conn = MagicMock()
    fake_summary = MagicMock(
        template_mode="TEMPLATE_COMPLIANT", is_template_compliant=True, rows_processed=1, rows_partial=0,
        rows_failed=0, data_loss_pct=0.0, header_coverage_ratio=1.0, minio_object_key=None, row_outcomes=[],
    )
    fake_promotion_summary = MagicMock(
        rows_promoted=1, rows_skipped_incomplete=0, rows_failed=0, products_created=1, errors=[],
    )
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.main.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.main.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.main.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.main.job_management.finalize_ingestion_job"), \
         patch("src.ai.main.ingestion_pipeline.process_records", return_value=fake_summary), \
         patch("src.ai.main.promotion.promote_ingested_rows", return_value=fake_promotion_summary), \
         patch("src.ai.main._publish_discovery_request") as mock_publish:
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"product_name\nx\n", "text/csv")}, headers=_auth()
        )

    assert response.status_code == 200
    mock_publish.assert_called_once_with("t1")


def test_upload_does_not_publish_a_discovery_request_when_no_products_were_created():
    fake_conn = MagicMock()
    fake_summary = MagicMock(
        template_mode="TEMPLATE_COMPLIANT", is_template_compliant=True, rows_processed=1, rows_partial=0,
        rows_failed=0, data_loss_pct=0.0, header_coverage_ratio=1.0, minio_object_key=None, row_outcomes=[],
    )
    fake_promotion_summary = MagicMock(
        rows_promoted=1, rows_skipped_incomplete=0, rows_failed=0, products_created=0, errors=[],
    )
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.main.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.main.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.main.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.main.job_management.finalize_ingestion_job"), \
         patch("src.ai.main.ingestion_pipeline.process_records", return_value=fake_summary), \
         patch("src.ai.main.promotion.promote_ingested_rows", return_value=fake_promotion_summary), \
         patch("src.ai.main._publish_discovery_request") as mock_publish:
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"product_name\nx\n", "text/csv")}, headers=_auth()
        )

    assert response.status_code == 200
    mock_publish.assert_not_called()


def test_publish_discovery_request_swallows_redis_errors():
    """A Redis hiccup must never fail the upload response the user is
    already waiting on - matches persistence.py's identical convention
    for market.analysis.requested."""
    from src.ai.main import _publish_discovery_request

    with patch("src.ai.main.redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value.xadd.side_effect = redis.RedisError("boom")
        _publish_discovery_request("t1")  # must not raise


def test_upload_marks_job_failed_and_returns_500_on_unexpected_error():
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.main.file_dispatch.read_source_file", return_value=(["a"], [{"a": "1"}])), \
         patch("src.ai.main.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.main.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.main.job_management.finalize_ingestion_job") as mock_finalize, \
         patch("src.ai.main.ingestion_pipeline.process_records", side_effect=RuntimeError("boom")):
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"a\n1\n", "text/csv")}, headers=_auth()
        )
    assert response.status_code == 500
    mock_finalize.assert_called_once()
    assert mock_finalize.call_args.args[2] == "job-1"
    assert mock_finalize.call_args.args[3] == "FAILED"


def test_template_download_csv():
    response = client.get("/extraction/templates/csv", headers=_auth())
    assert response.status_code == 200
    assert b"product_name" in response.content


def test_template_download_xlsx():
    response = client.get("/extraction/templates/xlsx", headers=_auth())
    assert response.status_code == 200


def test_template_download_unknown_format_rejected():
    response = client.get("/extraction/templates/pdf", headers=_auth())
    assert response.status_code == 404


def test_template_download_requires_auth():
    response = client.get("/extraction/templates/csv")
    assert response.status_code == 401


def test_rag_query_requires_auth():
    response = client.post("/rag/query", params={"query_text": "what is our best seller?"})
    assert response.status_code == 401


def test_rag_query_returns_answer_and_sources_on_success():
    fake_conn = MagicMock()
    fake_result = {"answer": "Sunscreen SPF 50.", "sources": [{"source_index": 1, "chunk_id": "c1", "score": 0.9}]}
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.rag_llm_client.answer_query", return_value=fake_result) as mock_answer:
        response = client.post("/rag/query", params={"query_text": "what is our best seller?"}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    assert mock_answer.call_args.args[2] == "what is our best seller?"


def test_rag_query_maps_llm_provider_failure_to_502_not_500():
    """A Groq/provider failure is a distinct, more specific error than a
    generic 500 - retrieval genuinely succeeded, only the LLM call didn't."""
    from src.ai.rag import llm_client as rag_llm_client_module

    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch(
             "src.ai.main.rag_llm_client.answer_query",
             side_effect=rag_llm_client_module.LLMError("GROQ_API_KEY is not set"),
         ):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 502
    assert "GROQ_API_KEY" in response.json()["detail"]
    fake_conn.rollback.assert_called_once()


def test_rag_query_returns_500_and_rolls_back_on_unexpected_error():
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.rag_llm_client.answer_query", side_effect=RuntimeError("boom")):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 500
    fake_conn.rollback.assert_called_once()


def test_rag_query_rejects_empty_query_text():
    """min_length=1 - an empty query has nothing to retrieve or ask an LLM
    about, and would still cost a wasted retrieval pass if allowed through."""
    response = client.post("/rag/query", params={"query_text": ""}, headers=_auth())
    assert response.status_code == 422


def test_rag_query_rejects_a_query_text_over_the_length_cap():
    """2026-09-01 security review: query_text goes straight into a prompt
    sent to a paid, metered third-party API - unbounded length is a real
    cost/abuse vector, enforced here before the handler (and therefore
    before any DB connection or LLM call) ever runs."""
    from src.ai.main import _MAX_QUERY_TEXT_LENGTH

    response = client.post(
        "/rag/query", params={"query_text": "x" * (_MAX_QUERY_TEXT_LENGTH + 1)}, headers=_auth()
    )
    assert response.status_code == 422


def test_rag_query_rejects_top_k_out_of_bounds():
    response = client.post("/rag/query", params={"query_text": "q", "top_k": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.post("/rag/query", params={"query_text": "q", "top_k": 999}, headers=_auth())
    assert response.status_code == 422


def test_onboarding_status_requires_auth():
    response = client.get("/onboarding/status")
    assert response.status_code == 401


def test_onboarding_status_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"status": "not_started", "connected_methods": [], "invoice_count": 0}
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.market_scraper_data_access.get_onboarding_status", return_value=fake_result) as mock_status:
        response = client.get("/onboarding/status", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_status.assert_called_once_with(fake_conn, "t1")


def test_onboarding_connect_database_requires_auth():
    response = client.post("/onboarding/connect/database", json={
        "source_name": "My DB", "host": "h", "port": 5432, "dbname": "d",
        "query": "SELECT 1", "field_mapping": {}, "credentials": {"user": "u", "password": "p"},
    })
    assert response.status_code == 401


def test_onboarding_connect_database_rejects_missing_required_fields():
    response = client.post(
        "/onboarding/connect/database", json={"source_name": "My DB"}, headers=_auth(),
    )
    assert response.status_code == 422


def test_onboarding_connect_database_registers_a_source_on_success():
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch(
             "src.ai.main.market_scraper_data_access.register_self_service_data_source",
             return_value="new-source-id",
         ) as mock_register:
        response = client.post(
            "/onboarding/connect/database",
            json={
                "source_name": "My POS DB", "host": "db.example.com", "port": 5432, "dbname": "pos",
                "query": "SELECT * FROM sales", "field_mapping": {"a": "b"},
                "credentials": {"user": "u", "password": "p"}, "sync_frequency_minutes": 30,
            },
            headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json() == {"source_id": "new-source-id", "collector_key": "db_connector"}
    args = mock_register.call_args.args
    assert args[0] is fake_conn
    assert args[1] == "t1"
    assert args[2] == "u1"
    assert args[3] == "My POS DB"
    assert args[4] == "db_connector"
    assert args[5] == {
        "host": "db.example.com", "port": 5432, "dbname": "pos",
        "query": "SELECT * FROM sales", "field_mapping": {"a": "b"},
    }
    assert args[6] == {"user": "u", "password": "p"}
    assert args[7] == 30


def test_onboarding_connect_api_requires_auth():
    response = client.post("/onboarding/connect/api", json={
        "source_name": "My API", "base_url": "https://x.example", "field_mapping": {},
    })
    assert response.status_code == 401


def test_onboarding_connect_api_rejects_missing_required_fields():
    response = client.post("/onboarding/connect/api", json={"source_name": "My API"}, headers=_auth())
    assert response.status_code == 422


def test_onboarding_connect_api_registers_a_source_with_only_required_fields():
    """base_url/field_mapping are the only required fields - every other
    vendor-specific detail is optional and must be omitted from the
    stored config entirely when not supplied, not stored as a null."""
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch(
             "src.ai.main.market_scraper_data_access.register_self_service_data_source",
             return_value="new-source-id",
         ) as mock_register:
        response = client.post(
            "/onboarding/connect/api",
            json={"source_name": "My POS API", "base_url": "https://pos.example.com", "field_mapping": {"a": "b"}},
            headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json() == {"source_id": "new-source-id", "collector_key": "api_connector"}
    args = mock_register.call_args.args
    assert args[4] == "api_connector"
    assert args[5] == {"base_url": "https://pos.example.com", "field_mapping": {"a": "b"}}
    assert args[6] is None
    assert args[7] is None


def test_onboarding_connect_api_includes_optional_fields_when_given():
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch(
             "src.ai.main.market_scraper_data_access.register_self_service_data_source",
             return_value="new-source-id",
         ) as mock_register:
        response = client.post(
            "/onboarding/connect/api",
            json={
                "source_name": "My POS API", "base_url": "https://pos.example.com", "field_mapping": {"a": "b"},
                "records_path": "data.results", "page_size_param": "per_page", "page_size": 50,
                "credentials": {"api_key": "secret"},
            },
            headers=_auth(),
        )

    assert response.status_code == 200
    args = mock_register.call_args.args
    assert args[5] == {
        "base_url": "https://pos.example.com", "field_mapping": {"a": "b"},
        "records_path": "data.results", "page_size_param": "per_page", "page_size": 50,
    }
    assert args[6] == {"api_key": "secret"}


def test_dashboard_metrics_requires_auth():
    response = client.get("/dashboard/metrics")
    assert response.status_code == 401


def test_dashboard_metrics_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {
        "window_days": 30,
        "revenue": {"amount": 12420.0, "currency": "JOD", "change_pct": 12.0},
        "units_sold": {"units": 1482, "change_pct": 8.0},
        "transaction_growth_pct": 18.0,
        "competitors_tracked": {"count": 12, "new_this_window": 2},
    }
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.dashboard_metrics.get_dashboard_metrics", return_value=fake_result) as mock_metrics:
        response = client.get("/dashboard/metrics", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_metrics.assert_called_once_with(fake_conn, "t1", window_days=30)


def test_dashboard_metrics_accepts_a_custom_window():
    fake_conn = MagicMock()
    with patch("src.ai.main.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.main.dashboard_metrics.get_dashboard_metrics", return_value={}) as mock_metrics:
        response = client.get("/dashboard/metrics", params={"window_days": 7}, headers=_auth())

    assert response.status_code == 200
    mock_metrics.assert_called_once_with(fake_conn, "t1", window_days=7)


def test_dashboard_metrics_rejects_an_out_of_bounds_window():
    response = client.get("/dashboard/metrics", params={"window_days": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.get("/dashboard/metrics", params={"window_days": 400}, headers=_auth())
    assert response.status_code == 422
