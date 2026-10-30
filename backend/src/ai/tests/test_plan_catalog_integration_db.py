"""
The agreed plan terms against the real database: every plan includes market
intelligence, demand forecasting and competitor tracking; plans differ by
capacity. The assistant is metered in tokens; review analysis, document
processing, tracked competitors and connected data sources respect each
company's own allowance; a new billing period starts from zero.
"""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

from src.ai.core import entitlements, usage
from src.ai.tests.signup_helpers import create_verified_test_account

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
    reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set - skipping live-DB plan catalog test",
)

# These tests store real objects, so they need MinIO as well as Postgres (CI has no MinIO service).
requires_minio = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")),
    reason="MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD not set - skipping MinIO-backed test",
)


@pytest.fixture
def client():
    from src.ai.main import app

    return TestClient(app)


def _admin(sql, params=()):
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall() if cursor.description else None
    conn.close()
    return rows


def _company(client, plan_key):
    email = f"plan+{uuid.uuid4().hex[:8]}@example.com"
    session = create_verified_test_account(client, {"full_name": "Owner", "business_name": "Plan Co", "email": email,
                                                     "country_code": "JO", "primary_currency": "JOD",
                                                     "password": "Plan!Catalog-2026"})
    _admin("UPDATE tenant_plan_assignments SET plan_key = %s, status = 'active', source = 'manual' WHERE tenant_id = %s;",
           (plan_key, session["tenant_id"]))
    entitlements.forget(session["tenant_id"])
    return session, {"Authorization": f"Bearer {session['access_token']}"}


@pytest.mark.parametrize("plan_key", ["starter", "growth", "enterprise"])
def test_every_plan_includes_the_core_intelligence(client, plan_key):
    _, headers = _company(client, plan_key)
    for path, params in (("/discovery/competitors", None), ("/competitors", None), ("/forecasting/overview", None),
                         ("/mpi/summary", {"subject_type": "BUSINESS"}), ("/sentiment/summary", {"subject_type": "BUSINESS"}),
                         ("/products", None), ("/reports/sales", None), ("/dashboard/command-center", None)):
        assert client.get(path, params=params, headers=headers).status_code == 200, (plan_key, path)
    subscription = client.get("/billing/subscription", headers=headers).json()
    assert subscription["planId"] == plan_key
    assert {"market_intelligence", "demand_prediction", "competitor_management"} <= set(subscription["entitlements"])
    # Only the plan terms customers see - no internal budgets under raw codes.
    assert set(subscription["limits"]) == {"products", "reports", "teamSeats", "dataCredits", "aiCredits", "imageGenerations",
                                           "storageGb", "documentProcessingMb", "sentimentRecords", "dataSources"}
    assert set(subscription["credits"]) >= {"data", "ai"}


@pytest.mark.parametrize("plan_key", ["starter", "growth", "enterprise"])
def test_competitors_have_no_fixed_count(client, plan_key):
    """Competitor tracking is limited by the Data Credit budget, not a count."""
    session, _ = _company(client, plan_key)
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        assert usage.get_plan(conn, session["tenant_id"])["features"]["tracked_competitors"]["limit"] is None
        assert usage.capacity_left(conn, session["tenant_id"], usage.TRACKED_COMPETITORS) is None
    finally:
        conn.close()


@pytest.mark.parametrize("plan_key, cap", [("standard", 15), ("pro", 60)])
def test_retired_packages_keep_their_competitor_cap(client, plan_key, cap):
    session, _ = _company(client, plan_key)
    tenant = session["tenant_id"]
    _admin(
        """
        WITH g AS (
            INSERT INTO global_competitors (competitor_name)
            SELECT 'Cap test competitor ' || n || ' ' || %s FROM generate_series(1, %s) AS n
            RETURNING global_competitor_id
        )
        INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked)
        SELECT %s, global_competitor_id, TRUE FROM g;
        """, (tenant, cap - 1, tenant))
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        usage.ensure_capacity(conn, tenant, usage.TRACKED_COMPETITORS)  # cap - 1 tracked: one more fits
        _admin("""
            WITH g AS (INSERT INTO global_competitors (competitor_name) VALUES ('Cap test last ' || %s) RETURNING global_competitor_id)
            INSERT INTO tenant_competitors (tenant_id, global_competitor_id, is_tracked) SELECT %s, global_competitor_id, TRUE FROM g;
            """, (tenant, tenant))
        with pytest.raises(usage.PlanLimitReached) as full:
            usage.ensure_capacity(conn, tenant, usage.TRACKED_COMPETITORS)
        assert full.value.reason == "CAPACITY_REACHED" and full.value.limit == cap
    finally:
        conn.close()


