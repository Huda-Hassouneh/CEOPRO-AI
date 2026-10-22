"""Verify canonical file import against uniquely disposable PostgreSQL/Redis and Chromium."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import jwt
import psycopg2


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str], capture=False) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=capture, timeout=300)
    if result.returncode:
        details = ""
        if capture:
            details = (result.stdout + "\n" + result.stderr)[-12000:]
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}). {details}")
    return result


def _wait(url: str, process: subprocess.Popen, timeout: int = 90) -> None:
    from urllib.request import urlopen

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited before readiness: {Path(process.args[0]).name}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"readiness timed out: {url.split('/')[2]}")


def _wait_postgres(docker: str, container: str) -> None:
    for _ in range(90):
        check = subprocess.run([docker, "exec", container, "pg_isready", "-U", "ceopro_admin", "-d", "keel_import_test"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _seed(database_url: str, jwt_secret: str) -> dict[str, str]:
    os.environ["JWT_SECRET"] = jwt_secret
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from src.ai.core.security import hash_password

    suffix = secrets.token_hex(5).upper()
    tenant, user = str(uuid.uuid4()), str(uuid.uuid4())
    other_tenant, other_user = str(uuid.uuid4()), str(uuid.uuid4())
    markers = {key: f"FILE{suffix}_{key.upper()}" for key in ("valid", "retry", "corrected", "arabic", "invalid")}
    password = f"File-Import-{secrets.token_urlsafe(18)}-Aa9!"
    email = f"file-import-{suffix.lower()}@example.test"
    products = {key: str(uuid.uuid4()) for key in markers}

    with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,onboarding_completed_at)
                       VALUES(%s,%s,'JO','JOD',now())""", (tenant, f"Import verification {suffix}"))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(%s,%s,%s,%s,now())",
                    (user, email, hash_password(password), "Import Verification Owner"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, user))
        cur.execute("""INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source)
                       VALUES(%s,'growth','active',current_date,current_date+30,'manual')""", (tenant,))
        for key, product_id in products.items():
            cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) VALUES(%s,%s,%s::jsonb,6.25,'JOD','MANUAL')",
                        (product_id, tenant, json.dumps({"en": markers[key], "ar": markers[key]})))
        # A real older canonical sale keeps the Dashboard out of first-time
        # setup while the 7/30/90-day charts still have no current sales.
        old_product, old_invoice = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) VALUES(%s,%s,%s::jsonb,10,'JOD','MANUAL')",
                    (old_product, tenant, json.dumps({"en": "Historical sale", "ar": "Historical sale"})))
        cur.execute("INSERT INTO invoices(invoice_id,tenant_id,invoice_number,issue_date,subtotal,total_amount,currency,payment_status) VALUES(%s,%s,%s,current_date-120,20,20,'JOD','PAID')",
                    (old_invoice, tenant, f"HIST-{suffix}"))
        cur.execute("INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) VALUES(%s,%s,%s,2,10,20)",
                    (tenant, old_invoice, old_product))
        cur.execute("INSERT INTO transactions(tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,transaction_date) VALUES(%s,%s,2,10,20,'JOD',current_date-120)",
                    (tenant, old_product))
        pending_product = str(uuid.uuid4())
        cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) VALUES(%s,%s,%s::jsonb,10,'JOD','MANUAL')",
                    (pending_product, tenant, json.dumps({"en": "Unsettled invoice", "ar": "Unsettled invoice"})))
        for status, amount in (("UNPAID", 100), ("CANCELLED", 200)):
            invoice_id = str(uuid.uuid4())
            cur.execute("INSERT INTO invoices(invoice_id,tenant_id,invoice_number,issue_date,subtotal,total_amount,currency,payment_status) VALUES(%s,%s,%s,current_date-2,%s,%s,'JOD',%s)",
                        (invoice_id, tenant, f"{status}-{suffix}", amount, amount, status))
            cur.execute("INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) VALUES(%s,%s,%s,%s,10,%s)",
                        (tenant, invoice_id, pending_product, amount // 10, amount))
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,onboarding_completed_at) VALUES(%s,'Other import tenant','US','USD',now())",
                    (other_tenant,))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(%s,%s,'test-only','Other tenant owner',now())",
                    (other_user, f"other-file-import-{suffix.lower()}@example.test"))
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (other_tenant, other_user))
        cur.execute("SELECT limit_value FROM usage_plan_limits WHERE plan_key='growth' AND feature_code='document_extraction'")
        if cur.fetchone() is None:
            raise RuntimeError("disposable Growth plan is missing the established document_extraction limit")

    other_token = jwt.encode({"tenant_id": other_tenant, "user_id": other_user, "exp": int(time.time()) + 3600},
                             jwt_secret, algorithm="HS256")
    return {"tenant": tenant, "user": user, "other_tenant": other_tenant, "email": email, "password": password,
            "other_token": other_token, **markers, **{f"product_{key}": value for key, value in products.items()}}


