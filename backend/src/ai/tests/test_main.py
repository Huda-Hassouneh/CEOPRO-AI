"""
Unit tests for src/ai/main.py - zero test coverage before this file. Auth/
security-check logic and request/response shape, all offline (DB/MinIO/
ingestion_pipeline calls mocked out) - the real end-to-end path (a real
upload landing in Postgres + MinIO) is covered separately by
test_main_integration_db.py, matching this repo's established
offline-unit/live-integration split.
"""
import json
import os
import random
from unittest.mock import MagicMock, patch

import jwt
import pytest
import redis
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.main import app  # noqa: E402
from src.ai.sales import quick_sale as quick_sale_module  # noqa: E402

client = TestClient(app)
# raise_server_exceptions=False: TestClient's default (True) deliberately
# re-raises an unhandled exception past the app's own registered handlers
# (so a real bug in a test surfaces directly) - which means it can never
# actually exercise core/exceptions.py's global Exception handler. This
# second client is only for the tests below that specifically verify that
# handler's real runtime behavior (the generic 500 body a real deployed
# server would actually send).
error_client = TestClient(app, raise_server_exceptions=False)
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
    with patch("src.ai.routers.extraction._MAX_UPLOAD_BYTES", 10):
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


def test_upload_rejects_a_csv_with_invalid_utf8_bytes_with_a_clean_400():
    """Real bug found live in first-customer E2E acceptance testing: CSV has
    no magic-byte check (plain text, unlike xlsx/xlsm/pdf above), so a CSV
    saved in a non-UTF-8 encoding (a common real-world export from an older
    POS/Excel setup, not just literally corrupt bytes) used to reach
    file_dispatch.read_source_file() uncaught, raise UnicodeDecodeError, and
    fall into the generic `except Exception` below - a 500 implying a server
    bug for what is really an invalid upload. Must be a clean 400, same as
    every other invalid-upload case on this endpoint.

    Legacy Windows-1256/1252/UTF-16 exports are now decoded (see
    test_extraction_adapters.py), so this uses bytes that are text in no
    encoding at all - binary content renamed to .csv."""
    binary = b"product_name,quantity\n" + random.Random(7).randbytes(3000)
    response = client.post(
        "/extraction/upload",
        files={"file": ("t.csv", binary, "text/csv")},
        headers=_auth(),
    )
    assert response.status_code == 400
    assert "utf-8" in response.json()["detail"].lower()


def test_upload_accepts_a_genuine_pdf_magic_header():
    """The magic-byte check itself must not falsely reject real content -
    downstream parsing is mocked out here, only the content-sniffing gate
    is under test."""
    fake_conn = MagicMock()
    fake_summary = MagicMock(
        template_mode="FALLBACK", is_template_compliant=False, rows_processed=1, rows_partial=0,
        rows_failed=0, data_loss_pct=0.0, header_coverage_ratio=0.0, minio_object_key=None, row_outcomes=[],
    )
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.extraction.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.extraction.file_dispatch.read_source_file", return_value=(["page_text"], [{"page_text": "x"}])), \
         patch("src.ai.routers.extraction.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.routers.extraction.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.routers.extraction.job_management.finalize_ingestion_job"), \
         patch("src.ai.routers.extraction.ingestion_pipeline.process_records", return_value=fake_summary):
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
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.extraction.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.extraction.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.routers.extraction.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.routers.extraction.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.routers.extraction.job_management.finalize_ingestion_job"), \
         patch("src.ai.routers.extraction.ingestion_pipeline.process_records", return_value=fake_summary):
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
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.extraction.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.extraction.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.routers.extraction.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.routers.extraction.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.routers.extraction.job_management.finalize_ingestion_job"), \
         patch("src.ai.routers.extraction.ingestion_pipeline.process_records", return_value=fake_summary), \
         patch("src.ai.routers.extraction.promotion.promote_ingested_rows", return_value=fake_promotion_summary), \
         patch("src.ai.routers.extraction._publish_discovery_request") as mock_publish:
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
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.extraction.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.extraction.file_dispatch.read_source_file", return_value=(["product_name"], [{"product_name": "x"}])), \
         patch("src.ai.routers.extraction.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.routers.extraction.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.routers.extraction.job_management.finalize_ingestion_job"), \
         patch("src.ai.routers.extraction.ingestion_pipeline.process_records", return_value=fake_summary), \
         patch("src.ai.routers.extraction.promotion.promote_ingested_rows", return_value=fake_promotion_summary), \
         patch("src.ai.routers.extraction._publish_discovery_request") as mock_publish:
        response = client.post(
            "/extraction/upload", files={"file": ("t.csv", b"product_name\nx\n", "text/csv")}, headers=_auth()
        )

    assert response.status_code == 200
    mock_publish.assert_not_called()


