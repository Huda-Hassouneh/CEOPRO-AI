"""Recoverable test suites on the existing checkout-owned Compose infrastructure.

No stored DSNs, provider credentials, fixed machine paths or business fixtures
outside the repository are required. Test services never share application data.
"""
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

import dev

TEST_SERVICES = ("test-redis", "test-storage", "test-mail")
TEST_PROCESSES = {"test-api", "test-frontend"}


def test_environment(c, name):
    if not name.startswith("keel_billing_test_dev"):
        raise dev.DevError("Test database name is outside the disposable namespace.")
    env = dev.environment(c, admin=True, external=False)
    env["DATABASE_URL"] = urlunsplit(urlsplit(env["DATABASE_URL"])._replace(path="/" + name))
    env["AI_TEST_DATABASE_URL"] = env["DATABASE_URL"]
    env["BILLING_TEST_DATABASE_URL"] = env["DATABASE_URL"]
    env["BILLING_DATABASE_TESTS"] = "1"
    for variable, key in (("BILLING_SETUP_DB_PASSWORD", "billing_setup_password"),
                          ("BILLING_WEBHOOK_DB_PASSWORD", "billing_webhook_password"),
                          ("CREDIT_ACCOUNTING_DB_PASSWORD", "credit_accounting_password")):
        if c.get(key):
            env[variable] = c[key]
    restricted = dev.environment(c, external=False)["DATABASE_URL"]
    env["SCRAPER_DATABASE_URL"] = urlunsplit(urlsplit(restricted)._replace(path="/" + name))
    env.update(AI_TEST_REDIS_HOST="127.0.0.1", AI_TEST_REDIS_PORT=env["REDIS_PORT"],
               AI_TEST_MINIO_ENDPOINT=env["MINIO_ENDPOINT"],
               AI_TEST_MINIO_ACCESS_KEY=env["MINIO_ROOT_USER"],
               AI_TEST_MINIO_SECRET_KEY=env["MINIO_ROOT_PASSWORD"],
               AI_TEST_MINIO_ROOT_USER=env["MINIO_ROOT_USER"],
               AI_TEST_MINIO_ROOT_PASSWORD=env["MINIO_ROOT_PASSWORD"],
               FRONTEND_BASE_URL="http://localhost:5173")
    # Match the backend CI job's default-origin assertions, independently of
    # the separate browser runtime's exact dynamic frontend origin.
    env["MINIO_ENDPOINT"] = "http://" + env["AI_TEST_MINIO_ENDPOINT"]
    env.pop("CORS_ALLOWED_ORIGINS", None)
    return env


def logged(args, target, env, *, cwd=None):
    with target.open("w", encoding="utf-8") as output:
        result = subprocess.run([str(a) for a in args], cwd=cwd or dev.ROOT / "backend",
                                env=env, stdout=output, stderr=subprocess.STDOUT)
    print(f"{'PASS' if result.returncode == 0 else 'FAIL'}: {target.name}; evidence: {target}", flush=True)
    if result.returncode:
        raise dev.DevError(f"{target.name} failed (exit {result.returncode}); inspect private evidence. No check was skipped.")


def published_port(c, service, internal):
    endpoint = dev.docker(c, "port", service, str(internal), capture=True).strip()
    if not endpoint.startswith("127.0.0.1:") or "\n" in endpoint:
        raise dev.DevError("Test service is not bound exclusively to one loopback port.")
    return int(endpoint.rsplit(":", 1)[1])


def cleanup(c):
    dev.check_docker()
    dev.compose_file(c)
    dev.verify_containers(c)
    dev.stop_processes(TEST_PROCESSES)
    dev.docker(c, "stop", *TEST_SERVICES)
    dev.docker(c, "rm", "-f", *TEST_SERVICES)
    print("Removed only owned test Redis/storage/mail containers. Application services, volumes, test databases and evidence retained.")


