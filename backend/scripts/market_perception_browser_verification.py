"""Run a real MPI browser journey on uniquely disposable PostgreSQL/Redis containers.

Only synthetic test users, products, competitors, and review evidence are seeded.
The containers and temporary application logs are removed on completion.
"""
from __future__ import annotations

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
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote

import psycopg2


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _run(args: list[str], *, env=None, cwd=None, capture=False):
    result = subprocess.run(
        args, cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"verification command failed: {Path(args[0]).name} (exit {result.returncode})")
    return result.stdout.strip() if capture else ""


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(url: str, process: subprocess.Popen, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"application exited before readiness: {Path(process.args[0]).name}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"readiness timed out for {url.split('/')[2]}")


def _seed(database_url: str, jwt_secret: str) -> dict:
    os.environ["JWT_SECRET"] = jwt_secret
    from src.ai.core.security import hash_password

    suffix = secrets.token_hex(4).upper()
    tenant_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    sample_product, empty_product = str(uuid.uuid4()), str(uuid.uuid4())
    foreign_tenant, foreign_product = str(uuid.uuid4()), str(uuid.uuid4())
    competitor_id = str(uuid.uuid4())
    email, password = f"mpi-e2e-{suffix.lower()}@example.test", "MPI-Test-Only-2026!Aa"
    marker, competitor_name = f"MPI{suffix}", f"MPI{suffix} Tracked Rival"

    with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,onboarding_completed_at) "
            "VALUES(%s,'MPI E2E Company','JO','JOD',now())", (tenant_id,),
        )
        cur.execute(
            "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) "
            "VALUES(%s,%s,%s,'MPI Test Owner',now())", (user_id, email, hash_password(password)),
        )
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant_id, user_id))
        cur.execute(
            "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) "
            "VALUES(%s,'growth','active',current_date,current_date+30,'manual')", (tenant_id,),
        )
        for product_id, name in (
            (sample_product, {"en": f"{marker} Sample Product", "ar": f"{marker} Sample Product"}),
            (empty_product, {"en": f"{marker} Empty Product", "ar": f"{marker} Empty Product"}),
        ):
            cur.execute(
                "INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) "
                "VALUES(%s,%s,%s,12,'JOD')", (product_id, tenant_id, json.dumps(name)),
            )
        cur.execute(
            "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) "
            "VALUES(%s,'MPI Foreign Company','US','USD')", (foreign_tenant,),
        )
        cur.execute(
            "INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) "
            "VALUES(%s,%s,%s,12,'USD')", (foreign_product, foreign_tenant, json.dumps({"en": "Foreign Product"})),
        )
        cur.execute(
            "INSERT INTO global_competitors(global_competitor_id,competitor_name,visibility,added_by_tenant_id) "
            "VALUES(%s,%s,'PRIVATE',%s)", (competitor_id, competitor_name, tenant_id),
        )
        cur.execute(
            "INSERT INTO tenant_competitors(tenant_id,global_competitor_id,is_tracked,tier,classified_at,"
            "confidence_score,confidence_label,competitor_scope) VALUES(%s,%s,true,'RELEVANT',now(),.9,'High','BROAD_DOMAIN')",
            (tenant_id, competitor_id),
        )
        for kind, product_id, rival_id, count in (
            ("BUSINESS", None, None, 1), ("PRODUCT", sample_product, None, 1),
            ("COMPETITOR", None, competitor_id, 5),
        ):
            for _ in range(count):
                review_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO reviews(review_id,tenant_id,subject_type,product_id,competitor_id,source_platform,"
                    "review_text,review_language,review_date,collection_method,source_status,safety_status) "
                    "VALUES(%s,%s,%s,%s,%s,'SYNTHETIC','Synthetic test review','en',now()-interval '1 day',"
                    "'PUBLIC_API','ALLOWED','SAFE')", (review_id, tenant_id, kind, product_id, rival_id),
                )
                cur.execute(
                    "INSERT INTO sentiment_results(review_id,tenant_id,sentiment_label,sentiment_score,"
                    "positive_probability,neutral_probability,negative_probability,confidence,model_version) "
                    "VALUES(%s,%s,'POSITIVE',.7,.8,.1,.1,.9,'fixture-only')", (review_id, tenant_id),
                )
    return {
        "email": email, "password": password, "marker": marker,
        "competitor": competitor_name, "foreign_product": foreign_product,
    }