def test_publish_discovery_request_swallows_redis_errors():
    """A Redis hiccup must never fail the upload response the user is
    already waiting on - matches persistence.py's identical convention
    for market.analysis.requested."""
    from src.ai.routers.extraction import _publish_discovery_request

    with patch("src.ai.routers.extraction.redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value.xadd.side_effect = redis.RedisError("boom")
        _publish_discovery_request("t1")  # must not raise


def test_upload_marks_job_failed_and_returns_500_on_unexpected_error():
    fake_conn = MagicMock()
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.extraction.db.minio_client", return_value=MagicMock()), \
         patch("src.ai.routers.extraction.file_dispatch.read_source_file", return_value=(["a"], [{"a": "1"}])), \
         patch("src.ai.routers.extraction.job_management.resolve_or_create_data_source", return_value="src-1"), \
         patch("src.ai.routers.extraction.job_management.create_ingestion_job", return_value="job-1"), \
         patch("src.ai.routers.extraction.job_management.finalize_ingestion_job") as mock_finalize, \
         patch("src.ai.routers.extraction.ingestion_pipeline.process_records", side_effect=RuntimeError("boom")):
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
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.rag_advisor.answer", return_value=fake_result) as mock_answer, \
         patch("src.ai.routers.rag.conversation_store.create_session", return_value="sess-1") as mock_create_session, \
         patch("src.ai.routers.rag.conversation_store.append_message") as mock_append_message:
        response = client.post("/rag/query", params={"query_text": "what is our best seller?"}, headers=_auth())

    assert response.status_code == 200
    # No session_id was passed in, so a brand-new persisted session is
    # created and its id comes back in the response - the one real,
    # deterministic id a frontend needs to remember for the next turn.
    assert response.json() == {**fake_result, "session_id": "sess-1"}
    # Three commits: the reserved token estimate, the answer, then the
    # allowance settled to the tokens really used.
    assert fake_conn.commit.call_count == 3
    mock_create_session.assert_called_once_with(fake_conn, "t1", "u1", "what is our best seller?")
    # Both the user's question and the assistant's answer (with its
    # sources) are persisted - conversation history is a two-sided record,
    # not just the answers.
    assert mock_append_message.call_count == 2
    assert mock_append_message.call_args_list[0].args[4:6] == ("user", "what is our best seller?")
    assert mock_append_message.call_args_list[1].args[4:6] == ("assistant", "Sunscreen SPF 50.")
    assert mock_answer.call_args.args[2] == "what is our best seller?"


def test_rag_query_passes_token_usage_through_to_the_http_response():
    """The endpoint returns answer_query()'s dict verbatim, merged with
    session_id (main.py never reshapes the answer/sources/token_usage
    keys) - this pins that token_usage survives that pass-through
    unmodified, since it's what the caller needs to compute the real
    cost of this RAG call against the provider's per-token pricing."""
    fake_conn = MagicMock()
    fake_result = {
        "answer": "Sunscreen SPF 50.",
        "sources": [{"source_index": 1, "chunk_id": "c1", "score": 0.9}],
        "token_usage": {"prompt_tokens": 342, "completion_tokens": 58, "total_tokens": 400},
    }
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.rag_advisor.answer", return_value=fake_result), \
         patch("src.ai.routers.rag.conversation_store.create_session", return_value="sess-1"), \
         patch("src.ai.routers.rag.conversation_store.append_message"):
        response = client.post("/rag/query", params={"query_text": "what is our best seller?"}, headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["token_usage"] == {"prompt_tokens": 342, "completion_tokens": 58, "total_tokens": 400}
    assert body["answer"] == "Sunscreen SPF 50."
    assert body["sources"] == fake_result["sources"]
    assert body["session_id"] == "sess-1"


def test_rag_query_maps_llm_provider_failure_to_502_not_500():
    """A Groq/provider failure is a distinct, more specific error than a
    generic 500 - retrieval genuinely succeeded, only the LLM call didn't."""
    from src.ai.rag import llm_client as rag_llm_client_module

    fake_conn = MagicMock()
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.usage.release") as mock_release, \
         patch(
             "src.ai.routers.rag.rag_advisor.answer",
             side_effect=rag_llm_client_module.LLMError("GROQ_API_KEY is not set"),
         ):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 502
    assert response.headers["x-assistant-reason"] == "provider_unavailable"
    # Provider/configuration details stay in the server log, not the response.
    assert "GROQ_API_KEY" not in response.json()["detail"]
    assert "temporarily unavailable" in response.json()["detail"]
    fake_conn.rollback.assert_called()
    # No answer was produced, so the reserved question is given back.
    mock_release.assert_called_once()


def test_rag_query_says_when_no_language_model_is_configured():
    """Missing provider key is an operator problem: the chat must say so
    (reason not_configured) instead of "try again"."""
    from src.ai.rag import llm_client as rag_llm_client_module

    fake_conn = MagicMock()
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.usage.release") as mock_release, \
         patch(
             "src.ai.routers.rag.rag_advisor.answer",
             side_effect=rag_llm_client_module.LLMNotConfiguredError("GROQ_API_KEY is not set"),
         ):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 503
    assert response.headers["x-assistant-reason"] == "not_configured"
    assert "GROQ_API_KEY" not in response.json()["detail"]
    assert "not set up" in response.json()["detail"]
    mock_release.assert_called_once()


