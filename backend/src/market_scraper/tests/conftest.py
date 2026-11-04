import os

# Same as src/ai/tests/conftest.py: provider tests mock HTTP without a
# database, and pre-billing tests create companies without a plan.
os.environ.setdefault("KEEL_TEST_DISABLE_METERING", "1")
os.environ.setdefault("UNASSIGNED_PLAN_ACCESS", "default")

import pytest


@pytest.fixture(autouse=True)
def _offline_capacity(request, monkeypatch):
    """Transport unit tests are offline; real Redis admission has native coverage."""
    if request.module.__name__.endswith('_integration_db'):
        return
    from contextlib import nullcontext
    from src.market_scraper import search_safety
    monkeypatch.setattr(search_safety, 'admission', lambda *a, **kw: nullcontext())


@pytest.fixture(autouse=True)
def _connector_hosts_are_mocked(monkeypatch):
    """Connector tests use made-up hostnames with the network mocked; the
    public-address check (network_security.assert_connector_target) has
    its own tests that remove this."""
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "true")
