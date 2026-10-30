"""
The marketing image gallery against the real database, object storage and a
real (in-process) self-hosted image server reached over HTTP:

- an image in each format comes out at that format's exact ratio, whether a
  provider honours the requested size or not, and the designed fallback
  poster is made at the format's size;
- every image is kept in the campaign's gallery with its prompt, format and
  channel; one is attached; attach / channel / delete work, and deleting
  frees its storage;
- the owner's edited prompt is the one sent and is kept for next time;
- another company can't list, stream, change or delete any of it, and the
  table's row-level security hides the rows even from a direct query.

Only the language model is a fake. The image server is a real HTTP server
speaking the OpenAI images API or AUTOMATIC1111's txt2img API; it draws a
flat image of the requested size (it is not a diffusion model - none can
be downloaded in this sandbox), which is what these tests need: the HTTP
contract, the storage and the access rules.
"""
import base64
import io
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2
import pytest
from fastapi.testclient import TestClient
from PIL import Image

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not DATABASE_URL or not os.getenv("APP_DB_PASSWORD"),
                       reason="AI_TEST_DATABASE_URL/APP_DB_PASSWORD not set - skipping live-DB integration test"),
    pytest.mark.skipif(not all(os.getenv(k) for k in ("MINIO_ENDPOINT", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")),
                       reason="MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD not set - skipping MinIO-backed test"),
]


class _ImageServer:
    """A real HTTP server on 127.0.0.1 with the two local image APIs."""

    def __init__(self, square_only=False):
        self.requests = []
        self.square_only = square_only  # like Workers AI FLUX: ignores the requested size
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append((self.path, body))
                if self.path == "/v1/images/generations":
                    width, height = (int(v) for v in body["size"].split("x"))
                elif self.path == "/sdapi/v1/txt2img":
                    width, height = body["width"], body["height"]
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                if server.square_only:
                    width = height = 1024
                buffer = io.BytesIO()
                Image.new("RGB", (width, height), (30, 90, 160)).save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode()
                answer = {"data": [{"b64_json": encoded}]} if self.path.startswith("/v1") else {"images": [encoded]}
                payload = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def studio(monkeypatch):
    from src.ai.core import notifications
    from src.ai.main import app
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import _valid_response_json

    def model(messages, **kwargs):
        from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion
        payload = json.loads(_valid_response_json())
        payload["image_prompt"] = "Golden kunafa on a marble counter, warm morning light"
        return scripted_campaign_completion(messages, campaign_json=json.dumps(payload), total_tokens=900)

    monkeypatch.setattr(llm_client, "_chat_completion_with_usage", model)
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local")
    server = _ImageServer()
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", server.url)
    monkeypatch.setenv("LOCAL_IMAGE_API", "openai")
    client = TestClient(app)
    verification_codes = {}
    monkeypatch.setattr(notifications, "send_email_verification_email",
                        lambda address, code: verification_codes.__setitem__(address, code) or True)

    def company():
        email = f"gallery+{uuid.uuid4().hex[:8]}@example.com"
        signup = client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Gallery Bakery", "email": email,
                                                    "country_code": "JO", "primary_currency": "JOD",
                                                    "password": "Gallery!Test-2026"})
        assert signup.status_code == 202, signup.text
        verified = client.post("/auth/email/verify", json={"email": email,
            "registration_token": signup.json()["registration_token"], "code": verification_codes[email]})
        assert verified.status_code == 200, verified.text
        session = verified.json()
        return session, {"Authorization": f"Bearer {session['access_token']}"}

    def campaign(headers):
        created = client.post("/marketing/campaigns", json={"text": "Fresh kunafa, 3.5 JOD", "strategy_type": "SALES_DRIVEN"},
                              headers=headers)
        assert created.status_code == 200, created.text
        return created.json()["campaign_id"]

    yield client, server, company, campaign
    server.close()


def _size(content):
    with Image.open(io.BytesIO(content)) as picture:
        return picture.size


def test_options_list_the_formats_and_channels(studio):
    client, _server, company, _campaign = studio
    _session, headers = company()
    options = client.get("/marketing/options", headers=headers).json()
    assert [f["key"] for f in options["image_formats"]] == ["SQUARE", "PORTRAIT", "STORY", "LANDSCAPE", "WIDE"]
    assert "INSTAGRAM" in options["asset_channels"]
    # A self-hosted server only: images are available and nothing leaves this server.
    assert options["capabilities"]["image_generation"]["available"] is True
    assert options["capabilities"]["image_generation"]["external"] is False