def test_rag_query_maps_provider_rate_limit_to_503_with_retry_after_and_no_provider_details():
    from src.ai.rag import llm_client as rag_llm_client_module

    fake_conn = MagicMock()
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.usage.release") as mock_release, \
         patch(
             "src.ai.routers.rag.rag_advisor.answer",
             side_effect=rag_llm_client_module.LLMRateLimitError("429 for organization org_123", 12.4),
         ):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 503
    assert response.headers["retry-after"] == "12"
    assert response.headers["x-assistant-reason"] == "provider_busy"
    assert "org_123" not in response.json()["detail"]
    assert "about 12 seconds" in response.json()["detail"]
    fake_conn.rollback.assert_called()
    # No answer was produced, so the reserved question is given back.
    mock_release.assert_called_once()


def test_rag_query_returns_500_and_rolls_back_on_unexpected_error():
    fake_conn = MagicMock()
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.usage.release") as mock_release, \
         patch("src.ai.routers.rag.rag_advisor.answer", side_effect=RuntimeError("boom")):
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 500
    fake_conn.rollback.assert_called()
    # No answer was produced, so the reserved question is given back.
    mock_release.assert_called_once()


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
    from src.ai.routers.rag import _MAX_QUERY_TEXT_LENGTH

    response = client.post(
        "/rag/query", params={"query_text": "x" * (_MAX_QUERY_TEXT_LENGTH + 1)}, headers=_auth()
    )
    assert response.status_code == 422


