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

from src.ai.tests.signup_helpers import create_verified_test_account

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                                reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test")

# These tests store real objects, so they need MinIO as well as Postgres (CI has no MinIO service).
requires_minio = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")),
    reason="MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD not set - skipping MinIO-backed test",
)


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

    client = TestClient(app, raise_server_exceptions=False)
    calls = {"llm": 0, "image": 0, "prompts": []}

    def model(messages, **kwargs):
        calls["llm"] += 1
        import json
        from src.ai.marketing import content_generator
        if messages[0]['content'] == content_generator._GROUNDING_PROMPT:
            return json.dumps({'supported':True,'unsupported_claims':[],'claims':[]}), {'total_tokens':100}
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
        session = create_verified_test_account(client, {"full_name": "Owner", "business_name": "Lifecycle Bakery", "email": email,
                                                         "country_code": "JO", "primary_currency": "JOD",
                                                         "password": "Lifecycle!Test-2026"})
        return session, {"Authorization": f"Bearer {session['access_token']}"}

    return client, calls, company


def _storage_keys(tenant):
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT object_key FROM tenant_storage_objects WHERE tenant_id = %s ORDER BY created_at;", (tenant,))
        return [r[0] for r in cursor.fetchall()]


@requires_minio
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
    assert (calls["llm"], calls["image"]) == (2, 1)  # Draft plus factual review, one image.

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

    # Regenerating adds the new image to the gallery and attaches it; the
    # earlier one stays (and takes space) until it is deleted.
    first_key = reloaded["generated_image_key"]
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", headers=headers).json()["image_generation_status"] == "COMPLETED"
    second_key = client.get(f"/marketing/campaigns/{cid}", headers=headers).json()["generated_image_key"]
    assert second_key != first_key and _storage_keys(tenant) == [first_key, second_key]
    gallery = client.get(f"/marketing/campaigns/{cid}/assets", headers=headers).json()["assets"]
    assert len(gallery) == 2 and [a["attached"] for a in gallery] == [True, False]
    assert "provider" not in gallery[0] and "image_key" not in gallery[0]  # never exposed
    # Deleting the attached image attaches the one left and frees its space.
    deleted = client.delete(f"/marketing/campaigns/{cid}/assets/{gallery[0]['asset_id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/marketing/campaigns/{cid}", headers=headers).json()["generated_image_key"] == first_key
    assert _storage_keys(tenant) == [first_key]
    minio = db.minio_client()
    names = [o.object_name for o in minio.list_objects(image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{tenant}/{cid}/", recursive=True)]
    assert names == [first_key]

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
    """No AI image AND the local poster failing too: the campaign is still complete, with an honest image status."""
    from src.ai.marketing import designed_poster, image_generation

    client, calls, company = setup
    _session, headers = company()

    def fail(prompt, **kwargs):
        error = image_generation.ImageGenerationError("PROVIDER_ERROR", "No image provider produced an image (aihorde: busy).")
        error.attempts = [{"provider": "aihorde", "reason": "busy"}]
        raise error

    def poster_fails(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(image_generation, "generate_campaign_image", fail)
    monkeypatch.setattr(designed_poster, "render_designed_poster", poster_fails)
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN", "generate_image": True},
                           headers=headers).json()
    assert campaign["status"] == "COMPLETED" and campaign["content"]
    assert campaign["image_generation_status"] == "PROVIDER_ERROR"
    assert "image_generation_attempts" not in campaign  # provider details stay in the server log


def test_when_no_ai_image_can_be_made_a_designed_poster_is_stored_instead(setup, monkeypatch):
    """The fallback path end to end against the real database: a finished image, labelled as designed."""
    from unittest.mock import MagicMock

    from src.ai.marketing import image_generation, image_storage
    from src.ai.routers import marketing as marketing_router

    client, calls, company = setup
    _session, headers = company()
    stored = {}

    def fail(prompt, **kwargs):
        raise image_generation.ImageGenerationError("PROVIDER_ERROR", "No image provider produced an image (aihorde: busy).")

    def fake_upload(client_, content, content_type, tenant_id, campaign_id, **kwargs):
        stored["content"] = content
        return f"{tenant_id}/{campaign_id}/generated.png"

    monkeypatch.setattr(image_generation, "generate_campaign_image", fail)
    monkeypatch.setattr(marketing_router.db, "minio_client", lambda: MagicMock())
    monkeypatch.setattr(image_storage, "upload_generated_image", fake_upload)
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN", "generate_image": True},
                           headers=headers).json()
    assert campaign["status"] == "COMPLETED"
    assert campaign["image_generation_status"] == "COMPLETED" and campaign["image_generation_provider"] == "designed"
    assert stored["content"][:8] == b"\x89PNG\r\n\x1a\n"


@requires_minio
def test_database_failure_after_source_upload_removes_the_new_object(setup, monkeypatch):
    from src.ai.marketing import image_storage
    from src.ai.routers import marketing as marketing_router

    client, _calls, company = setup
    session, headers = company()
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN"},
                           headers=headers).json()
    campaign_id = campaign["campaign_id"]
    real_upload = image_storage.upload_source_image

    def verify_committed_before_put(client_, contents, content_type, tenant_id, campaign_id_, ext, **kwargs):
        key = kwargs["object_key"]
        kwargs["on_pre_upload"](image_storage.SOURCE_IMAGES_BUCKET, key, len(contents))
        with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
            cursor.execute(
                "SELECT size_bytes FROM tenant_storage_objects WHERE tenant_id = %s AND bucket = %s AND object_key = %s;",
                (tenant_id, image_storage.SOURCE_IMAGES_BUCKET, key),
            )
            assert cursor.fetchone() == (len(contents),)
        return real_upload(
            client_, contents, content_type, tenant_id, campaign_id_, ext,
            object_key=key, on_pre_upload=None,
        )

    monkeypatch.setattr(image_storage, "upload_source_image", verify_committed_before_put)

    def fail_campaign_update(*_args, **_kwargs):
        raise RuntimeError("injected database failure after object upload")

    monkeypatch.setattr(marketing_router.data_access, "set_source_image_key", fail_campaign_update)
    response = client.post(
        f"/marketing/campaigns/{campaign_id}/image",
        files={"file": ("source.png", _png(), "image/png")}, headers=headers,
    )

    assert response.status_code == 500
    assert _storage_keys(session["tenant_id"]) == []
    objects = list(marketing_router.db.minio_client().list_objects(
        image_storage.SOURCE_IMAGES_BUCKET, prefix=f"{session['tenant_id']}/{campaign_id}/", recursive=True,
    ))
    assert objects == []