def test_a_new_billing_period_starts_from_zero(client):
    session, _ = _company(client, "starter")
    tenant = session["tenant_id"]
    # Last period's allowance was fully used...
    _admin("INSERT INTO tenant_usage_counters (tenant_id, feature_code, period_start, used) "
           "SELECT %s, 'rag_assistant', (current_period_start - INTERVAL '1 month')::date, 100000 "
           "FROM tenant_plan_assignments WHERE tenant_id = %s;", (tenant, tenant))
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        # ...which doesn't count against this one.
        assert usage.remaining(conn, tenant, usage.RAG_ASSISTANT) == 100_000
    finally:
        conn.close()


def test_one_companys_usage_never_reduces_anothers_allowance(client):
    a, _ = _company(client, "growth")
    b, _ = _company(client, "growth")
    _admin("INSERT INTO tenant_usage_counters (tenant_id, feature_code, period_start, used) "
           "SELECT %s, 'sentiment_analysis', current_period_start, 25000 FROM tenant_plan_assignments WHERE tenant_id = %s;",
           (a["tenant_id"], a["tenant_id"]))
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        assert usage.remaining(conn, a["tenant_id"], usage.SENTIMENT_ANALYSIS) == 0
        assert usage.remaining(conn, b["tenant_id"], usage.SENTIMENT_ANALYSIS) == 25_000
    finally:
        conn.close()


def test_new_companies_start_on_the_growth_trial(client):
    email = f"trial+{uuid.uuid4().hex[:8]}@example.com"
    session = create_verified_test_account(client, {"full_name": "Owner", "business_name": "Trial Co", "email": email,
                                                     "country_code": "JO", "primary_currency": "JOD",
                                                     "password": "Plan!Catalog-2026"})
    [(plan_key, status, days)] = _admin(
        "SELECT a.plan_key, a.status, (a.current_period_end - a.current_period_start) FROM tenant_plan_assignments a WHERE tenant_id = %s;",
        (session["tenant_id"],))
    assert (plan_key, status, days) == ("growth", "trialing", 14)


def test_the_assistant_allowance_is_counted_in_tokens(client):
    session, _ = _company(client, "starter")
    tenant = session["tenant_id"]
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        assert usage.remaining(conn, tenant, usage.RAG_ASSISTANT) == 100_000
        reservation = usage.reserve(conn, tenant, usage.RAG_ASSISTANT, usage.RAG_TOKEN_RESERVATION)
        usage.settle(conn, reservation, 1_734)          # the answer used 1,734 tokens
        conn.commit()
        assert usage.remaining(conn, tenant, usage.RAG_ASSISTANT) == 100_000 - 1_734
        _admin("UPDATE tenant_usage_counters SET used = 100000 WHERE tenant_id = %s AND feature_code = 'rag_assistant';", (tenant,))
        with pytest.raises(usage.PlanLimitReached) as exhausted:
            usage.reserve(conn, tenant, usage.RAG_ASSISTANT, 1)
        assert exhausted.value.reason == "QUOTA_EXHAUSTED"
    finally:
        conn.rollback()
        conn.close()


def test_review_analysis_stops_at_the_allowance(client, monkeypatch):
    from src.ai.sentiment import model, pipeline

    session, _ = _company(client, "growth")
    tenant = session["tenant_id"]
    for i in range(5):
        _admin("INSERT INTO reviews (tenant_id, source_platform, subject_type, review_text, review_rating) VALUES (%s, 'MANUAL', 'BUSINESS', %s, 4);",
               (tenant, f"Good service number {i}"))
    _admin("INSERT INTO tenant_usage_counters (tenant_id, feature_code, period_start, used) "
           "SELECT %s, 'sentiment_analysis', current_period_start, 24998 FROM tenant_plan_assignments WHERE tenant_id = %s;",
           (tenant, tenant))
    monkeypatch.setattr(model, "classify_or_unavailable",
                        lambda texts: [model.predict_from_rating(4) for _ in texts])
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        first = pipeline.classify_and_store_reviews(conn, tenant)
        assert first["analyzed_count"] == 2, "only the 2 records left in the Growth allowance (25,000)"
        assert pipeline.classify_and_store_reviews(conn, tenant)["status"] == "PLAN_LIMIT"
    finally:
        conn.close()


