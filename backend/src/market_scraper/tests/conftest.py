import pytest


@pytest.fixture(autouse=True)
def _connector_hosts_are_mocked(monkeypatch):
    """Connector tests use made-up hostnames with the network mocked; the
    public-address check (network_security.assert_connector_target) has
    its own tests that remove this."""
    monkeypatch.setenv("CONNECTORS_ALLOW_PRIVATE_HOSTS", "true")
