"""Checkout-scoped local orchestration. No business rules or provider mutations."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".dev"
PYTHON = STATE / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
WORKERS = {
    "forecast": "src.ai.forecasting.consumer",
    "images": "src.ai.marketing.image_worker",
    "connectors": "src.market_scraper.connector_worker",
    "prices": "src.market_scraper.worker",
    "analysis": "src.market_scraper.analysis_worker",
    "discovery": "src.market_scraper.discovery_worker",
    "enrichment": "src.market_scraper.enrichment_worker",
    "maintenance": "src.market_scraper.maintenance",
}
CORE = ["forecast", "images", "connectors"]
PORTS = {"api": 8000, "frontend": 5173, "postgres": 55432, "redis": 56379,
         "storage": 59000, "console": 59001, "smtp": 51025, "inbox": 58025,
         "prices_metrics": 59108, "maintenance_metrics": 59109}
MANAGED = {
    "DATABASE_URL", "APP_DB_PASSWORD", "SCRAPER_DATABASE_URL", "JWT_SECRET",
    "CREDENTIAL_VAULT_MASTER_KEY", "REDIS_URL", "REDIS_HOST", "REDIS_PORT",
    "REDIS_PASSWORD", "REDIS_TLS", "MINIO_ENDPOINT", "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD", "SMTP_HOST", "SMTP_PORT", "SMTP_USE_TLS", "SMTP_USERNAME",
    "SMTP_PASSWORD", "EMAIL_LOG_UNSENT_BODIES", "FRONTEND_BASE_URL",
    "CORS_ALLOWED_ORIGINS", "VITE_API_BASE_URL", "KEEL_API_PROXY_TARGET",
    "SCRAPER_METRICS_PORT", "SCRAPER_MAINTENANCE_METRICS_PORT",
    "AI_SERVICE_ACTOR_USER_ID", "SCRAPER_ACTOR_USER_ID", "SENTRY_ENVIRONMENT",
    "KEEL_ALLOW_DISPOSABLE_PROVIDER_PROMOTION", "KEEL_DEV_ISOLATED",
}


class DevError(RuntimeError):
    pass


def run(args, *, cwd=ROOT, env=None, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, text=True,
                            encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        # Captured commands may contain provider diagnostics or credentials: keep errors local.
        raise DevError(f"{Path(str(args[0])).name} failed (exit {result.returncode}). "
                       "Inspect the command output above and local logs; no success was assumed.")
    return result.stdout if capture else ""


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def linked(path):
    import stat
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def private_state():
    if linked(STATE):
        raise DevError(".dev is a link/junction. Preserve it and use a separate checkout-local state directory.")
    STATE.mkdir(exist_ok=True)
    if os.name == "nt":
        # DACL only; avoids Set-Acl's SeSecurityPrivilege/SACL failure.
        import csv
        row = next(csv.reader(run(["whoami", "/user", "/fo", "csv", "/nh"], capture=True).splitlines()))
        run(["icacls", str(STATE), "/inheritance:r", "/grant:r",
             f"*{row[1]}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture=True)
    else:
        STATE.chmod(0o700)


def available(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def allocate_ports(preferred=PORTS):
    selected = {}
    for name, start in preferred.items():
        port = start
        while port in selected.values() or not available(port):
            port += 1
        selected[name] = port
    return selected


def config():
    path = STATE / "config.json"
    if not path.exists():
        raise DevError("Local configuration is missing. Run dev.ps1 setup (or bash dev.sh setup).")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("root") != str(ROOT) or not re.fullmatch(r"[a-f0-9]{12}", value.get("id", "")):
        raise DevError("Configuration belongs to another checkout. Do not reuse its .dev directory.")
    if set(value["ports"]) != set(PORTS) or len(set(value["ports"].values())) != len(PORTS):
        raise DevError("Invalid or duplicate development ports in .dev/config.json.")
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in value["ports"].values()):
        raise DevError("Development ports must be integers between 1024 and 65535.")
    return value


def integrations():
    path = STATE / "integrations.env"
    values = {}
    if path.exists():
        for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise DevError(f"Invalid integrations.env line {number}; use NAME=value, no shell syntax.")
            if key in MANAGED or key.startswith(("KEEL_DEV_", "POSTGRES_", "KEEL_ALLOW_")):
                raise DevError(f"{key} is managed locally; integrations.env cannot redirect infrastructure.")
            value = value.strip().strip("'\"")
            if value:
                values[key] = value
    key = values.get("STRIPE_SECRET_KEY", "")
    if key and not key.startswith(("sk_test_", "rk_test_")):
        raise DevError("Only Stripe TEST MODE keys are accepted by local development tooling.")
    if bool(key) != bool(values.get("STRIPE_WEBHOOK_SECRET")):
        raise DevError("Configure both Stripe TEST key and listener webhook secret, or neither.")
    if values.get("STRIPE_WEBHOOK_SECRET") and not values["STRIPE_WEBHOOK_SECRET"].startswith("whsec_"):
        raise DevError("Use the signing secret from your actual Stripe CLI listener.")
    return values


def environment(c, *, admin=False):
    # Do not inherit an existing production/provider .env or another runtime's DB settings.
    safe_names = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                  "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL",
                  "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
                  "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CERT")
    env = {k: v for k, v in os.environ.items() if k.upper() in {s.upper() for s in safe_names}}
    p = c["ports"]
    user = "keel_dev_admin" if admin else "ceopro_app"
    password = c["admin_password"] if admin else c["app_password"]
    db = f"postgresql://{user}:{password}@127.0.0.1:{p['postgres']}/keel_dev_{c['id']}"
    actor = "00000000-0000-0000-0000-000000000000"  # existing restricted service principal
    env.update({
        "DATABASE_URL": db, "APP_DB_PASSWORD": c["app_password"],
        "SCRAPER_DATABASE_URL": db, "JWT_SECRET": c["jwt"],
        "CREDENTIAL_VAULT_MASTER_KEY": c["vault"],
        "REDIS_URL": f"redis://127.0.0.1:{p['redis']}/0",
        "REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(p["redis"]),
        "MINIO_ENDPOINT": f"127.0.0.1:{p['storage']}", "MINIO_ROOT_USER": "keeldev",
        "MINIO_ROOT_PASSWORD": c["storage_password"],
        "SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(p["smtp"]), "SMTP_USE_TLS": "false",
        "EMAIL_FROM_ADDRESS": "local@keel.example", "EMAIL_LOG_UNSENT_BODIES": "false",
        "FRONTEND_BASE_URL": f"http://127.0.0.1:{p['frontend']}",
        "CORS_ALLOWED_ORIGINS": f"http://127.0.0.1:{p['frontend']}",
        "KEEL_DEV_ISOLATED": "1", "VITE_API_BASE_URL": "/api", "KEEL_API_PROXY_TARGET": f"http://127.0.0.1:{p['api']}",
        "SCRAPER_METRICS_PORT": str(p["prices_metrics"]),
        "SCRAPER_MAINTENANCE_METRICS_PORT": str(p["maintenance_metrics"]),
        "AI_SERVICE_ACTOR_USER_ID": actor, "SCRAPER_ACTOR_USER_ID": actor,
        "SENTRY_ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8", "API_DOCS_ENABLED": "true",
    })
    env.update(integrations())
    return env


def compose_file(c):
    p = c["ports"]
    labels = {"com.keel.dev.root": str(ROOT), "com.keel.dev.id": c["id"]}
    def service(image, name, internal, volume=None, command=None):
        value = {"image": image, "labels": labels,
                 "ports": [f"127.0.0.1:{p[name]}:{internal}"]}
        if volume:
            value["volumes"] = [f"{volume}:/data"]
        if command:
            value["command"] = command
        return value
    pg = service("pgvector/pgvector:pg17", "postgres", 5432)
    pg.update({
        "environment": {"POSTGRES_USER": "keel_dev_admin",
                        "POSTGRES_PASSWORD": c["admin_password"], "POSTGRES_DB": f"keel_dev_{c['id']}"},
        "volumes": ["postgres:/var/lib/postgresql/data"],
        "healthcheck": {"test": ["CMD-SHELL", f"pg_isready -U keel_dev_admin -d keel_dev_{c['id']}"],
                        "interval": "2s", "timeout": "3s", "retries": 40}})
    redis = service("redis:7-alpine", "redis", 6379, "redis")
    redis["healthcheck"] = {"test": ["CMD", "redis-cli", "ping"], "interval": "2s", "timeout": "3s", "retries": 30}
    storage = service("keel-dev-minio:source", "storage", 9000, "storage",
                      ["server", "/data", "--console-address", ":9001"])
    storage.update({
        "build": {"context": str(ROOT / "backend"), "dockerfile": "src/infrastructure/Dockerfile.minio"},
        "environment": {"MINIO_ROOT_USER": "keeldev", "MINIO_ROOT_PASSWORD": c["storage_password"]},
        "healthcheck": {"test": ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"],
                        "interval": "3s", "timeout": "3s", "retries": 40}})
    storage.pop("image")  # Compose builds a checkout-project image; no nonexistent registry pull.
    storage["ports"].append(f"127.0.0.1:{p['console']}:9001")
    mail = service("axllent/mailpit:latest", "smtp", 1025)
    mail["ports"].append(f"127.0.0.1:{p['inbox']}:8025")
    mail["healthcheck"] = {"test": ["CMD", "/mailpit", "readyz"], "interval": "3s", "timeout": "3s", "retries": 30}
    value = {"services": {"postgres": pg, "redis": redis, "storage": storage, "mail": mail},
             "volumes": {n: {"labels": labels} for n in ("postgres", "redis", "storage")}}
    write_json(STATE / "compose.json", value)


def docker_base():
    """Never send development mutations to a remote Docker context."""
    override = os.environ.get("DOCKER_HOST", "")
    if override and not override.startswith(("npipe://", "unix://")):
        raise DevError("Remote/TCP DOCKER_HOST is unsupported. Select an authorized local Docker context; no context was changed.")
    name = run(["docker", "context", "show"], capture=True).strip()
    details = json.loads(run(["docker", "context", "inspect", name], capture=True))
    endpoint = details[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith(("npipe://", "unix://")):
        raise DevError("Development requires a local named-pipe/Unix Docker context. Remote/TCP/SSH contexts are never used.")
    return ["docker", "--context", name]


def docker(c, *args, capture=False):
    return run([*docker_base(), "compose", "--project-name", f"keeldev{c['id']}",
                "--project-directory", ROOT, "-f", STATE / "compose.json", *args], capture=capture)


def check_docker():
    try:
        base = docker_base()
        if run([*base, "info", "--format", "{{.OSType}}"], capture=True).strip() != "linux":
            raise DevError("Use Docker Linux containers for PostgreSQL/Redis/MinIO.")
        version = run([*base, "compose", "version", "--short"], capture=True)
        match = re.search(r"(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (2, 20):
            raise DevError("Docker Compose 2.20+ is required for readiness waiting.")
    except (DevError, FileNotFoundError):
        raise DevError("Docker Desktop/Engine with Linux containers and Compose 2.20+ is required. "
                       "Start Docker Desktop and run doctor. Existing containers were not changed.") from None


def verify_containers(c):
    base = docker_base()
    ids = run([*base, "ps", "-aq", "--filter", f"label=com.docker.compose.project=keeldev{c['id']}"], capture=True).split()
    if ids:
        for item in json.loads(run([*base, "inspect", *ids], capture=True)):
            labels = item["Config"].get("Labels") or {}
            if labels.get("com.keel.dev.root") != str(ROOT) or labels.get("com.keel.dev.id") != c["id"]:
                raise DevError("Compose project ownership mismatch; refusing to change containers.")


    volumes = run([*base, "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project=keeldev{c['id']}"], capture=True).split()
    if volumes:
        for volume in json.loads(run([*base, "volume", "inspect", *volumes], capture=True)):
            labels = volume.get("Labels") or {}
            if labels.get("com.keel.dev.root") != str(ROOT) or labels.get("com.keel.dev.id") != c["id"]:
                raise DevError("Compose volume ownership mismatch; refusing to mount it.")


def processes():
    path = STATE / "processes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def owned(record):
    import psutil
    try:
        process = psutil.Process(record["pid"])
        return (abs(process.create_time() - record["created"]) < 0.01
                and process.exe() == record["exe"] and process.cmdline() == record["cmd"])
    except (psutil.Error, KeyError):
        return False


def start_process(name, args, c):
    import psutil
    records = processes()
    record = records.get(name)
    revision = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    if record and owned(record):
        if record.get("revision") != revision:
            raise DevError(f"{name} serves a different source revision. Run restart before reusing it.")
        return
    log = STATE / "logs" / f"{name}.log"
    log.parent.mkdir(exist_ok=True)
    # Truncate only this stopped owned service's log. Logs can contain synthetic PII: keep local.
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen([str(a) for a in args], cwd=ROOT / ("frontend" if name == "frontend" else "backend"),
                                   env=environment(c), stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                   start_new_session=os.name != "nt")
    time.sleep(0.15)
    if process.poll() is not None:
        raise DevError(f"{name} exited immediately. Inspect .dev/logs/{name}.log.")
    p = psutil.Process(process.pid)
    records[name] = {"pid": p.pid, "created": p.create_time(), "exe": p.exe(), "cmd": p.cmdline(), "revision": revision}
    write_json(STATE / "processes.json", records)


def http(url, origin=None):
    request = urllib.request.Request(url, headers={"Origin": origin} if origin else {})
    # Local requests must never go through a corporate/outbound proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
        return response.read().decode("utf-8"), response.headers


def wait_for(description, check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                print(f"OK  {description}", flush=True)
                return
        except DevError:
            raise
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(1)
    raise DevError(f"{description} did not become ready. Run logs and doctor; partial startup is preserved for diagnosis.")


def database(c, action):
    args = [str(PYTHON), str(ROOT / "tools/dev/database.py"), action]
    if action != "migrate":
        run(args, cwd=ROOT / "backend", env=environment(c, admin=True))
        return
    log = STATE / "logs/migrations.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(args, cwd=ROOT / "backend", env=environment(c, admin=True),
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise DevError("Migration runner failed. Inspect logs --service migrations; no migration success assumed.")
    print(log.read_text(encoding="utf-8").splitlines()[-1])


def runtime_pids(record):
    """Windows venv launchers may delegate to a base-interpreter child."""
    import psutil
    if not owned(record):
        return set()
    return {record["pid"], *(p.pid for p in psutil.Process(record["pid"]).children(recursive=True))}


def worker_ready(name, c):
    record = processes().get(name)
    if not record or not owned(record):
        return False
    text = (STATE / "logs" / f"{name}.log").read_text(encoding="utf-8", errors="replace")
    if any(marker in text for marker in ("Traceback (most recent call last)", "ModuleNotFoundError", "claim failed",
                                         "discovery pass failed", "maintenance run failed", "heartbeat failed")):
        raise DevError(f"{name} reported a startup error; inspect its log.")
    import psycopg2
    import redis
    pids = runtime_pids(record)
    env = environment(c)
    if name == "images":
        with psycopg2.connect(env["DATABASE_URL"], connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM image_workers WHERE worker_id LIKE ANY(%s) AND heartbeat_at > now() - interval '60 seconds')", ([f"%:{pid}" for pid in pids],))
            return cur.fetchone()[0]
    if name == "connectors":
        return "Connector worker online" in text
    if name == "maintenance":
        return "market maintenance result:" in text
    if name == "prices":
        return "listening on" in text and "python_info" in http(f"http://127.0.0.1:{c['ports']['prices_metrics']}/metrics")[0]
    mapping = {
        "forecast": ("ceopro:stream:demand_forecast_requested", "ceopro-ai-forecast-engine"),
        "analysis": ("market.analysis.requested", "ceopro-market-analysis"),
        "discovery": ("market.discovery.requested", "ceopro-market-discovery"),
        "enrichment": ("market.enrichment.requested", "ceopro-market-enrichment"),
    }
    stream, group = mapping[name]
    client = redis.Redis.from_url(env["REDIS_URL"], decode_responses=True)
    try:
        return any(x["name"].endswith("-" + str(pid)) for x in client.xinfo_consumers(stream, group) for pid in pids)
    except redis.ResponseError:
        return False
    finally:
        client.close()


def capabilities():
    values = integrations()
    for label, keys in {
        "Stripe TEST Checkout": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
        "Shopify OAuth": ["SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"],
        "AI assistant (Groq)": ["GROQ_API_KEY"],
        "External market search (Tavily)": ["TAVILY_API_KEY"],
    }.items():
        print(f"{label}: " + ("configured; provider/cost verification still required" if all(values.get(k) for k in keys)
                             else "UNAVAILABLE / not configured"))
    print("WooCommerce: requires a tenant's verified test-store connection; none is created by setup.")
    print("Local sentiment/semantic RAG: setup --models installs libraries; first use may download weights.")
    print("Pricing/paid AI require verified financial configuration. Setup creates no rates, offers or paid rights.")


def setup(args):
    if sys.platform not in ("win32", "linux", "darwin"):
        raise DevError("Supported local platforms are Windows, Linux and macOS.")
    if sys.maxsize <= 2 ** 32:
        raise DevError("Install 64-bit CPython 3.11/3.12; 32-bit ML dependencies are not supported.")
    if not (3, 11) <= sys.version_info[:2] <= (3, 12):
        raise DevError("Use CPython 3.11 or 3.12 (64-bit), then rerun setup.")
    node = run(["node", "--version"], capture=True).strip().lstrip("v").split(".")
    if not (int(node[0]) >= 22 and (int(node[0]) != 22 or int(node[1]) >= 12)):
        raise DevError("Vite 8 requires Node 22.12+; Node 24 LTS is recommended.")
    run(["git", "--version"], capture=True)
    check_docker()
    private_state()
    if not (STATE / "config.json").exists():
        c = {"root": str(ROOT), "id": secrets.token_hex(6), "ports": allocate_ports(),
             "admin_password": secrets.token_hex(24), "app_password": secrets.token_hex(24),
             "storage_password": secrets.token_hex(24), "jwt": secrets.token_hex(32),
             "vault": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}
        write_json(STATE / "config.json", c)
    c = config()
    new_venv = not PYTHON.exists()
    if new_venv:
        run([sys.executable, "-m", "venv", STATE / "venv"])
    manifest = ROOT / "tools/dev/requirements.txt"
    source = [manifest, ROOT / "backend/src/ai/requirements.txt", ROOT / "backend/src/market_scraper/requirements.txt"]
    fingerprint = hashlib.sha256(b"".join(x.read_bytes() for x in source)).hexdigest()
    marker = STATE / "dependencies.json"
    prior = json.loads(marker.read_text()) if marker.exists() else {}
    if new_venv:
        prior.pop("python", None)
        prior.pop("models", None)
    if linked(ROOT / "frontend/node_modules"):
        raise DevError("frontend/node_modules is a link/junction. Preserve it; setup requires checkout-owned dependencies.")
    changes = prior.get("python") != fingerprint or (args.models and prior.get("models") != fingerprint)
    node_hash = hashlib.sha256((ROOT / "frontend/package-lock.json").read_bytes()).hexdigest()
    changes |= prior.get("node") != node_hash
    if changes and any(owned(r) for r in processes().values()):
        raise DevError("Dependency changes require stopping this checkout first: run down, then setup.")
    constraints = STATE / "constraints.txt"
    lines = []
    for dependency_file in source[1:]:
        for raw in dependency_file.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                lines.append(re.sub(r"\[[^]]+\]", "", line))
    constraints.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if prior.get("python") != fingerprint:
        free = shutil.disk_usage(ROOT).free
        if free < 1024 ** 3:
            raise DevError("Less than 1 GB free disk. Free space safely before dependency installation; no data removed.")
        if free < 5 * 1024 ** 3:
            print("WARNING: under 5 GB free; dependencies and optional model weights can need several GB.")
        run([PYTHON, "-m", "pip", "install", "-c", constraints, "-r", manifest])
        run([PYTHON, "-m", "pip", "check"])
        prior["python"] = fingerprint
    if args.models and prior.get("models") != fingerprint:
        # Linux CPU-only torch avoids implicitly pulling gigabytes of CUDA runtimes.
        if sys.platform.startswith("linux"):
            run([PYTHON, "-m", "pip", "install", "--index-url", "https://download.pytorch.org/whl/cpu", "torch>=2,<3"])
        run([PYTHON, "-m", "pip", "install", "-r", source[1]])
        run([PYTHON, "-m", "pip", "check"])
        prior["models"] = fingerprint
    lock = hashlib.sha256((ROOT / "frontend/package-lock.json").read_bytes()).hexdigest()
    if prior.get("node") != lock or not (ROOT / "frontend/node_modules/vite/bin/vite.js").exists():
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise DevError("npm was not found. Install Node 24 LTS, reopen the terminal, run setup.")
        run([npm, "ci"], cwd=ROOT / "frontend")
        prior["node"] = lock
    write_json(marker, prior)
    compose_file(c)
    print("Dependencies/configuration ready. Existing .env files were not read or changed.")
    print("Run up to create/start this checkout's infrastructure and apply migrations.")
    capabilities()


def infra(_args):
    """Initialize only the owned local infrastructure; never reset existing data."""
    c = config()
    check_docker()
    compose_file(c)
    verify_containers(c)
    docker(c, "up", "-d", "--wait", "--wait-timeout", "180")
    print("Local infrastructure ready. PostgreSQL creates the development DB only on first volume initialization; existing data retained.")


def up(args):
    c = config()
    if not PYTHON.exists() or not (STATE / "dependencies.json").exists():
        raise DevError("Dependency setup is incomplete. Run setup.")
    check_docker()
    integrations()
    compose_file(c)
    verify_containers(c)
    records = processes()
    mode_file = STATE / "mode.json"
    previous_mode = json.loads(mode_file.read_text())["mode"] if mode_file.exists() else "full"
    args.mode = args.mode or previous_mode
    if args.mode != previous_mode and any(owned(r) for r in records.values()):
        raise DevError("Stop the owned runtime with down before changing worker modes.")
    containers = docker(c, "ps", "--format", "json", capture=True).strip()
    # Check ports before creating infrastructure. Running owned infrastructure is checked by Compose.
    owned_ports = {"api", "frontend"}
    for name, port in c["ports"].items():
        if name in owned_ports and records.get(name) and owned(records[name]):
            continue
        if name in ("prices_metrics", "maintenance_metrics"):
            worker = "prices" if name == "prices_metrics" else "maintenance"
            if records.get(worker) and owned(records[worker]):
                continue
        elif name not in owned_ports and containers:
            continue
        if not available(port):
            raise DevError(f"Port {port} ({name}) is occupied by an unowned listener. "
                           "No process was stopped. Choose a free port in .dev/config.json while down.")
    docker(c, "up", "-d", "--wait", "--wait-timeout", "180")
    database(c, "migrate")
    database(c, "check")
    start_process("api", [PYTHON, "-m", "uvicorn", "src.ai.main:app", "--host", "127.0.0.1",
                          "--port", c["ports"]["api"]], c)
    origin = f"http://127.0.0.1:{c['ports']['frontend']}"
    api = f"http://127.0.0.1:{c['ports']['api']}"
    wait_for("FastAPI database/Redis readiness and exact CORS", lambda: (
        json.loads(http(api + "/health/ready", origin)[0]).get("status") == "ok"
        and http(api + "/health/ready", origin)[1].get("Access-Control-Allow-Origin") == origin))
    names = CORE if args.mode == "core" else list(WORKERS)
    for name in names:
        start_process(name, [PYTHON, "-m", WORKERS[name]], c)
        wait_for(f"{name} worker initialization", lambda name=name: worker_ready(name, c), 45)
    start_process("frontend", ["node", ROOT / "frontend/node_modules/vite/bin/vite.js",
                              "--host", "127.0.0.1", "--port", c["ports"]["frontend"], "--strictPort"], c)
    wait_for("Vite and actual frontend-to-API proxy", lambda: (
        "/src/main" in http(origin)[0] and json.loads(http(origin + "/api/health/ready")[0]).get("status") == "ok"))
    write_json(STATE / "mode.json", {"mode": args.mode, "workers": names})
    print("Source: " + run(["git", "rev-parse", "HEAD"], capture=True).strip())
    print(f"\nREADY ({args.mode} local runtime; external capabilities listed below)")
    print(f"Frontend: {origin}\nAPI: {api}\nAPI docs: {api}/docs")
    print(f"Mail inbox: http://127.0.0.1:{c['ports']['inbox']}\nStorage console: http://127.0.0.1:{c['ports']['console']}")
    capabilities()


def down(_args):
    import psutil
    c = config()
    records = processes()
    for name, record in reversed(list(records.items())):
        if not owned(record):
            if psutil.pid_exists(record["pid"]):
                raise DevError(f"{name} PID was reused or changed. Refusing to stop it; inspect doctor.")
            continue
        parent = psutil.Process(record["pid"])
        # Inspect descendants before stopping; never kill by port or process name.
        children = parent.children(recursive=True)
        parent.terminate()
        _, alive = psutil.wait_procs([parent], timeout=20)
        if alive:
            parent.kill()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, remaining = psutil.wait_procs(children, timeout=5)
        for child in remaining:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(remaining, timeout=5)
    write_json(STATE / "processes.json", {})
    check_docker()
    verify_containers(c)
    docker(c, "stop")
    print("Stopped this checkout's processes and containers. Database, Redis and storage volumes retained.")


def status(_args):
    c = config()
    ok = True
    for name, record in processes().items():
        live = owned(record)
        print(f"{name}: {'RUNNING (identity verified)' if live else 'STOPPED/IDENTITY MISMATCH'}")
        if live:
            print("  source: " + record.get("revision", "unrecorded"))
        ok &= live
    check_docker()
    verify_containers(c)
    print(docker(c, "ps", "--all", capture=True))
    try:
        body, _ = http(f"http://127.0.0.1:{c['ports']['api']}/health/ready")
        print("API readiness: " + body)
    except OSError:
        ok = False
        print("API readiness: unavailable")
    mode = STATE / "mode.json"
    if mode.exists():
        for name in json.loads(mode.read_text())["workers"]:
            ready = worker_ready(name, c)
            print(f"{name} readiness: {ready}")
            ok &= ready
    if not ok:
        raise DevError("One or more local services are not ready. Inspect logs; status is not a readiness claim.")


def redact(value):
    value = re.sub(r"(?:sk|rk)_(?:test|live)_[A-Za-z0-9]+|whsec_[A-Za-z0-9]+", "<redacted>", value)
    return re.sub(r"postgres(?:ql)?://\S+", "postgresql://<redacted>", value)


def logs(args):
    def show():
        paths = [STATE / "logs" / f"{args.service}.log"] if args.service else sorted((STATE / "logs").glob("*.log"))
        for path in paths:
            if path.exists():
                print(f"\n--- {path.stem} ---")
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-args.tail:]:
                    line = re.sub(r"(?:sk|rk)_(?:test|live)_[A-Za-z0-9]+|whsec_[A-Za-z0-9]+", "<redacted>", line)
                    line = re.sub(r"postgres(?:ql)?://[^ @]+", "postgresql://<redacted>", line)
                    print(redact(line))
    show()
    if args.follow:
        # Avoid repeats: maintain offsets and print only new lines.
        offsets = {p: p.stat().st_size for p in (STATE / "logs").glob("*.log")}
        try:
            while True:
                for path in (STATE / "logs").glob("*.log"):
                    if args.service and path.stem != args.service:
                        continue
                    with path.open(encoding="utf-8", errors="replace") as stream:
                        stream.seek(min(offsets.get(path, 0), path.stat().st_size))
                        value = stream.read()
                        if value:
                            print(f"[{path.stem}] {redact(value)}", end="", flush=True)
                        offsets[path] = stream.tell()
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass


def doctor(_args):
    print(f"Checkout: {ROOT}\nPython: {sys.version.split()[0]}")
    print("Revision: " + run(["git", "rev-parse", "HEAD"], capture=True).strip())
    print("Node: " + run(["node", "--version"], capture=True).strip())
    check_docker()
    print("Docker Engine/Compose: available")
    c = config()
    print("Database: keel_dev_" + c["id"] + " (isolated Compose project, loopback only)")
    for key, value in c["ports"].items():
        print(f"{key}: 127.0.0.1:{value}")
    print("Environment: .dev/config.json and optional .dev/integrations.env; repository .env files ignored")
    capabilities()


def test(args):
    run([sys.executable, "-m", "unittest", "discover", "-s", ROOT / "tools/dev/tests", "-v"])
    if args.suite == "tooling":
        return
    c = config()
    if args.suite == "browser":
        run(["node", ROOT / "tools/dev/browser_smoke.mjs"], env=environment(c))
    elif args.suite == "database":
        database(c, "check")
        run([PYTHON, ROOT / "tools/dev/database.py", "test"], cwd=ROOT / "backend", env=environment(c, admin=True))
    else:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        for script in ("test", "lint", "build"):
            run([npm, "run", script], cwd=ROOT / "frontend", env=environment(c))


@contextlib.contextmanager
def command_lock():
    STATE.mkdir(exist_ok=True)
    path = STATE / "command.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DevError("Another developer command holds .dev/command.lock. "
                       "Check its recorded PID before removing a stale lock; never remove an active lock.") from None
    try:
        with os.fdopen(fd, "w") as lock:
            lock.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "up", "down", "restart", "status", "logs",
                                           "doctor", "infra", "migrate", "db-status", "db-check", "seed", "test"])
    parser.add_argument("--mode", choices=["core", "full"], default=None)
    parser.add_argument("--models", action="store_true", help="setup: also install the existing model requirements")
    parser.add_argument("--suite", choices=["tooling", "frontend", "database", "browser"], default="tooling")
    parser.add_argument("--service", choices=["api", "frontend", "migrations", *WORKERS])
    parser.add_argument("--tail", type=int, default=40)
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    try:
        if args.command in ("logs", "doctor", "status", "test"):
            globals()[args.command](args)
        else:
            with command_lock():
                if args.command == "restart":
                    down(args)
                    up(args)
                elif args.command in ("migrate", "db-status", "db-check", "seed"):
                    c = config()
                    if args.command != "seed":
                        check_docker()
                        verify_containers(c)
                    database(c, {"db-status": "status", "db-check": "check"}.get(args.command, args.command))
                else:
                    globals()[args.command](args)
        return 0
    except (DevError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Started resources remain owned by this checkout; inspect status or run down.")
        return 130
    except Exception as exc:
        # Never interpolate exception text that might include a DSN or token.
        print(f"ERROR: {type(exc).__name__}. Inspect local logs and docs/TROUBLESHOOTING.md; no readiness claimed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