def test_starter_allows_one_connected_data_source(client):
    session, _ = _company(client, "starter")
    tenant = session["tenant_id"]
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        usage.ensure_capacity(conn, tenant, usage.CONNECTED_DATA_SOURCES)  # 0 of 1: fine
        _admin("INSERT INTO data_sources (tenant_id, source_name, source_type, is_active) VALUES (%s, 'POS', 'OWN_SYSTEM_CONNECTOR', TRUE);",
               (tenant,))
        with pytest.raises(usage.PlanLimitReached) as full:
            usage.ensure_capacity(conn, tenant, usage.CONNECTED_DATA_SOURCES)
        assert full.value.reason == "CAPACITY_REACHED" and full.value.limit == 1
    finally:
        conn.close()


def test_uploads_count_against_document_processing(client):
    session, headers = _company(client, "starter")
    csv = b"date,product,quantity,unit_price\n2026-09-01,Olive Oil,2,8.5\n"
    response = client.post("/extraction/upload", files={"file": ("sales.csv", csv, "text/csv")}, headers=headers)
    assert response.status_code == 200, response.text
    [(used,)] = _admin("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'document_extraction';",
                       (session["tenant_id"],))
    assert used == 1  # ceil(bytes / 1024) KB


def test_imports_create_products_only_up_to_the_plan_limit(client):
    session, headers = _company(client, "starter")  # Standard: 100 products
    tenant = session["tenant_id"]
    _admin("INSERT INTO products (tenant_id, product_name, current_price, currency, source) "
           "SELECT %s, jsonb_build_object('en', 'Existing ' || n), 1, 'JOD', 'MANUAL' FROM generate_series(1, 98) AS n;",
           (tenant,))
    csv = "date,product,quantity,unit_price\n" + "".join(
        f"2026-09-0{i},New item {i},1,2.5\n" for i in range(1, 6)) + "2026-09-07,Existing 1,3,1\n"
    response = client.post("/extraction/upload", files={"file": ("sales.csv", csv.encode(), "text/csv")}, headers=headers)
    assert response.status_code == 200, response.text
    promotion = response.json()["promotion"]
    assert promotion["products_created"] == 2          # 98 + 2 = the Standard limit of 100
    assert promotion["rows_over_product_limit"] == 3   # rows for the 3 products that didn't fit
    assert promotion["rows_promoted"] == 3             # 2 new products + the existing one
    [(count,)] = _admin("SELECT COUNT(*) FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant,))
    assert count == 100


def test_campaign_writing_uses_the_ai_token_allowance(client, monkeypatch):
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion

    session, headers = _company(client, "starter")  # 100,000 tokens
    tenant = session["tenant_id"]
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage",
                        lambda messages, **kw: scripted_campaign_completion(messages, total_tokens=3210))
    body = {"text": "Cold-pressed olive oil, 1 litre", "strategy_type": "SALES_DRIVEN"}
    assert client.post("/marketing/campaigns", json=body, headers=headers).status_code in (200, 201)
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        assert usage.remaining(conn, tenant, usage.RAG_ASSISTANT) == 100_000 - 2 * 3210  # generation and independent factual review
    finally:
        conn.close()

    # Nothing left: refused before the model is asked.
    _admin("UPDATE tenant_usage_counters SET used = 100000 WHERE tenant_id = %s AND feature_code = 'rag_assistant';", (tenant,))
    called = []
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: called.append(1))
    refused = client.post("/marketing/campaigns", json=body, headers=headers)
    assert refused.status_code == 402 and called == []


