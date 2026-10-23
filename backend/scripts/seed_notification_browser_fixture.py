"""Seed/clean one real failed-import signal for the reusable alert browser check."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import uuid

import psycopg2


STATE = Path(os.environ["KEEL_VERIFICATION_STATE"])
IMPORT_FIXTURE = STATE / "import-browser-fixture.json"
ALERT_FIXTURE = STATE / "notification-browser-fixture.json"


def cleanup() -> None:
    if not ALERT_FIXTURE.exists():
        return
    fixture = json.loads(ALERT_FIXTURE.read_text(encoding="utf-8"))
    owner = json.loads(IMPORT_FIXTURE.read_text(encoding="utf-8"))
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notification_outbox WHERE tenant_id=%s AND source_type='ingestion_job' AND source_id=%s",
            (fixture["tenant_id"], fixture["job_id"]),
        )
        cur.execute(
            "DELETE FROM ingestion_jobs WHERE job_id = %s AND tenant_id = %s AND source_id = %s",
            (fixture["job_id"], fixture["tenant_id"], fixture["source_id"]),
        )
        cur.execute(
            "DELETE FROM data_sources WHERE source_id = %s AND tenant_id = %s",
            (fixture["source_id"], fixture["tenant_id"]),
        )
        cur.execute(
            "DELETE FROM notification_reads WHERE tenant_id = %s AND user_id = %s",
            (fixture["tenant_id"], fixture.get("user_id") or owner["user"]),
        )
    ALERT_FIXTURE.unlink()


def main() -> None:
    cleanup()
    owner = json.loads(IMPORT_FIXTURE.read_text(encoding="utf-8"))
    source_id = str(uuid.uuid4())
    marker = f"KEEL-ALERT-{secrets.token_hex(6).upper()}.csv"
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        # This is the dedicated synthetic import-browser tenant. Prior CSV
        # browser runs can legitimately leave failed-import alerts for that
        # same test owner, so clear its inbox before asserting one seeded row.
        cur.execute("DELETE FROM notification_outbox WHERE tenant_id=%s", (owner["tenant"],))
        cur.execute(
            "DELETE FROM notification_reads WHERE tenant_id = %s AND user_id = %s",
            (owner["tenant"], owner["user"]),
        )
        cur.execute(
            "INSERT INTO data_sources (source_id, tenant_id, source_name, source_type) "
            "VALUES (%s, %s, 'Notification verification', 'FILE_UPLOAD')",
            (source_id, owner["tenant"]),
        )
        cur.execute(
            "INSERT INTO ingestion_jobs (tenant_id, source_id, job_status, file_name) "
            "VALUES (%s, %s, 'PROCESSING', %s) RETURNING job_id",
            (owner["tenant"], source_id, marker),
        )
        job_id = str(cur.fetchone()[0])
        # Exercise the same transactional transition the production trigger observes.
        cur.execute(
            "UPDATE ingestion_jobs SET job_status='FAILED', ended_at=NOW() "
            "WHERE job_id=%s AND tenant_id=%s",
            (job_id, owner["tenant"]),
        )
    fixture = {"tenant_id": owner["tenant"], "user_id": owner["user"], "source_id": source_id,
               "job_id": job_id, "file_name": marker}
    ALERT_FIXTURE.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print("Seeded one synthetic failed-import row for the alert browser test.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup":
        cleanup()
    else:
        main()
