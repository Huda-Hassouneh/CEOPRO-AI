"""
The background image queue against the real database and object storage:
batches of formats x variations, the worker making them (through an
in-process HTTP image server speaking the self-hosted API - the HTTP
contract, not a model; real model output is checked by
scripts/real_image_check.py), retries with backoff, "busy" re-queues that
use no attempt, takeover of a job whose worker died, companies served in
turn, limits, cancel/retry, capacity figures, and isolation between
companies (API and row-level security).
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


class _Server:
    """Answers the self-hosted images API; `script` forces status codes."""

    def __init__(self):
        self.requests, self.script = [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                status = outer.script.pop(0) if outer.script else 200
                if status != 200:
                    self.send_response(status)
                    self.send_header("Retry-After", "5")
                    self.end_headers()
                    return
                width, height = (int(v) for v in body["size"].split("x"))
                buffer = io.BytesIO()
                Image.new("RGB", (width, height), (body.get("seed", 0) % 255, 80, 120)).save(buffer, format="JPEG")
                payload = json.dumps({"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def queue(monkeypatch):
    from src.ai.core import notifications
    from src.ai.main import app
    from src.ai.marketing import image_generation
    from src.ai.rag import llm_client
    from src.ai.tests.test_marketing_content_generator import _valid_response_json

    monkeypatch.setattr(llm_client, "_chat_completion_with_usage",
                        lambda messages, **kw: (_valid_response_json(image_prompt="A jar of zaatar on a stone counter"), {"total_tokens": 500}))
    server = _Server()
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local")
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", server.url)
    monkeypatch.setenv("LOCAL_IMAGE_API", "openai")
    # No shared Redis cooldowns between tests.
    monkeypatch.setattr(image_generation, "_cooling_down", lambda name: False)
    monkeypatch.setattr(image_generation, "_cool_down", lambda name, seconds: None)
    client = TestClient(app)
    verification_codes = {}
    monkeypatch.setattr(notifications, "send_email_verification_email",
                        lambda address, code: verification_codes.__setitem__(address, code) or True)

    tenants = []

    def company():
        email = f"jobs+{uuid.uuid4().hex[:8]}@example.com"
        signup = client.post("/auth/signup", json={"full_name": "Owner", "business_name": "Jobs Bakery", "email": email,
                                                    "country_code": "JO", "primary_currency": "JOD",
                                                    "password": "Jobs!Test-2026"})
        assert signup.status_code == 202, signup.text
        verified = client.post("/auth/email/verify", json={"email": email,
            "registration_token": signup.json()["registration_token"], "code": verification_codes[email]})
        assert verified.status_code == 200, verified.text
        session = verified.json()
        tenants.append(session["tenant_id"])
        return session, {"Authorization": f"Bearer {session['access_token']}"}

    def campaign(headers):
        created = client.post("/marketing/campaigns", json={"text": "Zaatar mix, 250 g", "strategy_type": "SALES_DRIVEN"},
                              headers=headers)
        assert created.status_code == 200, created.text
        return created.json()["campaign_id"]

    _drain()
    yield client, server, company, campaign
    _drain()
    # These jobs ran against an instant fake server: keep them out of the
    # capacity figures (seconds per image) of whatever else uses this database.
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM image_generation_jobs WHERE tenant_id = ANY(%s::uuid[]);", (tenants,))
    server.httpd.shutdown()


def _drain():
    """Leftovers of earlier runs of these tests (their companies' emails start
    with jobs+) must not be claimed here. Anyone else's queued images are
    never touched: when there are some, the tests skip instead - their worker
    claims from the shared queue and would make those images with this
    file's fake server."""
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE image_generation_jobs j SET status = 'CANCELLED'
            WHERE j.status IN ('QUEUED', 'RUNNING') AND EXISTS (
                SELECT 1 FROM tenant_users tu JOIN users u ON u.user_id = tu.user_id
                WHERE tu.tenant_id = j.tenant_id AND u.email LIKE 'jobs+%%@example.com');
            """
        )
        cursor.execute("SELECT COUNT(*) FROM image_generation_jobs WHERE status IN ('QUEUED', 'RUNNING');")
        others = cursor.fetchone()[0]
    if others:
        pytest.skip(f"{others} image job(s) of other companies are queued in this database; "
                    "run these tests against a database without a live image queue")


def _work(n=1):
    from src.ai.marketing import image_worker

    return [image_worker.run_one(f"test-worker-{uuid.uuid4().hex[:6]}") for _ in range(n)]


def _job_rows(batch_id):
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT status, attempts, next_attempt_at > NOW(), error FROM image_generation_jobs "
                       "WHERE batch_id = %s ORDER BY created_at;", (batch_id,))
        return cursor.fetchall()


def test_a_batch_of_formats_and_variations_is_made_by_the_worker(queue):
    client, server, company, campaign = queue
    _session, headers = company()
    cid = campaign(headers)
    queued = client.post(f"/marketing/campaigns/{cid}/image-batches",
                         json={"formats": ["SQUARE", "STORY", "WIDE"], "variations": 2, "channel": "INSTAGRAM"}, headers=headers)
    assert queued.status_code == 200, queued.text
    batch = queued.json()
    assert batch["queued"] == 6
    progress = client.get(f"/marketing/campaigns/{cid}/image-jobs", headers=headers).json()
    assert progress["counts"]["QUEUED"] == 6

    assert _work(7) == ["COMPLETED"] * 6 + [None]  # the 7th finds nothing
    progress = client.get(f"/marketing/campaigns/{cid}/image-jobs", params={"batch_id": batch["batch_id"]}, headers=headers).json()
    assert progress["counts"]["COMPLETED"] == 6 and all(j["asset_id"] and j["mode"] == "ai" for j in progress["jobs"])
    gallery = client.get(f"/marketing/campaigns/{cid}/assets", headers=headers).json()["assets"]
    assert sorted(a["image_format"] for a in gallery) == ["SQUARE", "SQUARE", "STORY", "STORY", "WIDE", "WIDE"]
    assert all(a["channel"] == "INSTAGRAM" for a in gallery)
    assert sum(a["attached"] for a in gallery) == 1  # the campaign had no image: the first one made is attached
    seeds = [r["seed"] for r in server.requests]
    assert len(set(seeds)) == 6  # each variation is a distinct image
    sizes = sorted({r["size"] for r in server.requests})
    assert sizes == ["1024x1024", "1344x704", "768x1344"]
    for asset in gallery:
        image = client.get(f"/marketing/campaigns/{cid}/assets/{asset['asset_id']}/image", headers=headers)
        assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"


def test_a_failing_server_is_retried_with_backoff_then_the_job_fails(queue, monkeypatch):
    from src.ai.marketing import image_jobs

    client, server, company, campaign = queue
    _session, headers = company()
    cid = campaign(headers)
    batch = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"]}, headers=headers).json()
    server.script = [500]
    assert _work(1) == ["QUEUED"]
    status, attempts, later, error = _job_rows(batch["batch_id"])[0]
    assert (status, attempts, later) == ("QUEUED", 1, True) and "No image could be made" in error
    # Due again now; two more failures use up the 3 attempts.
    for _ in range(2):
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
            cursor.execute("UPDATE image_generation_jobs SET next_attempt_at = NOW() WHERE batch_id = %s;", (batch["batch_id"],))
        server.script = [500]
        _work(1)
    assert _job_rows(batch["batch_id"])[0][:2] == ("FAILED", image_jobs.MAX_ATTEMPTS)
    # Retry from the Studio queues it again; this time it works.
    assert client.post(f"/marketing/campaigns/{cid}/image-jobs/retry", headers=headers).json()["requeued"] == 1
    assert _work(1) == ["COMPLETED"]


def test_a_busy_server_requeues_without_using_an_attempt(queue):
    client, server, company, campaign = queue
    _session, headers = company()
    cid = campaign(headers)
    batch = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["PORTRAIT"]}, headers=headers).json()
    server.script = [503]
    assert _work(1) == ["QUEUED"]
    status, attempts, later, error = _job_rows(batch["batch_id"])[0]
    assert (status, attempts, later, error) == ("QUEUED", 0, True, "Every image server was busy.")


def test_a_job_whose_worker_died_is_taken_over(queue):
    from src.ai.marketing import image_jobs

    client, _server, company, campaign = queue
    _session, headers = company()
    cid = campaign(headers)
    batch = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"]}, headers=headers).json()
    from src.ai import db

    conn = db.system_connection()
    try:
        assert image_jobs.claim(conn, "worker-that-dies") is not None
        assert image_jobs.claim(conn, "another-worker") is None  # running, heartbeat fresh: not stolen
        with conn.cursor() as cursor:
            cursor.execute("UPDATE image_generation_jobs SET heartbeat_at = NOW() - INTERVAL '1 hour' WHERE batch_id = %s;",
                           (batch["batch_id"],))
        conn.commit()
    finally:
        conn.close()
    assert _work(1) == ["COMPLETED"]
    assert _job_rows(batch["batch_id"])[0][:2] == ("COMPLETED", 2)


def test_companies_take_turns(queue):
    from src.ai import db
    from src.ai.marketing import image_jobs

    client, _server, company, campaign = queue
    big, big_headers = company()
    small, small_headers = company()
    big_cid, small_cid = campaign(big_headers), campaign(small_headers)
    client.post(f"/marketing/campaigns/{big_cid}/image-batches", json={"formats": ["SQUARE"], "variations": 3}, headers=big_headers)
    client.post(f"/marketing/campaigns/{small_cid}/image-batches", json={"formats": ["SQUARE"]}, headers=small_headers)
    conn = db.system_connection()
    try:
        order = [image_jobs.claim(conn, f"w{i}")[1] for i in range(4)]
    finally:
        conn.close()
    # The small company's only job goes second, not after the whole big batch.
    assert order[:2] in ([big["tenant_id"], small["tenant_id"]], [small["tenant_id"], big["tenant_id"]])
    assert order.count(big["tenant_id"]) == 3


def test_limits_cancel_and_capacity(queue, monkeypatch):
    from src.ai.marketing import image_jobs

    client, _server, company, campaign = queue
    _session, headers = company()
    cid = campaign(headers)
    monkeypatch.setattr(image_jobs, "BATCH_MAX", 4)
    over = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE", "STORY"], "variations": 3},
                       headers=headers)
    assert over.status_code == 429 and over.json()["detail"]["limit"] == 4
    monkeypatch.setattr(image_jobs, "QUEUE_MAX_PER_COMPANY", 5)
    assert client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"], "variations": 4},
                       headers=headers).status_code == 200
    full = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"], "variations": 2}, headers=headers)
    assert full.status_code == 429 and full.json()["detail"]["pending"] == 4
    assert client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["BANNER"]}, headers=headers).status_code == 422
    assert client.post(f"/marketing/campaigns/{cid}/image-jobs/cancel", headers=headers).json()["cancelled"] == 4
    assert _work(1) == [None]

    _work(0)
    client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"]}, headers=headers)
    assert _work(1) == ["COMPLETED"]
    capacity = client.get("/marketing/image-capacity", headers=headers).json()
    assert capacity["completed_last_hour"] >= 1 and capacity["average_seconds_per_image"] is not None
    assert capacity["self_hosted_only"] is True and capacity["uses_plan_allowance"] is False


def test_another_company_cannot_see_or_touch_the_queue(queue):
    from src.ai import db

    client, _server, company, campaign = queue
    owner, headers = company()
    cid = campaign(headers)
    batch = client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"], "variations": 2},
                        headers=headers).json()
    other, other_headers = company()
    assert client.get(f"/marketing/campaigns/{cid}/image-jobs", headers=other_headers).status_code == 404
    assert client.post(f"/marketing/campaigns/{cid}/image-batches", json={"formats": ["SQUARE"]}, headers=other_headers).status_code == 404
    assert client.post(f"/marketing/campaigns/{cid}/image-jobs/cancel", headers=other_headers).status_code == 404
    assert client.post(f"/marketing/campaigns/{cid}/image-jobs/retry", headers=other_headers).status_code == 404
    for tenant, user, expected in ((other["tenant_id"], other.get("user_id"), 0), (owner["tenant_id"], owner.get("user_id"), 2)):
        conn = db.app_role_connection(tenant, user)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM image_generation_jobs WHERE batch_id = %s;", (batch["batch_id"],))
                assert cursor.fetchone()[0] == expected
                # Even a direct update by id can't reach another company's rows.
                cursor.execute("UPDATE image_generation_jobs SET status = 'CANCELLED' WHERE batch_id = %s;", (batch["batch_id"],))
                assert cursor.rowcount == expected
            conn.rollback()
        finally:
            conn.close()


def test_hosted_providers_still_use_the_plan_allowance(monkeypatch):
    from src.ai.marketing import image_service

    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local")
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://127.0.0.1:1")
    assert image_service.uses_plan_allowance() is False
    monkeypatch.setenv("MARKETING_SELF_HOSTED_IMAGES_USE_PLAN_ALLOWANCE", "true")
    assert image_service.uses_plan_allowance() is True
    monkeypatch.delenv("MARKETING_SELF_HOSTED_IMAGES_USE_PLAN_ALLOWANCE")
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local,huggingface")
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf")
    assert image_service.uses_plan_allowance() is True