def test_market_analysis_uses_the_ai_token_allowance(client, monkeypatch):
    from src.ai.rag import llm_client

    session, headers = _company(client, "starter")
    tenant = session["tenant_id"]
    for i in range(3):
        _admin("INSERT INTO market_news (tenant_id, url, title, published_at) VALUES (%s, %s, %s, NOW());",
               (tenant, f"https://news.example.com/{tenant}/{i}", f"Flour prices rise again, report {i}"))
    asked = []
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: asked.append(1) or (
        '{"trends": [{"text": "Flour costs keep rising", "evidence": [3, 4]}], "watch": []}', {"total_tokens": 777}))
    response = client.post("/discovery/market/analysis", headers=headers)
    assert response.status_code == 200, response.text
    assert [t["text"] for t in response.json()["analysis"]["trends"]] == ["Flour costs keep rising"]
    assert client.get("/discovery/market/analysis", headers=headers).json()["analysis"]["trends"][0]["citations"][0]["url"].startswith("https://news.example.com/")
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        assert usage.remaining(conn, tenant, usage.RAG_ASSISTANT) == 100_000 - 777
    finally:
        conn.close()
    _admin("UPDATE tenant_usage_counters SET used = 100000 WHERE tenant_id = %s AND feature_code = 'rag_assistant';", (tenant,))
    assert client.post("/discovery/market/analysis", headers=headers).status_code == 402 and len(asked) == 1


def _storage_rows(tenant):
    return _admin("SELECT kind, size_bytes FROM tenant_storage_objects WHERE tenant_id = %s ORDER BY kind;", (tenant,))


@requires_minio
def test_stored_upload_results_count_toward_storage(client):
    session, headers = _company(client, "starter")
    tenant = session["tenant_id"]
    csv = b"date,product,quantity,unit_price\n2026-09-01,Olive Oil,2,8.5\n"
    assert client.post("/extraction/upload", files={"file": ("sales.csv", csv, "text/csv")}, headers=headers).status_code == 200
    rows = _storage_rows(tenant)
    assert [kind for kind, _ in rows] == ["upload_result"] and rows[0][1] > 0
    conn = psycopg2.connect(ADMIN_DATABASE_URL)
    try:
        used = [f for f in usage.current_usage(conn, tenant) if f["feature_code"] == usage.DOCUMENT_STORAGE_MB][0]["current_usage"]
        assert used == round(rows[0][1] / 1048576, 2)
    finally:
        conn.close()


@requires_minio
def test_a_marketing_image_is_refused_when_storage_is_full(client, monkeypatch):
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion

    session, headers = _company(client, "starter")  # 1 GB
    tenant = session["tenant_id"]
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: scripted_campaign_completion(messages, total_tokens=100))
    campaign = client.post("/marketing/campaigns", json={"text": "Olive oil", "strategy_type": "SALES_DRIVEN"}, headers=headers).json()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 2048
    ok = client.post(f"/marketing/campaigns/{campaign['campaign_id']}/image", files={"file": ("p.png", png, "image/png")}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert [kind for kind, _ in _storage_rows(tenant)] == ["marketing_source_image"]

    _admin("INSERT INTO tenant_storage_objects (tenant_id, bucket, object_key, size_bytes, kind) VALUES (%s, 'test', %s, %s, 'test');",
           (tenant, f"filler-{tenant}", 1024 * 1048576))
    full = client.post(f"/marketing/campaigns/{campaign['campaign_id']}/image", files={"file": ("p.png", png, "image/png")}, headers=headers)
    assert full.status_code == 402


@requires_minio
def test_marketing_images_stop_at_the_monthly_allowance_and_failures_are_not_counted(client, monkeypatch):
    from src.ai.marketing import designed_poster, image_generation
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion

    session, headers = _company(client, "starter")  # 20 images a month
    tenant = session["tenant_id"]
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: scripted_campaign_completion(messages, total_tokens=100))
    campaign = client.post("/marketing/campaigns", json={"text": "Olive oil", "strategy_type": "SALES_DRIVEN"}, headers=headers).json()
    url = f"/marketing/campaigns/{campaign['campaign_id']}/generate-image"

    def used():
        rows = _admin("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'marketing_image_generation';", (tenant,))
        return rows[0][0] if rows else 0

    # When nothing at all is produced - a provider failure or no provider, and the
    # locally drawn fallback poster failing too - nothing is used.
    def poster_fails(*args, **kwargs):
        raise RuntimeError("render failed")
    monkeypatch.setattr(designed_poster, "render_designed_poster", poster_fails)

    def fail(prompt, **kw):
        raise image_generation.ImageGenerationError("PROVIDER_ERROR", "provider down")
    monkeypatch.setattr(image_generation, "generate_campaign_image", fail)
    assert client.post(url, headers=headers).json()["image_generation_status"] == "PROVIDER_ERROR"
    monkeypatch.undo()
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: scripted_campaign_completion(messages, total_tokens=100))
    monkeypatch.setattr(designed_poster, "render_designed_poster", poster_fails)
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "none")
    assert client.post(url, headers=headers).json()["image_generation_status"] == "NOT_CONFIGURED"
    assert used() == 0

    # A produced image counts once; at the allowance the next is refused before the provider is asked.
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    calls = []
    monkeypatch.setattr(image_generation, "generate_campaign_image",
                        lambda prompt, **kw: calls.append(1) or image_generation.GeneratedImage(content=png, content_type="image/png", provider="test"))
    assert client.post(url, headers=headers).json()["image_generation_status"] == "COMPLETED"
    assert used() == 1
    _admin("UPDATE tenant_usage_counters SET used = 20 WHERE tenant_id = %s AND feature_code = 'marketing_image_generation';", (tenant,))
    refused = client.post(url, headers=headers)
    assert refused.status_code == 402 and len(calls) == 1
    assert refused.json()["detail"]["feature_code"] == "marketing_image_generation"


