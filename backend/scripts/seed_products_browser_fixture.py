"""Create a synthetic staff principal for the reusable Products browser journey."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import uuid

import psycopg2

from src.ai.core.security import hash_password

STATE = Path(os.environ["KEEL_VERIFICATION_STATE"])
OWNER_FIXTURE = STATE / "competitor-browser-fixture.json"
PRODUCT_FIXTURE = STATE / "products-browser-fixture.json"


def main() -> None:
    owner = json.loads(OWNER_FIXTURE.read_text(encoding="utf-8"))
    email = f"products-staff+{uuid.uuid4().hex[:10]}@example.test"
    password = secrets.token_urlsafe(24)
    user_id = str(uuid.uuid4())
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id,email,password_hash,full_name,email_verified_at) "
            "VALUES (%s,%s,%s,'Synthetic Product Staff',NOW())",
            (user_id, email, hash_password(password)),
        )
        cur.execute("INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,'staff')",
                    (owner["tenant_id"], user_id))
    fixture = {"tenant_id": owner["tenant_id"], "email": email, "password": password,
               "user_id": user_id}
    PRODUCT_FIXTURE.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print("Synthetic staff browser fixture prepared; credentials were stored outside Git.")


if __name__ == "__main__":
    main()