def main() -> int:
    docker = shutil.which("docker")
    node = shutil.which("node")
    if not docker or not node:
        raise RuntimeError("Docker and Node.js are required for this browser verification")
    chromium = os.getenv("CHROMIUM_PATH")
    if not chromium:
        candidates = list((Path.home() / "AppData/Local/ms-playwright").glob("chromium-*/chrome-win*/chrome.exe"))
        chromium = str(candidates[0]) if candidates else None
    if not chromium or not Path(chromium).exists():
        raise RuntimeError("No existing Playwright Chromium executable is available")

    run_id = secrets.token_hex(6)
    pg_name, redis_name = f"keel-mpi-pg-{run_id}", f"keel-mpi-redis-{run_id}"
    pg_password, app_password = secrets.token_hex(24), secrets.token_hex(24)
    jwt_secret = secrets.token_hex(48)
    pg_port, redis_port = _port(), _port()
    api_port, web_port = _port(), _port()
    work = Path(tempfile.mkdtemp(prefix="keel-mpi-browser-"))
    api_process = web_process = None
    api_log_handle = web_log_handle = None
    created = []
    try:
        _run([docker, "run", "-d", "--name", pg_name, "-e", "POSTGRES_USER=ceopro_admin",
              "-e", f"POSTGRES_PASSWORD={pg_password}", "-e", "POSTGRES_DB=keel_mpi_test",
              "-p", f"127.0.0.1:{pg_port}:5432", "pgvector/pgvector:pg17"])
        created.append(pg_name)
        _run([docker, "run", "-d", "--name", redis_name, "-p", f"127.0.0.1:{redis_port}:6379", "redis:7.4.11"])
        created.append(redis_name)
        for _ in range(90):
            result = subprocess.run([docker, "exec", pg_name, "pg_isready", "-U", "ceopro_admin", "-d", "keel_mpi_test"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("disposable PostgreSQL did not become ready")

        database_url = f"postgresql://ceopro_admin:{pg_password}@127.0.0.1:{pg_port}/keel_mpi_test"
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": database_url, "AI_TEST_DATABASE_URL": database_url,
            "APP_DB_PASSWORD": app_password, "JWT_SECRET": jwt_secret,
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0", "PYTHONPATH": str(BACKEND),
            "CORS_ALLOWED_ORIGINS": f"http://127.0.0.1:{web_port}",
            "VITE_API_BASE_URL": "/api", "KEEL_API_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
            "UNASSIGNED_PLAN_ACCESS": "none", "CHROMIUM_PATH": chromium,
            "API_URL": f"http://127.0.0.1:{api_port}", "APP_URL": f"http://127.0.0.1:{web_port}",
        })
        migration_env = env.copy()
        migration = subprocess.run([sys.executable, "scripts/apply_migrations.py"], cwd=BACKEND,
                                   env=migration_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if migration.returncode:
            raise RuntimeError("fresh 1-99 migration chain failed")
        repeat = subprocess.run([sys.executable, "scripts/apply_migrations.py"], cwd=BACKEND,
                                env=migration_env, capture_output=True, text=True)
        if repeat.returncode or "Applied 0 new migration(s)" not in repeat.stderr:
            raise RuntimeError("migration rerun was not a zero-change success")
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            if cur.fetchone()[0] != 99:
                raise RuntimeError("disposable database does not contain exactly migrations 1-99")
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            if not cur.fetchone():
                raise RuntimeError("pgvector extension is missing")

        fixture = _seed(database_url, jwt_secret)
        env.update({
            "E2E_EMAIL": fixture["email"], "E2E_PASSWORD": fixture["password"],
            "E2E_PRODUCT_MARKER": fixture["marker"], "E2E_COMPETITOR_NAME": fixture["competitor"],
            "E2E_FOREIGN_PRODUCT_ID": fixture["foreign_product"],
        })
        api_log, web_log = work / "api.log", work / "vite.log"
        api_log_handle, web_log_handle = api_log.open("w"), web_log.open("w")
        api_process = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                                       cwd=BACKEND, env=env, stdout=api_log_handle, stderr=api_log_handle)
        web_process = subprocess.Popen([node, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
                                       cwd=FRONTEND, env=env, stdout=web_log_handle, stderr=web_log_handle)
        _wait(f"http://127.0.0.1:{api_port}/health/ready", api_process)
        _wait(f"http://127.0.0.1:{web_port}/login", web_process)
        browser_test = FRONTEND / "tests/browser/market-perception.mjs"
        for locale in ("en", "ar"):
            browser_env = env.copy()
            browser_env["E2E_LOCALE"] = locale
            result = subprocess.run([node, str(browser_test)], cwd=FRONTEND, env=browser_env,
                                     capture_output=True, text=True, timeout=120)
            if result.returncode:
                diagnostic = (result.stdout + "\n" + result.stderr)[-4000:]
                raise RuntimeError(f"{locale} browser journey failed: {diagnostic}")
            print(f"PASS Chromium Market Perception journey: {locale}")
        print("PASS FastAPI /health/ready; disposable migrations 1-99; migration rerun applied zero")
        return 0
    finally:
        for process in (web_process, api_process):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
        for handle in (web_log_handle, api_log_handle):
            if handle:
                handle.close()
        if created:
            subprocess.run([docker, "rm", "-f", *created], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Market Perception browser verification blocked/failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