@requires_minio
def test_stale_marketing_rows_cleanup_only_unreferenced_objects(setup):
    from src.ai import db
    from src.ai.marketing import image_storage

    client, _calls, company = setup
    session, headers = company()
    tenant_id = session["tenant_id"]
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN"},
                           headers=headers).json()
    campaign_id = campaign["campaign_id"]
    minio = db.minio_client()
    bucket = image_storage.SOURCE_IMAGES_BUCKET
    if not minio.bucket_exists(bucket):
        minio.make_bucket(bucket)
    orphan_key = f"{tenant_id}/{campaign_id}/stale-orphan.png"
    missing_key = f"{tenant_id}/{campaign_id}/stale-missing.png"
    minio.put_object(bucket, orphan_key, io.BytesIO(b"old"), length=3, content_type="image/png")
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenant_storage_objects (tenant_id,bucket,object_key,size_bytes,kind,created_at) "
            "VALUES (%s,%s,%s,3,'marketing_source_image',NOW()-INTERVAL '2 days'), "
            "(%s,%s,%s,4,'marketing_source_image',NOW()-INTERVAL '2 days');",
            (tenant_id, bucket, orphan_key, tenant_id, bucket, missing_key),
        )

    response = client.post(
        f"/marketing/campaigns/{campaign_id}/image",
        files={"file": ("source.png", _png(), "image/png")}, headers=headers,
    )

    assert response.status_code == 200, response.text
    remaining = _storage_keys(tenant_id)
    assert orphan_key not in remaining and missing_key not in remaining
    assert all(obj.object_name != orphan_key for obj in minio.list_objects(bucket, prefix=f"{tenant_id}/{campaign_id}/", recursive=True))


