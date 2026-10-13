"""
A marketing campaign's whole life against the real database and object
storage: created with its image in one request, the same press twice
gives one campaign (and one charge), the copy is edited and kept after a
reload, history pages through every campaign, regenerating replaces the
old image file, deleting removes the campaign, its copy and its files -
and another company can do none of it. Only the AI providers are fakes.
"""
import io
import os
import uuid

import jwt
import psycopg2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), (180, 110, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def setup(monkeypatch):
    from src.ai.main import app
    from src.ai.marketing import image_generation
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import _valid_response_json

    client = TestClient(app)
    calls = {"llm": 0, "image": 0, "prompts": []}

    def model(messages, **kwargs):
        calls["llm"] += 1
        import json
        payload = json.loads(_valid_response_json())
        payload["image_prompt"] = "A tray of golden kunafa on a marble counter, warm morning light"
        return json.dumps(payload), {"total_tokens": 900}

    def image(prompt, **kwargs):
        calls["image"] += 1
        calls["prompts"].append(prompt)
        return image_generation.GeneratedImage(content=_png(), content_type="image/png", provider="cloudflare")

    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", model)
    monkeypatch.setattr(image_generation, "generate_campaign_image", image)

    def company():
        email = f"lifecycle+{uuid.uuid4().hex[:8]}@example.com"
        assert client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Lifecycle Bakery", "email": email,
                                                 "country_code": "JO", "primary_currency": "JOD",
                                                 "password": "Lifecycle!Test-2026"}).status_code in (200, 201)
        session = client.post("/auth/login", json={"email": email, "password": "Lifecycle!Test-2026"}).json()
        return session, {"Authorization": f"Bearer {session['access_token']}"}

    return client, calls, company


def _storage_keys(tenant):
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT object_key FROM tenant_storage_objects WHERE tenant_id = %s ORDER BY created_at;", (tenant,))
        return [r[0] for r in cursor.fetchall()]


