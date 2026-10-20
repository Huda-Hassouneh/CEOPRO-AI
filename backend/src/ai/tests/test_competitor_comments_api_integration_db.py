"""The comments endpoints end to end, as the restricted app role under row-level security with real sign-ups:
a company sees only its own competitor's comments, can mark one, and another company can neither read nor mark it."""
import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient

ADMIN_DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL and/or APP_DB_PASSWORD not set")


def _signup(client, label):
    email = f"comments+{label}{uuid.uuid4().hex[:8]}@example.com"
    body = client.post("/auth/signup", json={"full_name": "Owner", "business_name": f"{label} Co", "email": email,
                                              "country_code": "JO", "primary_currency": "JOD", "password": "Comments!Test2026"}).json()
    return body, email


def test_comments_are_read_and_marked_per_company_through_the_real_api():
    from src.ai.main import app
    from src.market_scraper import competitor_enrichment as ce
    from src.market_scraper.discovery import CandidateSource, register_domain_level_competitor

    client = TestClient(app)
    owner, owner_email = _signup(client, "a")
    other, other_email = _signup(client, "b")
    own = {"Authorization": f"Bearer {owner['access_token']}"}
    foreign = {"Authorization": f"Bearer {other['access_token']}"}
    admin = psycopg2.connect(ADMIN_DATABASE_URL)
    tenant_id = owner["tenant_id"]
    try:
        candidate = CandidateSource(product_name="cafe", url="https://rivalcafe.example", title="Rival Cafe")
        competitor_id = register_domain_level_competitor(admin, tenant_id, str(uuid.uuid4()), candidate, "PLACES_NEARBY")["competitor_id"]
        admin.commit()
        source = ce._review_source(admin, tenant_id, str(uuid.uuid4()), "ops-1", name="YouTube comments (official API)", collector_key="youtube_comments", retention_days=30)
        slow, nice = "Very slow service and we waited an hour", "Lovely staff and fresh food every time"
        ce._save_comments(admin, tenant_id, competitor_id, source, "YouTube", [
            {"external_id": "a", "parent_external_id": None, "author": "Sam", "text": slow, "likes": 12, "published_at": None, "reply_count": 0, "url": "https://www.youtube.com/watch?v=v&lc=a"},
            {"external_id": "b", "parent_external_id": None, "author": "Lee", "text": nice, "likes": 1, "published_at": None, "reply_count": 0, "url": None}])
        with admin.cursor() as cursor:
            cursor.execute("SELECT review_id, review_text FROM reviews WHERE tenant_id = %s;", (tenant_id,))
            for review_id, text in cursor.fetchall():
                cursor.execute("INSERT INTO sentiment_results (tenant_id, review_id, sentiment_score, sentiment_label, model_version) VALUES (%s, %s, %s, %s, 'test');",
                               (tenant_id, review_id, -0.8 if text == slow else 0.8, "NEGATIVE" if text == slow else "POSITIVE"))
        admin.commit()

        listed = client.get(f"/competitors/{competitor_id}/reviews", headers=own)
        assert listed.status_code == 200
        body = listed.json()
        assert [c["text"] for c in body["comments"]] == [slow, nice] and body["comments"][0]["signal"] == "opportunity"
        assert body["comments"][0]["url"] == "https://www.youtube.com/watch?v=v&lc=a"
        assert body["summary"]["sentiment"]["negative"] == 1 and {t["theme"] for t in body["summary"]["themes"]} >= {"waiting", "staff"}
        assert [c["text"] for c in client.get(f"/competitors/{competitor_id}/reviews?theme=waiting&sentiment=negative", headers=own).json()["comments"]] == [slow]

        status = client.get(f"/competitors/{competitor_id}/data-status", headers=own).json()
        assert status["facets"]["COMMENTS"]["status"] == "SUCCEEDED" and status["facets"]["COMMENTS"]["next_step"] == "none"
        assert status["facets"]["REVIEWS"]["status"] != "SUCCEEDED"  # comments are not Google reviews

        first = body["comments"][0]["id"]
        assert client.put(f"/competitors/{competitor_id}/reviews/{first}/action", json={"status": "acted_on"}, headers=foreign).status_code == 404
        marked = client.put(f"/competitors/{competitor_id}/reviews/{first}/action", json={"status": "acted_on"}, headers=own)
        assert marked.status_code == 200 and marked.json()["action_status"] == "acted_on"
        assert [c["text"] for c in client.get(f"/competitors/{competitor_id}/reviews?action=open", headers=own).json()["comments"]] == [nice]
        assert client.put(f"/competitors/{competitor_id}/reviews/{first}/action", json={"status": None}, headers=own).json()["action_status"] is None

        assert client.get(f"/competitors/{competitor_id}/reviews", headers=foreign).status_code == 404  # another company's competitor
    finally:
        admin.rollback()
        with admin.cursor() as cursor:
            for tenant in (owner["tenant_id"], other["tenant_id"]):
                cursor.execute("DELETE FROM sentiment_results WHERE tenant_id = %s;", (tenant,))
                cursor.execute("DELETE FROM reviews WHERE tenant_id = %s;", (tenant,))
                cursor.execute("DELETE FROM competitor_enrichment WHERE tenant_id = %s;", (tenant,))
                cursor.execute("DELETE FROM data_sources WHERE tenant_id = %s;", (tenant,))
                cursor.execute("DELETE FROM tenant_competitors WHERE tenant_id = %s;", (tenant,))
                cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant,))
            for mail in (owner_email, other_email):
                cursor.execute("DELETE FROM users WHERE email = %s;", (mail,))
        admin.commit()
        admin.close()