@pytest.mark.parametrize("image_format,ratio", [("SQUARE", 1.0), ("PORTRAIT", 0.8), ("STORY", 9 / 16),
                                                ("LANDSCAPE", 16 / 9), ("WIDE", 1.91)])
def test_each_format_is_made_by_the_local_server_at_its_exact_ratio(studio, image_format, ratio):
    client, server, company, campaign = studio
    _session, headers = company()
    cid = campaign(headers)
    made = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": image_format}, headers=headers)
    assert made.status_code == 200, made.text
    result = made.json()
    assert result["image_generation_status"] == "COMPLETED" and result["image_generation_mode"] == "ai"
    asset = result["asset"]
    assert asset["image_format"] == image_format and asset["attached"] is True
    path, body = server.requests[-1]
    assert path == "/v1/images/generations" and body["response_format"] == "b64_json"
    stored = client.get(f"/marketing/campaigns/{cid}/assets/{asset['asset_id']}/image", headers=headers)
    assert stored.status_code == 200 and stored.headers["content-type"] == "image/png"
    width, height = _size(stored.content)
    assert (width, height) == (asset["width"], asset["height"])
    assert abs(width / height - ratio) / ratio <= 0.02


def test_a_provider_that_ignores_the_size_is_cropped_to_the_format(studio, monkeypatch):
    client, server, company, campaign = studio
    server.square_only = True
    _session, headers = company()
    cid = campaign(headers)
    asset = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "STORY"},
                        headers=headers).json()["asset"]
    assert (asset["width"], asset["height"]) == (576, 1024)  # centre crop of 1024x1024 to 9:16


def test_the_a1111_api_works_too(studio, monkeypatch):
    client, server, company, campaign = studio
    monkeypatch.setenv("LOCAL_IMAGE_API", "a1111")
    _session, headers = company()
    cid = campaign(headers)
    result = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "LANDSCAPE"}, headers=headers).json()
    assert result["image_generation_status"] == "COMPLETED"
    path, body = server.requests[-1]
    assert path == "/sdapi/v1/txt2img" and (body["width"], body["height"]) == (1344, 768)


def test_the_owners_prompt_is_sent_and_kept_and_the_channel_recorded(studio):
    client, server, company, campaign = studio
    _session, headers = company()
    cid = campaign(headers)
    assert client.get(f"/marketing/campaigns/{cid}", headers=headers).json()["image_prompt_default"].startswith("Golden kunafa")
    result = client.post(f"/marketing/campaigns/{cid}/generate-image",
                         json={"prompt": "Kunafa slice with pistachio, top-down, soft daylight", "channel": "INSTAGRAM"},
                         headers=headers).json()
    assert server.requests[-1][1]["prompt"] == "Kunafa slice with pistachio, top-down, soft daylight"
    assert result["asset"]["channel"] == "INSTAGRAM"
    assert result["asset"]["prompt"] == "Kunafa slice with pistachio, top-down, soft daylight"
    reloaded = client.get(f"/marketing/campaigns/{cid}", headers=headers).json()
    assert reloaded["image_prompt_default"] == "Kunafa slice with pistachio, top-down, soft daylight"


def test_gallery_attach_channel_and_delete(studio):
    from src.ai import db
    from src.ai.marketing import image_storage

    client, _server, company, campaign = studio
    session, headers = company()
    tenant = session["tenant_id"]
    cid = campaign(headers)
    first = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "SQUARE"}, headers=headers).json()
    # attach=false: kept in the gallery, the campaign keeps its image.
    second = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "STORY", "attach": False},
                         headers=headers).json()
    assert second["asset"]["attached"] is False and second["generated_image_key"] == first["generated_image_key"]
    gallery = client.get(f"/marketing/campaigns/{cid}/assets", headers=headers).json()["assets"]
    assert [a["image_format"] for a in gallery] == ["STORY", "SQUARE"] and [a["attached"] for a in gallery] == [False, True]

    story_id = second["asset"]["asset_id"]
    changed = client.patch(f"/marketing/campaigns/{cid}/assets/{story_id}", json={"attach": True, "channel": "TIKTOK"},
                           headers=headers)
    assert changed.status_code == 200 and changed.json()["attached"] is True and changed.json()["channel"] == "TIKTOK"
    assert client.patch(f"/marketing/campaigns/{cid}/assets/{story_id}", json={"clear_channel": True},
                        headers=headers).json()["channel"] is None
    assert client.patch(f"/marketing/campaigns/{cid}/assets/{story_id}", json={"channel": "MYSPACE"},
                        headers=headers).status_code == 422
    # The campaign's own image (GET .../image) is now the story.
    assert _size(client.get(f"/marketing/campaigns/{cid}/image", headers=headers).content)[1] > 1000

    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM tenant_storage_objects WHERE tenant_id = %s;", (tenant,))
        assert cursor.fetchone()[0] == 2
    assert client.delete(f"/marketing/campaigns/{cid}/assets/{story_id}", headers=headers).status_code == 200
    gallery = client.get(f"/marketing/campaigns/{cid}/assets", headers=headers).json()["assets"]
    assert len(gallery) == 1 and gallery[0]["attached"] is True  # the square one is attached again
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM tenant_storage_objects WHERE tenant_id = %s;", (tenant,))
        assert cursor.fetchone()[0] == 1
    names = [o.object_name for o in db.minio_client().list_objects(
        image_storage.GENERATED_IMAGES_BUCKET, prefix=f"{tenant}/{cid}/", recursive=True)]
    assert len(names) == 1
    # Deleting the last one leaves the campaign without an image.
    assert client.delete(f"/marketing/campaigns/{cid}/assets/{gallery[0]['asset_id']}", headers=headers).status_code == 200
    reloaded = client.get(f"/marketing/campaigns/{cid}", headers=headers).json()
    assert reloaded["generated_image_key"] is None and reloaded["image_generation_status"] is None
    assert client.get(f"/marketing/campaigns/{cid}/assets/{gallery[0]['asset_id']}/image", headers=headers).status_code == 404