def main() -> int:
    disk_free = shutil.disk_usage("C:\\").free
    if disk_free < 5 * 1024**3:
        raise RuntimeError(f"C: has only {disk_free / 1024**3:.2f} GB free; resource-safety rule stops disposable tests below 5 GB")
    docker, node = shutil.which("docker"), shutil.which("node")
    if not docker or not node:
        raise RuntimeError("Docker and Node.js are required; no disposable services were created")
    chromium = os.getenv("CHROMIUM_PATH")
    if not chromium:
        matches = list((Path.home() / "AppData/Local/ms-playwright").glob("chromium-*/chrome-win*/chrome.exe"))
        chromium = str(matches[0]) if matches else None
    if not chromium or not Path(chromium).exists():
        raise RuntimeError("No existing Chromium installation is available; dependencies were not installed")
    if importlib.util.find_spec("pytest") is None:
        raise RuntimeError("Current isolated Python environment lacks pytest; dependencies were not installed")

    run_id = secrets.token_hex(6)
    pg_name, redis_name = f"keel-file-pg-{run_id}", f"keel-file-redis-{run_id}"
    pg_password, app_password, jwt_secret = secrets.token_hex(24), secrets.token_hex(24), secrets.token_hex(48)
    pg_port, redis_port, api_port, web_port = (_port() for _ in range(4))
    work = Path(tempfile.mkdtemp(prefix="keel-file-import-e2e-"))
    created: list[str] = []
    api_process = web_process = None
    handles = []
    fixture = None
    try:
        _run([docker, "run", "-d", "--name", pg_name, "-e", "POSTGRES_USER=ceopro_admin",
              "-e", f"POSTGRES_PASSWORD={pg_password}", "-e", "POSTGRES_DB=keel_import_test",
              "-p", f"127.0.0.1:{pg_port}:5432", "pgvector/pgvector:pg17"], cwd=ROOT, env=os.environ.copy())
        created.append(pg_name)
        _run([docker, "run", "-d", "--name", redis_name, "-p", f"127.0.0.1:{redis_port}:6379", "redis:7.4.11"],
             cwd=ROOT, env=os.environ.copy())
        created.append(redis_name)
        _wait_postgres(docker, pg_name)

        database_url = f"postgresql://ceopro_admin:{pg_password}@127.0.0.1:{pg_port}/keel_import_test"
        env = os.environ.copy()
        env.update({"DATABASE_URL": database_url, "AI_TEST_DATABASE_URL": database_url,
                    "APP_DB_PASSWORD": app_password, "JWT_SECRET": jwt_secret,
                    "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0", "PYTHONPATH": str(BACKEND),
                    "REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(redis_port),
                    "CORS_ALLOWED_ORIGINS": f"http://127.0.0.1:{web_port}",
                    "VITE_API_BASE_URL": "/api", "KEEL_API_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
                    "UNASSIGNED_PLAN_ACCESS": "none", "CHROMIUM_PATH": chromium,
                    "API_URL": f"http://127.0.0.1:{api_port}", "APP_URL": f"http://127.0.0.1:{web_port}",
                    "FORECAST_AUTO_REFRESH": "0", "MAX_UPLOAD_SIZE_BYTES": str(10 * 1024 * 1024)})
        try:
            _run([sys.executable, "scripts/apply_migrations.py"], cwd=BACKEND, env=env)
        except RuntimeError:
            logs = subprocess.run([docker, "logs", pg_name], text=True, capture_output=True)
            print("Disposable PostgreSQL log tail (credentials are not included):")
            print((logs.stdout + "\n" + logs.stderr)[-5000:])
            raise
        repeat = subprocess.run([sys.executable, "scripts/apply_migrations.py"], cwd=BACKEND, env=env,
                                text=True, capture_output=True, timeout=180)
        if repeat.returncode or "Applied 0 new migration(s)" not in repeat.stderr:
            raise RuntimeError("migration rerun did not report zero new migrations")
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            if cur.fetchone()[0] != 99:
                raise RuntimeError("fresh disposable database did not apply exactly migrations 1-99")
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            if not cur.fetchone():
                raise RuntimeError("pgvector extension was not installed in disposable PostgreSQL")

        native_paths = [
            "src/ai/tests/test_extraction_promotion_integration_db.py",
            "src/ai/tests/test_extraction_ingestion_pipeline_integration_db.py",
            "src/ai/tests/test_import_drafts_http_integration_db.py",
            "src/ai/tests/test_recent_imports_integration_db.py",
            "src/ai/tests/test_dashboard_metrics_integration_db.py",
            "src/ai/tests/test_command_center_cache_integration_db.py",
        ]
        # These legacy DB tests intentionally seed no subscription assignment
        # and rely on the test-only default plan contract documented in conftest.
        # Keep the actual FastAPI process on the production-safe "none" policy.
        test_env = env.copy()
        test_env["UNASSIGNED_PLAN_ACCESS"] = "default"
        native = _run([sys.executable, "-m", "pytest", "-q", "--tb=short", "--no-header", *native_paths],
                      cwd=BACKEND, env=test_env, capture=True)
        print("Focused native pytest result:")
        print((native.stdout + "\n" + native.stderr)[-10000:])

        fixture = _seed(database_url, jwt_secret)
        env.update({"E2E_EMAIL": fixture["email"], "E2E_PASSWORD": fixture["password"],
                    "E2E_OTHER_TENANT_TOKEN": fixture["other_token"],
                    "E2E_VALID_MARKER": fixture["valid"], "E2E_RETRY_MARKER": fixture["retry"],
                    "E2E_CORRECTED_MARKER": fixture["corrected"], "E2E_ARABIC_MARKER": fixture["arabic"],
                    "E2E_INVALID_MARKER": fixture["invalid"]})
        api_log, web_log = work / "api.log", work / "vite.log"
        api_handle, web_handle = api_log.open("w", encoding="utf-8"), web_log.open("w", encoding="utf-8")
        handles.extend((api_handle, web_handle))
        api_process = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                                       cwd=BACKEND, env=env, stdout=api_handle, stderr=api_handle)
        web_process = subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
                                       cwd=FRONTEND, env=env, stdout=web_handle, stderr=web_handle)
        _wait(f"http://127.0.0.1:{api_port}/health/ready", api_process)
        _wait(f"http://127.0.0.1:{web_port}/login", web_process)

        for locale in ("en", "ar"):
            browser_env = env.copy()
            browser_env["E2E_LOCALE"] = locale
            _run([node, "tests/browser/data-import.mjs"], cwd=FRONTEND, env=browser_env)

        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            tenant = fixture["tenant"]
            product_ids = [fixture[f"product_{key}"] for key in ("valid", "retry", "corrected", "arabic", "invalid")]
            cur.execute("SELECT product_id,current_price,currency FROM products WHERE tenant_id=%s AND product_id=ANY(%s::uuid[])",
                        (tenant, product_ids))
            seeded = cur.fetchall()
            if len(seeded) != len(product_ids) or any(str(pid) not in product_ids or currency != "JOD" for pid, _price, currency in seeded):
                raise RuntimeError("seeded tenant product catalog changed unexpectedly")
            cur.execute("SELECT count(*),sum(quantity_sold),sum(total_price),count(DISTINCT product_id) FROM transactions WHERE tenant_id=%s AND product_id=ANY(%s::uuid[])",
                        (tenant, product_ids))
            tx_count, quantity, total, distinct_products = cur.fetchone()
            if tx_count != 4 or quantity != 8 or total != 50 or distinct_products != 4:
                raise RuntimeError(f"canonical sales integrity mismatch: count={tx_count}, quantity={quantity}, total={total}, products={distinct_products}")
            cur.execute("SELECT count(*) FROM invoice_items ii JOIN invoices i ON i.tenant_id=ii.tenant_id AND i.invoice_id=ii.invoice_id WHERE ii.tenant_id=%s AND ii.product_id=ANY(%s::uuid[])",
                        (tenant, product_ids))
            if cur.fetchone()[0] != 4:
                raise RuntimeError("canonical invoice mirrors do not match the four posted sales rows")
            cur.execute("SELECT count(*),sum(total_amount) FROM invoices WHERE tenant_id=%s AND payment_status='PAID' AND issue_date>=current_date-29",
                        (tenant,))
            invoice_count, invoice_revenue = cur.fetchone()
            if invoice_count != 4 or invoice_revenue != 50:
                raise RuntimeError(f"dashboard invoice source mismatch: count={invoice_count}, revenue={invoice_revenue}")
            cur.execute("""SELECT sum(ii.quantity),sum(ii.total_price) FROM invoice_items ii
                           JOIN invoices i ON i.tenant_id=ii.tenant_id AND i.invoice_id=ii.invoice_id
                           WHERE ii.tenant_id=%s AND i.payment_status='PAID' AND i.issue_date>=current_date-29""", (tenant,))
            invoice_units, item_revenue = cur.fetchone()
            if invoice_units != 8 or item_revenue != 50:
                raise RuntimeError(f"dashboard item source mismatch: units={invoice_units}, revenue={item_revenue}")
            cur.execute("SELECT count(*) FROM import_staging_rows s JOIN ingestion_jobs j ON j.tenant_id=s.tenant_id AND j.job_id=s.job_id WHERE s.tenant_id=%s AND s.validation_status='COMMITTED' AND s.committed_table='transactions' AND s.committed_record_id IS NOT NULL", (tenant,))
            if cur.fetchone()[0] != 4:
                raise RuntimeError("staging rows do not preserve transaction posting provenance")
            cur.execute("SELECT count(*) FROM data_sources WHERE tenant_id=%s AND source_type='OWN_SYSTEM_CONNECTOR' AND is_active=true", (tenant,))
            if cur.fetchone()[0] != 0:
                raise RuntimeError("one-time file uploads consumed a persistent connector slot")
            cur.execute("SELECT count(*) FROM import_staging_rows s JOIN ingestion_jobs j ON j.tenant_id=s.tenant_id AND j.job_id=s.job_id WHERE s.tenant_id=%s AND j.file_name=%s AND s.validation_status<>'COMMITTED'",
                        (tenant, f"{fixture['invalid']}.csv"))
            if cur.fetchone()[0] != 1:
                raise RuntimeError("invalid row was not retained as noncanonical staging evidence")
        with psycopg2.connect(host="127.0.0.1", port=pg_port, dbname="keel_import_test",
                              user="ceopro_app", password=app_password) as app_conn, app_conn.cursor() as app_cur:
            app_cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",
                            (fixture["tenant"], fixture["user"]))
            app_cur.execute("SELECT count(*),sum(total_amount) FROM invoices WHERE payment_status='PAID' AND issue_date>=current_date-29")
            if app_cur.fetchone() != (4, 50):
                raise RuntimeError("restricted role could not read its own canonical dashboard invoices")
            app_cur.execute("SELECT set_config('app.current_tenant_id',%s,true)", (fixture["other_tenant"],))
            app_cur.execute("SELECT count(*) FROM invoices")
            if app_cur.fetchone()[0] != 0:
                raise RuntimeError("restricted role exposed invoices after switching to an unauthorized tenant")
        print("PASS actual database inspection: four sales transactions and invoice mirrors; 30-day invoices=4, revenue=50 JOD, units=8; restricted ceopro_app tenant isolation; staging provenance and invalid row retention; upload source consumed no persistent connector slot.")
        print("PASS FastAPI /health/ready; PostgreSQL 17/pgvector 1-99; authenticated React/Chromium en+ar flow.")
        return 0
    finally:
        for process in (web_process, api_process):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for handle in handles:
            handle.close()
        if created:
            subprocess.run([docker, "rm", "-f", *created], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