def test_a_campaign_is_created_with_its_image_edited_reloaded_paged_and_deleted(setup):
    from src.ai import db
    from src.ai.marketing import image_storage

    client, calls, company = setup
    session, headers = company()
    tenant = session["tenant_id"]
    body = {"text": "Fresh kunafa, 3.5 JOD", "strategy_type": "SALES_DRIVEN", "generate_image": True,
            "request_key": f"press-{uuid.uuid4().hex}"}

    created = client.post("/marketing/campaigns", json=body, headers=headers)
    assert created.status_code == 200, created.text
    campaign = created.json()
    cid = campaign["campaign_id"]
    assert campaign["status"] == "COMPLETED" and campaign["image_generation_status"] == "COMPLETED"
    assert campaign["image_prompt"].startswith("A tray of golden kunafa")
    assert calls["prompts"] == ["A tray of golden kunafa on a marble counter, warm morning light"]  # the English image prompt is used
    image = client.get(f"/marketing/campaigns/{cid}/image", params={"kind": "generated"}, headers=headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png" and len(image.content) > 100

    # The same press again: same campaign, nothing written or charged twice.
    again = client.post("/marketing/campaigns", json=body, headers=headers).json()
    assert again["campaign_id"] == cid and again["duplicate_request"] is True
    assert (calls["llm"], calls["image"]) == (1, 1)

    # Edit the title, audience and one caption; a reload shows the edits.
    edit = {"title": "Kunafa weekend offer", "audience_summary": "Families in Amman",
            "variants": [{"platform": "INSTAGRAM", "variant_index": 1, "body_copy": "Our kunafa, warm from the oven.",
                          "hashtags": ["kunafa", "#amman"], "cta": "Order now"}]}
    edited = client.patch(f"/marketing/campaigns/{cid}", json=edit, headers=headers)
    assert edited.status_code == 200, edited.text
    reloaded = client.get(f"/marketing/campaigns/{cid}", headers=headers).json()
    assert reloaded["campaign_brief"] == "Kunafa weekend offer" and reloaded["audience_summary"] == "Families in Amman"
    instagram = reloaded["content"]["INSTAGRAM"][0]
    assert instagram["body_copy"] == "Our kunafa, warm from the oven." and instagram["hashtags"] == ["#kunafa", "#amman"]
    assert instagram["cta"] == "Order now" and reloaded["updated_at"]
    assert client.patch(f"/marketing/campaigns/{cid}", json={"variants": [{"platform": "TIKTOK", "variant_index": 9, "body_copy": "x"}]},
                        headers=headers).status_code == 422
    assert client.patch(f"/marketing/campaigns/{cid}", json={"variants": [{"platform": "GOOGLE_ADS", "variant_index": 1, "headline": "x" * 31}]},
                        headers=headers).status_code == 422

    # Regenerating replaces the image file (the old one no longer takes space).
    first_key = reloaded["generated_image_key"]
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", headers=headers).json()["image_generation_status"] == "COMPLETED"
    second_key = client.get(f"/marketing/campaigns/{cid}", headers=headers).json()["generated_image_key"]
    assert second_key != first_key and _storage_keys(tenant) == [second_key]
    minio = db.minio_client()
    names = [o.object_name for o in minio.list_objects(image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{tenant}/{cid}/", recursive=True)]
    assert names == [second_key]

    # History reaches every campaign, not only the latest few, and searches.
    for i in range(3):
        client.post("/marketing/campaigns", json={"text": f"Maamoul box {i}", "strategy_type": "SALES_DRIVEN"}, headers=headers)
    page = client.get("/marketing/campaigns", params={"limit": 2, "offset": 2}, headers=headers).json()
    assert page["total"] == 4 and len(page["campaigns"]) == 2
    found = client.get("/marketing/campaigns", params={"q": "weekend"}, headers=headers).json()
    assert [c["campaign_id"] for c in found["campaigns"]] == [cid] and found["campaigns"][0]["has_image"] is True

    # Another company can't read, edit, regenerate or delete it.
    _other, other_headers = company()
    assert client.get(f"/marketing/campaigns/{cid}", headers=other_headers).status_code == 404
    assert client.patch(f"/marketing/campaigns/{cid}", json=edit, headers=other_headers).status_code == 404
    assert client.delete(f"/marketing/campaigns/{cid}", headers=other_headers).status_code == 404
    assert client.get("/marketing/campaigns", headers=other_headers).json()["total"] == 0

    # Deleting removes the campaign, its copy and its files.
    deleted = client.delete(f"/marketing/campaigns/{cid}", headers=headers)
    assert deleted.status_code == 200 and deleted.json()["images_removed"] == 1
    assert client.get(f"/marketing/campaigns/{cid}", headers=headers).status_code == 404
    assert list(minio.list_objects(image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{tenant}/{cid}/", recursive=True)) == []
    assert _storage_keys(tenant) == []
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM campaign_content WHERE tenant_id = %s AND campaign_id = %s;", (tenant, cid))
        assert cursor.fetchone()[0] == 0
    assert client.delete(f"/marketing/campaigns/{cid}", headers=headers).status_code == 404
    assert client.delete("/marketing/campaigns/not-a-uuid", headers=headers).status_code == 404


def test_an_image_that_cant_be_made_leaves_a_complete_campaign(setup, monkeypatch):
    from src.ai.marketing import image_generation

    client, calls, company = setup
    _session, headers = company()

    def fail(prompt, **kwargs):
        error = image_generation.ImageGenerationError("PROVIDER_ERROR", "No image provider produced an image (pollinations: busy).")
        error.attempts = [{"provider": "pollinations", "reason": "busy"}]
        raise error

    monkeypatch.setattr(image_generation, "generate_campaign_image", fail)
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN", "generate_image": True},
                           headers=headers).json()
    assert campaign["status"] == "COMPLETED" and campaign["content"]
    assert campaign["image_generation_status"] == "PROVIDER_ERROR"
    assert campaign["image_generation_attempts"] == [{"provider": "pollinations", "reason": "busy"}]
