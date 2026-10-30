"""Run real AUTH browser journeys against explicitly disposable local infrastructure.

Requires aiosmtpd in the test environment; never imported by production.
The temporary mailbox is loopback-only and protected by a per-run secret.
"""
import email
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import psycopg2
from aiosmtpd.controller import Controller


def main():
    from scripts.billing_verification import validate_test_environment
    assert os.environ.get('PHASE1A_ISOLATED_BROWSER') == 'YES'
    database_url = validate_test_environment(dict(os.environ), database=True)
    root = Path(__file__).resolve().parents[2]
    # A real platform owner is bootstrapped only inside the explicitly
    # disposable verification database. This exercises the same one-time
    # privileged bootstrap function used by the native acceptance fixture.
    from src.ai.core.security import hash_password
    platform_email = f"auth-browser-platform-owner-{secrets.token_hex(8)}@example.test"
    platform_password = f"Platform-{secrets.token_urlsafe(18)}!aA9"
    search_marker = f"{secrets.token_hex(6)}"
    with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT u.user_id,u.email FROM keel_platform_members m JOIN users u USING(user_id) "
            "WHERE m.role_key='owner' AND m.status='active' AND u.email LIKE 'auth-browser-platform-owner-%@example.test' "
            "LIMIT 1"
        )
        existing_owner = cursor.fetchone()
        if existing_owner:
            platform_user_id, platform_email = str(existing_owner[0]), existing_owner[1]
            cursor.execute("UPDATE users SET password_hash=%s WHERE user_id=%s", (hash_password(platform_password), platform_user_id))
        else:
            platform_user_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) "
                "VALUES(%s,%s,%s,%s,now())",
                (platform_user_id, platform_email, hash_password(platform_password), "Browser Platform Owner"),
            )
            cursor.execute(
                "SELECT keel_bootstrap_platform_owner(%s,'JO','JOD','isolated AUTH browser acceptance fixture')",
                (platform_user_id,),
            )
        # Seed enough isolated records to prove the browser asks the server to
        # filter the full directory and paginate the filtered set. The target
        # suffix is deliberately on the third 50-row page before filtering.
        created_at = datetime.now(timezone.utc)
        for index in range(120):
            cursor.execute(
                "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,created_at) "
                "VALUES(%s,%s,'JO','JOD',%s)",
                (str(uuid.uuid4()), f"Browser Search {search_marker} Company {index:03}", created_at - timedelta(seconds=index)),
            )
            cursor.execute(
                "INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at,created_at) "
                "VALUES(%s,%s,'browser-search-fixture',%s,now(),%s)",
                (str(uuid.uuid4()), f"browser-search-{search_marker}-{index:03}@example.test",
                 f"Browser Search {search_marker} User {index:03}", created_at - timedelta(seconds=index)),
            )
    mailbox = {}
    secret = secrets.token_hex(32)

    class Mailbox:
        async def handle_DATA(self, server, session, envelope):
            message = email.message_from_bytes(envelope.content)
            body = message.get_payload(decode=True).decode(message.get_content_charset() or 'utf-8')
            for recipient in envelope.rcpt_tos:
                if not recipient.startswith('auth-browser-') or not recipient.endswith('@example.test'):
                    return '550 Synthetic test recipients only'
                mailbox[recipient] = body
            return '250 Accepted'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get('X-Test-Key') != secret:
                self.send_error(403)
                return
            address = parse_qs(urlparse(self.path).query).get('email', [''])[0]
            if not address.startswith('auth-browser-') or not address.endswith('@example.test'):
                self.send_error(400)
                return
            with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM users WHERE email=%s', (address,))
                users = cursor.fetchone()[0]
            body = json.dumps({'message': mailbox.get(address, ''), 'users': users}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get('X-Test-Key') != secret:
                self.send_error(403)
                return
            address = parse_qs(urlparse(self.path).query).get('email', [''])[0]
            if not address.startswith('auth-browser-') or not address.endswith('@example.test'):
                self.send_error(400)
                return
            if urlparse(self.path).path != '/expire-platform-invitation':
                self.send_error(404)
                return
            with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE keel_platform_invitations SET expires_at=now()-interval '1 minute' "
                    "WHERE lower(email)=lower(%s) AND accepted_at IS NULL AND canceled_at IS NULL",
                    (address,),
                )
                changed = cursor.rowcount
            body = json.dumps({'expired': changed == 1}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

    smtp = Controller(Mailbox(), hostname='127.0.0.1', port=18025)
    control = ThreadingHTTPServer(('127.0.0.1', 18002), Handler)
    env = {**os.environ, 'SMTP_HOST': '127.0.0.1', 'SMTP_PORT': '18025',
           'SMTP_USE_TLS': 'false', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '',
           'FRONTEND_BASE_URL': 'http://127.0.0.1:15173',
           'VITE_API_BASE_URL': '/api', 'KEEL_API_PROXY_TARGET': 'http://127.0.0.1:18001',
           'PHASE1A_BROWSER_BASE_URL': 'http://127.0.0.1:15173',
           'AUTH_TEST_MAILBOX_KEY': secret, 'REQUIRE_EMAIL_VERIFICATION': 'true',
           'AUTH_BROWSER_PLATFORM_OWNER_EMAIL': platform_email,
           'AUTH_BROWSER_PLATFORM_OWNER_PASSWORD': platform_password,
           'AUTH_BROWSER_PLATFORM_SEARCH_MARKER': search_marker}
    processes = []
    with tempfile.TemporaryDirectory(prefix='keel-auth-browser-') as logs:
        handles = []
        try:
            smtp.start()
            threading.Thread(target=control.serve_forever, daemon=True).start()
            for name, command, cwd in [
                ('backend', [sys.executable, '-m', 'uvicorn', 'src.ai.main:app', '--host', '127.0.0.1', '--port', '18001'], root / 'backend'),
                ('frontend', ['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '15173', '--strictPort'], root / 'frontend'),
            ]:
                handle = open(Path(logs) / (name + '.log'), 'w', encoding='utf-8')
                handles.append(handle)
                processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=handle))
            for url in ['http://127.0.0.1:18001/health', 'http://127.0.0.1:18001/health/ready', 'http://127.0.0.1:15173/login']:
                for _ in range(90):
                    try:
                        with urlopen(url, timeout=2) as response:
                            assert response.status == 200
                        break
                    except Exception:
                        time.sleep(1)
                else:
                    raise RuntimeError('Isolated application did not become ready')
            result = subprocess.run(['node', 'tests/browser/auth-lifecycle.mjs'], cwd=root / 'frontend', env=env)
            if result.returncode:
                # Backend exceptions only, not request bodies or tokens.
                for handle in handles:
                    handle.flush()
                for line in (Path(logs) / 'backend.log').read_text(encoding='utf-8').splitlines():
                    if 'Error:' in line or 'Exception:' in line:
                        print(line)
            return result.returncode
        finally:
            for process in processes:
                process.terminate()
                process.wait(timeout=20)
            control.shutdown()
            control.server_close()
            smtp.stop()
            for handle in handles:
                handle.close()


if __name__ == '__main__':
    raise SystemExit(main())