@contextlib.contextmanager
def isolated(c, suite):
    import database
    from psycopg2 import sql
    dev.ensure_billing_setup_password(c)
    dev.check_docker()
    dev.compose_file(c)
    dev.verify_containers(c)
    for name, record in dev.processes().items():
        if name in TEST_PROCESSES and dev.owned(record):
            raise dev.DevError("An earlier test runtime is still active. Inspect logs, then run test-cleanup.")
    # Discard only test container writable layers so retries start empty.
    cleanup(c)
    dev.docker(c, "up", "-d", "--wait", "--wait-timeout", "180", "postgres", *TEST_SERVICES)
    run_id = uuid.uuid4().hex[:12]
    name = "keel_billing_test_dev" + run_id
    target = dev.STATE / "evidence" / "tests" / run_id
    target.mkdir(parents=True)
    local = {**c, "ports": {**c["ports"], **dev.allocate_ports({"api": 18000, "frontend": 15173})}}
    local["ports"].update(redis=published_port(c, "test-redis", 6379),
                          storage=published_port(c, "test-storage", 9000),
                          smtp=published_port(c, "test-mail", 1025),
                          inbox=published_port(c, "test-mail", 8025))
    metadata = {"id": run_id, "database": name, "suite": suite, "ports": local["ports"],
                "revision": dev.run(["git", "rev-parse", "HEAD"], capture=True).strip(),
                "status": "preparing", "created": time.time()}
    dev.write_json(target / "run.json", metadata)
    print(f"Isolated {suite}: {name}; evidence: {target}", flush=True)
    try:
        with contextlib.closing(database.connect(c, external=False)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        ledger = dev.STATE / "test-databases.json"
        prior = json.loads(ledger.read_text()) if ledger.exists() else []
        prior.append({"name": name, "purpose": suite, "run": run_id})
        dev.write_json(ledger, prior)
        env = test_environment(local, name)
        migration = ("import os,psycopg2; from scripts.apply_migrations import run, MIGRATIONS_DIR; "
                     "c=psycopg2.connect(os.environ['DATABASE_URL']); first=run(c); "
                     "assert len(first)==len(list(MIGRATIONS_DIR.glob('*.sql'))); "
                     "assert run(c)==[]; c.close()")
        logged([dev.PYTHON, "-c", migration], target / "migrations.log", env)
        database.check(c, database=name)
        metadata["status"] = "running"
        dev.write_json(target / "run.json", metadata)
        yield local, env, target
        metadata["status"] = "passed"
    except BaseException:
        metadata["status"] = "failed-or-interrupted"
        raise
    finally:
        try:
            dev.stop_processes(TEST_PROCESSES)
            dev.docker(c, "stop", *TEST_SERVICES)
        except BaseException:
            metadata["status"] = "cleanup-failed"
            raise
        finally:
            dev.write_json(target / "run.json", metadata)
        print("Test processes/services stopped; database and private evidence retained.", flush=True)


def browser(c, env, target, suite):
    origin = f"http://127.0.0.1:{c['ports']['frontend']}"
    api = f"http://127.0.0.1:{c['ports']['api']}"
    env = dict(env, FRONTEND_BASE_URL=origin, CORS_ALLOWED_ORIGINS=origin)
    # API uses only the restricted app DSN. Tests/seeding use public APIs.
    runtime = dict(env, DATABASE_URL=env["SCRAPER_DATABASE_URL"])
    for key in ("AI_TEST_DATABASE_URL", "BILLING_TEST_DATABASE_URL", "BILLING_DATABASE_TESTS"):
        runtime.pop(key, None)
    runtime.update(KEEL_API_PROXY_TARGET=api, VITE_API_BASE_URL="/api",
                   DISCOVERY_REFRESH_ENABLED="false", NOTIFICATION_DIGEST_ENABLED="false")
    dev.start_process("test-api", [dev.PYTHON, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1",
                                   "--port", c["ports"]["api"]], c, env=runtime)
    dev.wait_for("test API database/Redis and CORS", lambda: (
        json.loads(dev.http(api + "/health/ready", origin)[0]).get("status") == "ok"
        and dev.http(api + "/health/ready", origin)[1].get("Access-Control-Allow-Origin") == origin))
    email, password = "ci-smoke@keel-ci.example", "Ci!Smoke-Only-2026"
    # Existing CI auth fixture needs its explicit administrative setup DSN
    # to bootstrap the signup trial. The running API retains ceopro_app only.
    logged([dev.PYTHON, "-m", "scripts.ci_smoke_account", "--api", api, "--email", email,
            "--password", password, "--test-email-verification-fixture"], target / "account.log", env)
    node = shutil.which("node")
    vite = dev.ROOT / "frontend/node_modules/vite/bin/vite.js"
    logged([node, vite, "build"], target / "build.log", runtime, cwd=dev.ROOT / "frontend")
    dev.start_process("test-frontend", [node, vite, "preview", "--host", "127.0.0.1", "--port",
                                        c["ports"]["frontend"], "--strictPort"], c,
                      env=runtime, cwd=dev.ROOT / "frontend")
    dev.wait_for("test frontend readiness proxy", lambda: json.loads(dev.http(origin + "/api/health/ready")[0]).get("status") == "ok")
    runtime.update(APP_URL=origin, API_URL=api, E2E_EMAIL=email, E2E_PASSWORD=password,
                   E2E_EXPECT_PLATFORM_DENIAL="true")
    chrome = dev.integrations(validate_providers=False).get("CHROMIUM_PATH") or next((shutil.which(n) for n in
              ("google-chrome", "chromium", "chromium-browser") if shutil.which(n)), None)
    if not chrome and os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base and (Path(base) / "Google/Chrome/Application/chrome.exe").exists():
                chrome = str(Path(base) / "Google/Chrome/Application/chrome.exe")
                break
    if not chrome:
        raise dev.DevError("Install Chrome/Chromium or set CHROMIUM_PATH in .dev/integrations.env. No browser checks were skipped.")
    runtime["CHROMIUM_PATH"] = chrome
    script = dev.ROOT / "frontend/tests/browser"
    logged([node, script / "run-all.mjs", *( ["a11y"] if suite == "a11y" else [])],
           target / (suite + ".log"), runtime, cwd=dev.ROOT / "frontend")
    if suite == "a11y":
        logged([node, script / "a11y.mjs"], target / "arabic-dark.log",
               dict(runtime, E2E_LOCALE="ar", E2E_WIDTH="390", E2E_THEME="dark"), cwd=dev.ROOT / "frontend")
    else:
        for locale in ("en", "ar"):
            logged([node, script / "assistant-evidence.mjs"], target / ("assistant-" + locale + ".log"),
                   dict(runtime, E2E_LOCALE=locale, E2E_WIDTH="390" if locale == "ar" else "1280"), cwd=dev.ROOT / "frontend")


def execute(c, args):
    if args.suite == "audit":
        target = dev.STATE / "evidence/audit" / uuid.uuid4().hex[:12]
        target.mkdir(parents=True, exist_ok=True)
        env = dev.environment(c, external=False)
        logged([dev.PYTHON, "-m", "pip", "check"], target / "pip-check.log", env)
        frozen = dev.run([dev.PYTHON, "-m", "pip", "freeze", "--exclude-editable"], env=env, capture=True)
        installed = target / "installed.txt"
        installed.write_text("\n".join(line for line in frozen.splitlines() if not line.lower().startswith("pip-audit==")) + "\n")
        logged([dev.PYTHON, "-m", "pip_audit", "-r", installed, "--no-deps", "--disable-pip",
                "--progress-spinner", "off"], target / "audit.log", env)
        return
    if args.suite == "backend":
        marker = dev.STATE / "dependencies.json"
        if args.pytest_args is None and (not marker.exists() or not json.loads(marker.read_text()).get("models")):
            raise dev.DevError("Full backend collection needs declared model libraries. Run setup --models first; no models are mocked.")
    with isolated(c, args.suite) as (local, env, target):
        if args.suite == "backend":
            selection = args.pytest_args if args.pytest_args is not None else ["src/", "-q"]
            logged([dev.PYTHON, "-m", "pytest", *selection, "--junitxml=" + str(target / "backend.xml")],
                   target / "backend.log", env)
        else:
            browser(local, env, target, args.suite)
