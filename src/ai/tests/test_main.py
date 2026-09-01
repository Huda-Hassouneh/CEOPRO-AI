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
