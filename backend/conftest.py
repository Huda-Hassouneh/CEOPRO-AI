"""Test-run safety guard for every backend suite (src/ and tests/).

Tests create, alter and delete rows, reset roles and flush Redis keys. They
must never run against a hosted database or Redis that happens to be in the
shell's environment (a cloud workspace or a developer shell can carry
production DATABASE_URL / REDIS_URL values). Before any test module is
imported, every connection URL the suites read is checked: only loopback
addresses and single-label container service names (``postgres``, ``redis``)
are accepted. Anything else stops the run with the variable's name and host
(never its credentials).

A deliberate run against a disposable remote instance sets
``KEEL_TEST_ALLOW_REMOTE_SERVICES=1``.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

GUARDED_URL_VARIABLES = (
    "DATABASE_URL",
    "AI_TEST_DATABASE_URL",
    "AI_TEST_MANAGED_PG_ADMIN_URL",
    "SCRAPER_DATABASE_URL",
    "BILLING_TEST_DATABASE_URL",
    "REDIS_URL",
    "AI_TEST_REDIS_URL",
)
GUARDED_HOST_VARIABLES = ("AI_TEST_REDIS_HOST", "REDIS_HOST")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_local_host(host: str | None) -> bool:
    if not host:
        return True  # a Unix socket or libpq default: this machine
    host = host.strip("[]").lower()
    return host in LOOPBACK_HOSTS or host.startswith("127.") or "." not in host


def remote_service_settings(environ=os.environ) -> list[str]:
    problems = []
    for name in GUARDED_URL_VARIABLES:
        value = environ.get(name)
        if not value:
            continue
        try:
            host = urlsplit(value).hostname
        except ValueError:
            host = "<unparseable>"
        if not is_local_host(host):
            problems.append(f"{name} -> {host}")
    for name in GUARDED_HOST_VARIABLES:
        value = environ.get(name)
        if value and not is_local_host(value):
            problems.append(f"{name} -> {value}")
    return problems


def pytest_configure(config):
    if os.environ.get("KEEL_TEST_ALLOW_REMOTE_SERVICES") == "1":
        return
    problems = remote_service_settings()
    if problems:
        pytest.exit(
            "Refusing to run tests against non-local services: "
            + "; ".join(problems)
            + ". Point these at a disposable local database/Redis (see docs/TESTING.md), "
            "or set KEEL_TEST_ALLOW_REMOTE_SERVICES=1 for a deliberate disposable remote run.",
            returncode=4,
        )