def test_rag_query_rejects_top_k_out_of_bounds():
    response = client.post("/rag/query", params={"query_text": "q", "top_k": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.post("/rag/query", params={"query_text": "q", "top_k": 999}, headers=_auth())
    assert response.status_code == 422


def test_rag_query_passes_parsed_history_through_to_answer_query():
    """The real fix: without a way to send prior turns back in, every call
    was answered with zero memory of the conversation so far - a real
    conversational assistant needs the caller's own running chat log."""
    fake_conn = MagicMock()
    fake_result = {"answer": "Sunscreen SPF 50.", "sources": []}
    history = [
        {"role": "user", "content": "what's our best seller?"},
        {"role": "assistant", "content": "Sunscreen SPF 50."},
    ]
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.rag_advisor.answer", return_value=fake_result) as mock_answer:
        response = client.post(
            "/rag/query",
            params={"query_text": "why is that?", "history_json": json.dumps(history)},
            headers=_auth(),
        )

    assert response.status_code == 200
    assert mock_answer.call_args.kwargs["history"] == history


def test_rag_query_treats_a_missing_history_json_as_no_history():
    fake_conn = MagicMock()
    fake_result = {"answer": "ok", "sources": []}
    with patch("src.ai.routers.rag.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.rag.rag_advisor.answer", return_value=fake_result) as mock_answer:
        response = client.post("/rag/query", params={"query_text": "q"}, headers=_auth())

    assert response.status_code == 200
    assert mock_answer.call_args.kwargs["history"] is None


def test_rag_query_rejects_malformed_history_json():
    response = client.post(
        "/rag/query", params={"query_text": "q", "history_json": "{not valid json"}, headers=_auth(),
    )
    assert response.status_code == 422


def test_rag_query_rejects_history_json_that_is_not_an_array():
    response = client.post(
        "/rag/query", params={"query_text": "q", "history_json": json.dumps({"role": "user"})}, headers=_auth(),
    )
    assert response.status_code == 422


def test_rag_query_rejects_history_json_over_the_length_cap():
    from src.ai.routers.rag import _MAX_HISTORY_JSON_LENGTH

    oversized = json.dumps([{"role": "user", "content": "x" * _MAX_HISTORY_JSON_LENGTH}])
    response = client.post(
        "/rag/query", params={"query_text": "q", "history_json": oversized}, headers=_auth(),
    )
    assert response.status_code == 422


def test_onboarding_status_requires_auth():
    response = client.get("/onboarding/status")
    assert response.status_code == 401


def test_onboarding_status_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"status": "not_started", "connected_methods": [], "invoice_count": 0}
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding.market_scraper_data_access.get_onboarding_status", return_value=fake_result) as mock_status, \
         patch("src.ai.routers.onboarding.price_coverage.get_barcode_summary", return_value={"products": 4, "with_barcode": 1, "coverage_pct": 25.0}):
        response = client.get("/onboarding/status", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {**fake_result, "barcodes": {"products": 4, "with_barcode": 1, "coverage_pct": 25.0}}
    fake_conn.commit.assert_called_once()
    mock_status.assert_called_once_with(fake_conn, "t1")


def test_onboarding_status_survives_a_failure_computing_the_barcode_hint():
    fake_conn = MagicMock()
    fake_result = {"status": "connected", "connected_methods": [], "invoice_count": 3}
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding.market_scraper_data_access.get_onboarding_status", return_value=fake_result), \
         patch("src.ai.routers.onboarding.price_coverage.get_barcode_summary", side_effect=RuntimeError("db")):
        response = client.get("/onboarding/status", headers=_auth())
    assert response.status_code == 200 and response.json() == fake_result


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
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding._require_admin"), \
         patch(
             "src.ai.routers.onboarding.market_scraper_data_access.register_self_service_data_source",
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
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding._require_admin"), \
         patch(
             "src.ai.routers.onboarding.market_scraper_data_access.register_self_service_data_source",
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
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding._require_admin"), \
         patch(
             "src.ai.routers.onboarding.market_scraper_data_access.register_self_service_data_source",
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
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_metrics.get_dashboard_metrics", return_value=fake_result) as mock_metrics:
        response = client.get("/dashboard/metrics", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_metrics.assert_called_once_with(fake_conn, "t1", window_days=30)


def test_dashboard_metrics_accepts_a_custom_window():
    fake_conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_metrics.get_dashboard_metrics", return_value={}) as mock_metrics:
        response = client.get("/dashboard/metrics", params={"window_days": 7}, headers=_auth())

    assert response.status_code == 200
    mock_metrics.assert_called_once_with(fake_conn, "t1", window_days=7)


def test_dashboard_metrics_rejects_an_out_of_bounds_window():
    response = client.get("/dashboard/metrics", params={"window_days": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.get("/dashboard/metrics", params={"window_days": 400}, headers=_auth())
    assert response.status_code == 422


def test_dashboard_recommendations_requires_auth():
    response = client.get("/dashboard/recommendations")
    assert response.status_code == 401


def test_dashboard_recommendations_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = [{"product_id": "p1", "category": "Pricing", "priority": "high", "message": "..."}]
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_recommendations.get_top_recommendations", return_value=fake_result) as mock_recs:
        response = client.get("/dashboard/recommendations", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"recommendations": fake_result}
    fake_conn.commit.assert_called_once()
    mock_recs.assert_called_once_with(fake_conn, "t1", limit=3)


def test_dashboard_recommendations_accepts_a_custom_limit():
    fake_conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_recommendations.get_top_recommendations", return_value=[]) as mock_recs:
        response = client.get("/dashboard/recommendations", params={"limit": 5}, headers=_auth())

    assert response.status_code == 200
    mock_recs.assert_called_once_with(fake_conn, "t1", limit=5)


def test_dashboard_recommendations_rejects_an_out_of_bounds_limit():
    response = client.get("/dashboard/recommendations", params={"limit": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.get("/dashboard/recommendations", params={"limit": 21}, headers=_auth())
    assert response.status_code == 422


def test_dashboard_forecast_requires_auth():
    response = client.get("/dashboard/forecast")
    assert response.status_code == 401


def test_dashboard_forecast_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"total_predicted_units": 40, "products_forecasted": 2, "forecast_target_date": "2026-09-19"}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_forecast.get_forecast_summary", return_value=fake_result) as mock_forecast:
        response = client.get("/dashboard/forecast", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_forecast.assert_called_once_with(fake_conn, "t1")


def test_dashboard_competitor_pricing_requires_auth():
    response = client.get("/dashboard/competitor-pricing")
    assert response.status_code == 401


def test_dashboard_competitor_pricing_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = [{"product_id": "p1", "product_name": "Widget", "currency": "JOD",
                     "your_price": 120.0, "market_average_price": 100.0, "price_gap_pct": 20.0,
                     "competitors_compared": 1}]
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_competitor_pricing.get_competitor_price_positioning", return_value=fake_result) as mock_pricing:
        response = client.get("/dashboard/competitor-pricing", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"products": fake_result}
    fake_conn.commit.assert_called_once()
    mock_pricing.assert_called_once_with(fake_conn, "t1", limit=10)


def test_dashboard_competitor_pricing_accepts_a_custom_limit():
    fake_conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_competitor_pricing.get_competitor_price_positioning", return_value=[]) as mock_pricing:
        response = client.get("/dashboard/competitor-pricing", params={"limit": 5}, headers=_auth())

    assert response.status_code == 200
    mock_pricing.assert_called_once_with(fake_conn, "t1", limit=5)


def test_dashboard_competitor_pricing_rejects_an_out_of_bounds_limit():
    response = client.get("/dashboard/competitor-pricing", params={"limit": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.get("/dashboard/competitor-pricing", params={"limit": 51}, headers=_auth())
    assert response.status_code == 422


def test_dashboard_competitors_requires_auth():
    response = client.get("/dashboard/competitors")
    assert response.status_code == 401


def test_dashboard_competitors_returns_the_directory_result():
    fake_conn = MagicMock()
    fake_result = {
        "strategic": [{"name": "SparkFun Electronics", "tier": "STRATEGIC",
                        "website_url": "https://sparkfun.com", "overlap_pct": 75.0}],
        "relevant": [{"name": "PiShop US", "tier": "RELEVANT", "website_url": None,
                       "price_comparisons": []}],
    }
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_competitors.get_competitor_directory", return_value=fake_result) as mock_directory:
        response = client.get("/dashboard/competitors", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    # default request == original behaviour: no opt-ins, no filters, no paging
    mock_directory.assert_called_once_with(
        fake_conn, "t1", separate_weak_leads=False, min_confidence=None, max_distance_km=None, limit=None, offset=0,
    )


def test_dashboard_competitors_forwards_the_optional_filters_and_paging():
    fake_conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_competitors.get_competitor_directory", return_value={}) as mock_directory:
        response = client.get(
            "/dashboard/competitors?separate_weak_leads=true&min_confidence=40&max_distance_km=12.5&limit=10&offset=5",
            headers=_auth(),
        )
    assert response.status_code == 200
    mock_directory.assert_called_once_with(
        fake_conn, "t1", separate_weak_leads=True, min_confidence=40.0, max_distance_km=12.5, limit=10, offset=5,
    )


@pytest.mark.parametrize("query", ["min_confidence=101", "min_confidence=-1", "max_distance_km=-3", "limit=0", "limit=501", "offset=-1"])
def test_dashboard_competitors_validates_its_query_parameters(query):
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=MagicMock()):
        response = client.get(f"/dashboard/competitors?{query}", headers=_auth())
    assert response.status_code == 422


def test_reclassify_competitors_requires_auth():
    assert client.post("/competitors/reclassify").status_code == 401


def test_reclassify_competitors_refreshes_only_the_callers_tenant():
    fake_conn = MagicMock()
    summary = {"reclassified": 3, "by_tier": {"STRATEGIC": 1, "RELEVANT": 1, "CANDIDATE": 1}, "demoted_to_candidate": 1, "names_repaired": 0}
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn) as mock_connect, \
         patch("src.ai.routers.competitors.market_scraper_discovery.refresh_tenant_competitors", return_value=summary) as mock_refresh:
        response = client.post("/competitors/reclassify", headers=_auth())
    assert response.status_code == 200 and response.json() == summary
    mock_refresh.assert_called_once_with(fake_conn, "t1")
    assert mock_connect.call_args.args[0] == "t1"
    fake_conn.commit.assert_called_once()


def test_reclassify_competitors_rolls_back_and_closes_on_failure():
    fake_conn = MagicMock()
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.market_scraper_discovery.refresh_tenant_competitors", side_effect=RuntimeError("boom")):
        failing_client = TestClient(app, raise_server_exceptions=False)
        response = failing_client.post("/competitors/reclassify", headers=_auth())
    assert response.status_code == 500
    fake_conn.rollback.assert_called_once()
    fake_conn.close.assert_called_once()


def test_dashboard_market_overview_requires_auth():
    response = client.get("/dashboard/market-overview")
    assert response.status_code == 401


def test_dashboard_market_overview_returns_the_overview_result():
    fake_conn = MagicMock()
    fake_result = {
        "price_trend": {"direction": "Up", "increases": 3, "decreases": 1},
        "sentiment": {"label": "Bullish", "positive_pct": 80.0, "competitors_with_sentiment": 5},
        "category_activity": {"Electronics": "High"},
    }
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_market_overview.get_market_overview", return_value=fake_result) as mock_overview:
        response = client.get("/dashboard/market-overview", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_overview.assert_called_once_with(fake_conn, "t1")


def test_dashboard_activity_requires_auth():
    response = client.get("/dashboard/activity")
    assert response.status_code == 401


def test_dashboard_activity_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = [{"activity_type": "PRODUCT_ADDED", "title": "Product Added", "detail": "Widget",
                     "status": None, "occurred_at": "2026-09-08T10:24:00+00:00"}]
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_activity.get_recent_activity", return_value=fake_result) as mock_activity:
        response = client.get("/dashboard/activity", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"activity": fake_result}
    mock_activity.assert_called_once_with(fake_conn, "t1", limit=10)


def test_dashboard_competitor_activity_requires_auth():
    response = client.get("/dashboard/competitor-activity")
    assert response.status_code == 401


def test_dashboard_competitor_activity_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = [{"competitor_name": "Umniah", "product_name": "Widget", "latest_price": 90.0,
                     "prior_price": 100.0, "currency": "JOD", "price_change_pct": -10.0,
                     "direction": "decrease", "observed_at": "2026-09-08T10:24:00+00:00"}]
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_competitor_activity.get_recent_competitor_price_changes", return_value=fake_result) as mock_changes:
        response = client.get("/dashboard/competitor-activity", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"changes": fake_result}
    mock_changes.assert_called_once_with(fake_conn, "t1", limit=10)


def test_dashboard_price_competitiveness_requires_auth():
    response = client.get("/dashboard/price-competitiveness")
    assert response.status_code == 401


def test_dashboard_price_competitiveness_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"score": 7.8, "change": -0.4}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_price_competitiveness.get_price_competitiveness", return_value=fake_result) as mock_score:
        response = client.get("/dashboard/price-competitiveness", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_score.assert_called_once_with(fake_conn, "t1")


def test_dashboard_inventory_requires_auth():
    response = client.get("/dashboard/inventory")
    assert response.status_code == 401


def test_dashboard_inventory_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"has_data": False, "in_stock_pct": None, "low_stock_count": None, "tracked_products": 0}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_inventory.get_inventory_status", return_value=fake_result) as mock_status:
        response = client.get("/dashboard/inventory", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_status.assert_called_once_with(fake_conn, "t1")


def test_dashboard_search_requires_auth():
    response = client.get("/dashboard/search", params={"q": "widget"})
    assert response.status_code == 401


def test_dashboard_search_requires_a_query_param():
    response = client.get("/dashboard/search", headers=_auth())
    assert response.status_code == 422


def test_dashboard_search_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"products": [{"product_id": "p1", "name": "Widget"}], "competitors": []}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_search.search", return_value=fake_result) as mock_search:
        response = client.get("/dashboard/search", params={"q": "widget"}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_search.assert_called_once_with(fake_conn, "t1", "widget", limit=10)


def test_dashboard_forecast_movers_requires_auth():
    response = client.get("/dashboard/forecast-movers")
    assert response.status_code == 401


def test_dashboard_forecast_movers_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"products_forecasted": 1, "increasing_count": 1, "decreasing_count": 0,
                    "stable_count": 0, "top_increasing": [], "top_decreasing": []}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_forecast_movers.get_forecast_movers", return_value=fake_result) as mock_movers:
        response = client.get("/dashboard/forecast-movers", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_movers.assert_called_once_with(fake_conn, "t1", limit=5)


def test_dashboard_inventory_recommendations_requires_auth():
    response = client.get("/dashboard/inventory-recommendations")
    assert response.status_code == 401


def test_dashboard_inventory_recommendations_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"restock_now_count": 1, "reduce_order_count": 0, "monitor_count": 0, "recommendations": []}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_inventory_recommendations.get_inventory_recommendations", return_value=fake_result) as mock_recs:
        response = client.get("/dashboard/inventory-recommendations", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_recs.assert_called_once_with(fake_conn, "t1", limit=20)


def test_dashboard_product_forecast_requires_auth():
    response = client.get("/dashboard/products/p1/forecast")
    assert response.status_code == 401


def test_dashboard_product_forecast_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"product_id": "p1", "product_name": "Widget", "current_stock": 620}
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_forecast_detail.get_product_forecast_detail", return_value=fake_result) as mock_detail:
        response = client.get("/dashboard/products/p1/forecast", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_detail.assert_called_once_with(fake_conn, "t1", "p1")


def test_dashboard_product_forecast_returns_404_for_a_missing_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.dashboard.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.dashboard.dashboard_forecast_detail.get_product_forecast_detail", return_value=None):
        response = client.get("/dashboard/products/missing/forecast", headers=_auth())

    assert response.status_code == 404


def test_quick_sale_requires_auth():
    response = client.post("/sales/quick-sale", json={"product_id": "p1", "quantity": 1})
    assert response.status_code == 401


def test_quick_sale_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"invoice_id": "i1", "invoice_number": "QS-ABC", "product_id": "p1",
                   "product_name": "Widget", "quantity": 2, "unit_price": 10.0,
                   "total_amount": 20.0, "currency": "JOD"}
    with patch("src.ai.routers.sales.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.sales.quick_sale.record_quick_sale", return_value=fake_result) as mock_sale:
        response = client.post("/sales/quick-sale", json={"product_id": "p1", "quantity": 2}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_sale.assert_called_once_with(fake_conn, "t1", "u1", "p1", 2, None)


def test_quick_sale_returns_404_for_a_missing_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.sales.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.sales.quick_sale.record_quick_sale",
               side_effect=quick_sale_module.ProductNotFoundError("no such product")):
        response = client.post("/sales/quick-sale", json={"product_id": "missing", "quantity": 1}, headers=_auth())

    assert response.status_code == 404


def test_add_competitor_requires_auth():
    response = client.post("/competitors", json={"name": "Rival", "website_url": "https://rival.example"})
    assert response.status_code == 401


def test_add_competitor_returns_the_pipeline_result():
    fake_conn = MagicMock()
    fake_result = {"competitor_id": "c1", "competitor_name": "Rival Co", "website_url": "https://rival.example",
                   "is_manufacturer": False, "is_confirmed_competitor": True, "tier": "STRATEGIC",
                   "classification_reason": "confirmed"}
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.market_scraper_discovery.register_manual_competitor", return_value=fake_result) as mock_add:
        response = client.post(
            "/competitors", json={"name": "Rival Co", "website_url": "https://rival.example"}, headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_add.assert_called_once_with(fake_conn, "t1", "Rival Co", "https://rival.example")


@pytest.mark.parametrize("body", [
    {"name": "", "website_url": "https://rival.example"},
    {"name": "   ", "website_url": "https://rival.example"},
    {"name": "Rival", "website_url": "not a url"},
    {"name": "Rival", "website_url": "ftp://rival.example"},
    {"name": "Rival", "website_url": "https://localhost"},
    {"name": "Rival", "website_url": ""},
])
def test_add_competitor_rejects_a_blank_name_or_a_non_web_address(body):
    with patch("src.ai.routers.competitors.market_scraper_discovery.register_manual_competitor") as mock_add:
        response = client.post("/competitors", json=body, headers=_auth())
    assert response.status_code == 422
    mock_add.assert_not_called()


def test_add_competitor_accepts_a_bare_domain_as_typed():
    fake_conn = MagicMock()
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.market_scraper_discovery.register_manual_competitor", return_value={"competitor_id": "c1"}) as mock_add:
        response = client.post("/competitors", json={"name": "  Rival   Co ", "website_url": " www.rival.jo/shop "}, headers=_auth())
    assert response.status_code == 200
    mock_add.assert_called_once_with(fake_conn, "t1", "Rival Co", "https://www.rival.jo/shop")


def test_list_competitors_requires_auth():
    response = client.get("/competitors")
    assert response.status_code == 401


def test_list_competitors_flattens_and_sorts_both_tiers_by_name():
    fake_conn = MagicMock()
    fake_directory = {
        "strategic": [{"id": "c2", "name": "Zebra Corp", "tier": "STRATEGIC", "overlap_pct": 80.0}],
        "relevant": [{"id": "c1", "name": "Acme Inc", "tier": "RELEVANT", "price_comparisons": []}],
    }
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.dashboard_competitors.get_competitor_directory", return_value=fake_directory) as mock_directory:
        response = client.get("/competitors", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"competitors": [fake_directory["relevant"][0], fake_directory["strategic"][0]]}
    fake_conn.commit.assert_called_once()
    mock_directory.assert_called_once_with(fake_conn, "t1")


def test_list_competitors_can_be_ordered_by_confidence_on_request():
    fake_conn = MagicMock()
    fake_directory = {
        "strategic": [{"id": "c2", "name": "Zebra Corp", "tier": "STRATEGIC", "confidence_score": 90.0}],
        "relevant": [{"id": "c1", "name": "Acme Inc", "tier": "RELEVANT", "confidence_score": 40.0},
                     {"id": "c3", "name": "Unscored Ltd", "tier": "RELEVANT"}],  # rows from older callers carry no score
    }
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.dashboard_competitors.get_competitor_directory", return_value=fake_directory):
        response = client.get("/competitors?sort=confidence", headers=_auth())
    assert response.status_code == 200
    assert [c["name"] for c in response.json()["competitors"]] == ["Zebra Corp", "Acme Inc", "Unscored Ltd"]


def test_list_competitors_rejects_an_unknown_sort():
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=MagicMock()):
        assert client.get("/competitors?sort=bogus", headers=_auth()).status_code == 422


def test_list_competitors_returns_an_empty_list_with_no_tracked_competitors():
    fake_conn = MagicMock()
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.competitors.dashboard_competitors.get_competitor_directory",
               return_value={"strategic": [], "relevant": []}):
        response = client.get("/competitors", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"competitors": []}


# ---------------------------------------------------------------------------
# CORS (production-hardening pass) - real browser origins allowed to call
# this API. Verifies the middleware itself is actually wired in, not just
# that individual endpoints still work when called directly (TestClient
# doesn't enforce CORS from JavaScript the way a real browser does - these
# tests check the response headers CORSMiddleware adds, which is the real
# server-side behavior a browser's own CORS check depends on).
# ---------------------------------------------------------------------------

def test_cors_allows_the_default_dev_frontend_origin():
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_preflight_allows_the_authorization_header():
    response = client.options(
        "/dashboard/metrics",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_an_unlisted_origin():
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Global exception handling (production-hardening pass) - a truly
# unexpected exception (not one an endpoint already anticipated and
# wrapped in its own HTTPException) must never leak its real message/
# traceback to the caller, and must always come back in the same
# {"detail": ...} shape every other error response already uses.
# ---------------------------------------------------------------------------

def test_unhandled_exception_returns_a_generic_500_not_a_leaked_message():
    """/pricing/recommend re-raises unwrapped on an unexpected failure
    (`except Exception: conn.rollback(); raise`) - a real, existing
    endpoint that never anticipated this specific failure, exactly the
    case the global handler exists for."""
    fake_conn = MagicMock()
    with patch("src.ai.routers.pricing.db.app_role_connection", return_value=fake_conn), \
         patch(
             "src.ai.routers.pricing.pricing_pipeline.run_price_recommendation",
             side_effect=RuntimeError("some internal detail that must never reach the caller"),
         ):
        response = error_client.post("/pricing/recommend", params={"product_id": "p1"}, headers=_auth())

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert "internal detail" not in response.text
    fake_conn.rollback.assert_called_once()


def test_validation_error_from_a_custom_field_validator_serializes_as_a_real_422():
    """Real bug this guards against: a Pydantic v2 @field_validator that
    raises a plain ValueError (e.g. routers/products.py's product_name-
    requires-"en"-key check) makes RequestValidationError.errors() embed
    the original ValueError OBJECT under ctx.error, not a string - passing
    that straight to JSONResponse's stdlib json.dumps used to raise
    TypeError: Object of type ValueError is not JSON serializable,
    silently turning an intended 422 into an unhandled 500 (caught by
    core/exceptions.py's own generic handler, which would still return a
    500 rather than genuinely crash the request - but never the honest
    422 the caller's own bad input actually deserves). core/exceptions.py's
    _validation_exception_handler now runs exc.errors() through FastAPI's
    own jsonable_encoder() first - this exercises that fix against the
    exact endpoint/validator that first surfaced it, using the real
    (non-mocked) TestClient so the real exception handler actually runs."""
    response = client.post(
        "/products",
        json={"product_name": {"ar": "ودجت"}, "current_price": 10.0, "currency": "JOD"},
        headers=_auth(),
    )
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    # The ctx.error field (if present) must now be a plain string, not an
    # unserializable exception object - the whole response already being
    # valid JSON proves this, but this asserts the specific field directly.
    for error in body["detail"]:
        ctx_error = error.get("ctx", {}).get("error")
        if ctx_error is not None:
            assert isinstance(ctx_error, str)



def test_api_responses_carry_baseline_security_headers():
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["content-security-policy"].startswith("default-src 'none'")


def test_security_headers_apply_to_errors_too_but_not_the_api_docs():
    assert "content-security-policy" in client.get("/no-such-route").headers
    # Swagger UI loads its assets from a CDN; the API's lock-down CSP would break it.
    docs = client.get("/docs")
    assert docs.status_code == 200 and "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "DENY"


def test_onboarding_connect_is_refused_for_non_admin_members():
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("staff",)
    with patch("src.ai.routers.onboarding.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.onboarding.market_scraper_data_access.register_self_service_data_source") as mock_register:
        response = client.post("/onboarding/connect/api", json={"source_name": "POS", "base_url": "https://pos.example.com/api",
                                                                 "field_mapping": {"a": "b"}}, headers=_auth())
    assert response.status_code == 403
    mock_register.assert_not_called()


def test_an_exhausted_database_pool_answers_503_with_retry_after():
    import psycopg2.pool
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ai.core.exceptions import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/busy")
    def busy():
        raise psycopg2.pool.PoolError("connection pool exhausted")

    response = TestClient(app, raise_server_exceptions=False).get("/busy")
    assert response.status_code == 503 and response.headers["Retry-After"] == "5"


def test_readiness_reports_each_dependency_and_503_when_one_is_down(monkeypatch):
    from fastapi.testclient import TestClient

    from src.ai.main import app
    from src.ai.routers import health

    monkeypatch.setattr(health, "_database", lambda: None)
    monkeypatch.setattr(health, "_redis", lambda: None)
    ok = TestClient(app).get("/health/ready")
    assert ok.status_code == 200 and ok.json()["checks"]["database"]["ok"] is True

    def down():
        raise ConnectionError("refused")

    monkeypatch.setattr(health, "_redis", down)
    failing = TestClient(app).get("/health/ready")
    assert failing.status_code == 503
    assert failing.json()["checks"]["redis"] == {"ok": False, "ms": failing.json()["checks"]["redis"]["ms"], "error": "ConnectionError"}
    assert "refused" not in failing.text, "error details stay in the server log"