@requires_minio
def test_storage_delete_failure_preserves_campaign_and_quota_entry(setup, monkeypatch):
    from src.ai.marketing import image_storage
    from src.ai.routers import marketing as marketing_router

    client, _calls, company = setup
    session, headers = company()
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN",
                                                         "generate_image": True}, headers=headers).json()
    campaign_id = campaign["campaign_id"]
    before = _storage_keys(session["tenant_id"])

    def fail_delete(*_args, **_kwargs):
        raise ConnectionError("injected object-storage outage")

    monkeypatch.setattr(marketing_router.image_storage, "remove_campaign_images", fail_delete)
    response = client.delete(f"/marketing/campaigns/{campaign_id}", headers=headers)

    assert response.status_code == 502
    assert client.get(f"/marketing/campaigns/{campaign_id}", headers=headers).status_code == 200
    assert _storage_keys(session["tenant_id"]) == before
    objects = list(marketing_router.db.minio_client().list_objects(
        image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{session['tenant_id']}/{campaign_id}/", recursive=True,
    ))
    assert objects
    monkeypatch.undo()
    assert client.delete(f"/marketing/campaigns/{campaign_id}", headers=headers).status_code == 200


@requires_minio
def test_failed_upload_cleanup_keeps_orphan_bytes_counted(setup, monkeypatch):
    from src.ai.marketing import image_storage
    from src.ai.routers import marketing as marketing_router

    client, _calls, company = setup
    session, headers = company()
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN"},
                           headers=headers).json()
    campaign_id = campaign["campaign_id"]

    def fail_campaign_update(*_args, **_kwargs):
        raise RuntimeError("injected database failure after object upload")

    def fail_cleanup(*_args, **_kwargs):
        raise ConnectionError("injected cleanup failure")

    monkeypatch.setattr(marketing_router.data_access, "set_source_image_key", fail_campaign_update)
    monkeypatch.setattr(marketing_router.image_storage, "remove_image", fail_cleanup)
    response = client.post(
        f"/marketing/campaigns/{campaign_id}/image",
        files={"file": ("source.png", _png(), "image/png")}, headers=headers,
    )

    assert response.status_code == 500
    tracked = _storage_keys(session["tenant_id"])
    assert len(tracked) == 1
    assert tracked[0].startswith(f"{session['tenant_id']}/{campaign_id}/")
    objects = list(marketing_router.db.minio_client().list_objects(
        image_storage.SOURCE_IMAGES_BUCKET, prefix=f"{session['tenant_id']}/{campaign_id}/", recursive=True,
    ))
    assert len(objects) == 1 and objects[0].object_name == tracked[0]
    client_ = marketing_router.db.minio_client()
    client_.remove_object(image_storage.SOURCE_IMAGES_BUCKET, tracked[0])
    with psycopg2.connect(DATABASE_URL) as admin, admin.cursor() as cursor:
        cursor.execute("DELETE FROM tenant_storage_objects WHERE tenant_id = %s AND object_key = %s;",
                       (session["tenant_id"], tracked[0]))


@requires_minio
def test_replacement_delete_failure_keeps_old_object_in_storage_accounting(setup, monkeypatch):
    from src.ai.marketing import image_storage
    from src.ai.routers import marketing as marketing_router

    client, _calls, company = setup
    session, headers = company()
    campaign = client.post("/marketing/campaigns", json={"text": "Kunafa", "strategy_type": "SALES_DRIVEN",
                                                         "generate_image": True}, headers=headers).json()
    campaign_id = campaign["campaign_id"]
    old_key = campaign["generated_image_key"]
    real_remove = image_storage.remove_image

    def fail_previous(client_, bucket, key):
        if key == old_key:
            raise ConnectionError("injected old-object deletion failure")
        return real_remove(client_, bucket, key)

    monkeypatch.setattr(marketing_router.image_storage, "remove_image", fail_previous)
    regenerated = client.post(f"/marketing/campaigns/{campaign_id}/generate-image", headers=headers)

    assert regenerated.status_code == 200
    assert regenerated.json()["image_generation_status"] == "COMPLETED"
    tracked = _storage_keys(session["tenant_id"])
    assert old_key in tracked and len(tracked) == 2
    objects = list(marketing_router.db.minio_client().list_objects(
        image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{session['tenant_id']}/{campaign_id}/", recursive=True,
    ))
    assert {item.object_name for item in objects} == set(tracked)
    monkeypatch.undo()
    assert client.delete(f"/marketing/campaigns/{campaign_id}", headers=headers).status_code == 200