def test_bad_requests_are_refused(studio):
    client, _server, company, campaign = studio
    _session, headers = company()
    cid = campaign(headers)
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "BANNER"}, headers=headers).status_code == 422
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", json={"channel": "FAX"}, headers=headers).status_code == 422
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", json={"prompt": "x" * 2001}, headers=headers).status_code == 422
    assert client.get(f"/marketing/campaigns/{cid}/assets/not-a-uuid/image", headers=headers).status_code == 404
    assert client.get("/marketing/campaigns/not-a-uuid/assets", headers=headers).status_code == 404
    assert client.get(f"/marketing/campaigns/{cid}/assets").status_code == 401


def test_when_the_local_server_is_down_a_designed_poster_in_the_format_is_stored(studio, monkeypatch):
    client, server, company, campaign = studio
    server.close()  # nothing answers any more
    _session, headers = company()
    cid = campaign(headers)
    result = client.post(f"/marketing/campaigns/{cid}/generate-image", json={"image_format": "PORTRAIT"}, headers=headers).json()
    assert result["image_generation_status"] == "COMPLETED" and result["image_generation_mode"] == "designed"
    stored = client.get(f"/marketing/campaigns/{cid}/assets/{result['asset']['asset_id']}/image", headers=headers)
    assert _size(stored.content) == (1080, 1350)


def test_another_company_can_reach_none_of_it(studio):
    client, _server, company, campaign = studio
    session, headers = company()
    cid = campaign(headers)
    asset_id = client.post(f"/marketing/campaigns/{cid}/generate-image", json={}, headers=headers).json()["asset"]["asset_id"]

    other_session, other = company()
    assert client.get(f"/marketing/campaigns/{cid}/assets", headers=other).status_code == 404
    assert client.get(f"/marketing/campaigns/{cid}/assets/{asset_id}/image", headers=other).status_code == 404
    assert client.patch(f"/marketing/campaigns/{cid}/assets/{asset_id}", json={"attach": True}, headers=other).status_code == 404
    assert client.delete(f"/marketing/campaigns/{cid}/assets/{asset_id}", headers=other).status_code == 404
    assert client.post(f"/marketing/campaigns/{cid}/generate-image", json={}, headers=other).status_code == 404
    # Their own campaign + this company's asset id: still not found.
    other_cid = campaign(other)
    assert client.get(f"/marketing/campaigns/{other_cid}/assets/{asset_id}/image", headers=other).status_code == 404
    assert client.delete(f"/marketing/campaigns/{other_cid}/assets/{asset_id}", headers=other).status_code == 404
    # The owner still has it.
    assert client.get(f"/marketing/campaigns/{cid}/assets/{asset_id}/image", headers=headers).status_code == 200

    # Row-level security, not only the API: as the application role in the
    # other company's context, the row is invisible.
    from src.ai import db

    conn = db.app_role_connection(other_session["tenant_id"], other_session.get("user_id"))
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM campaign_image_assets WHERE asset_id = %s;", (asset_id,))
            assert cursor.fetchone()[0] == 0
        conn.rollback()
    finally:
        conn.close()
    conn = db.app_role_connection(session["tenant_id"], session.get("user_id"))
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM campaign_image_assets WHERE asset_id = %s;", (asset_id,))
            assert cursor.fetchone()[0] == 1
        conn.rollback()
    finally:
        conn.close()