@requires_minio
def test_a_designed_poster_counts_as_one_image_of_the_monthly_allowance(client, monkeypatch):
    # Decision (PENDING_ACTIONS #76): when no AI image can be made, the locally
    # drawn poster is still a delivered image and uses one allowance.
    from src.ai.marketing import image_generation
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion

    session, headers = _company(client, "starter")
    tenant = session["tenant_id"]
    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", lambda messages, **kw: scripted_campaign_completion(messages, total_tokens=100))
    campaign = client.post("/marketing/campaigns", json={"text": "Olive oil", "strategy_type": "SALES_DRIVEN"}, headers=headers).json()
    url = f"/marketing/campaigns/{campaign['campaign_id']}/generate-image"

    def fail(prompt, **kw):
        raise image_generation.ImageGenerationError("PROVIDER_ERROR", "provider down")
    monkeypatch.setattr(image_generation, "generate_campaign_image", fail)

    result = client.post(url, headers=headers).json()
    assert result["image_generation_status"] == "COMPLETED"
    assert result["image_generation_provider"] == "designed"
    [(used,)] = _admin("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'marketing_image_generation';", (tenant,))
    assert used == 1


def test_review_imports_count_toward_monthly_uploads_and_storage_rows_stay_private(client, monkeypatch):
    from src.ai.routers import reviews

    # The background review analysis isn't what this test is about (and would
    # mark the sentiment model unavailable for later tests in this process).
    monkeypatch.setattr(reviews, "_analyze_imported_reviews", lambda *a, **k: None)
    a, a_headers = _company(client, "starter")
    b, _ = _company(client, "starter")
    csv = b"date,rating,review\n2026-09-01,5,Great oil\n"
    assert client.post("/reviews/import", files={"file": ("r.csv", csv, "text/csv")}, headers=a_headers).status_code == 200
    [(used,)] = _admin("SELECT used FROM tenant_usage_counters WHERE tenant_id = %s AND feature_code = 'document_extraction';", (a["tenant_id"],))
    assert used == 1
    _admin("INSERT INTO tenant_storage_objects (tenant_id, bucket, object_key, size_bytes, kind) VALUES (%s, 'test', %s, 10, 'test');",
           (a["tenant_id"], f"a-{a['tenant_id']}"))
    from src.ai import db
    conn = db.dedicated_tenant_connection(b["tenant_id"], b["user_id"])
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tenant_storage_objects;")
            assert cursor.fetchone()[0] == 0  # row-level security: B sees none of A's files
    finally:
        conn.close()
