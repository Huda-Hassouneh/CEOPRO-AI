"""Offline tests for discovery_worker.py - the real "upload -> discovery"
automatic trigger (production-hardening audit fix). conn/discovery
functions/enqueue_collection are all mocked - this verifies orchestration
and the ALLOWED-only auto-enqueue gate, not a real DB or Redis."""
from unittest.mock import MagicMock, patch

import pytest
import redis

from src.market_scraper import discovery_worker


def test_discover_for_tenant_raises_without_actor_user_id(monkeypatch):
    monkeypatch.delenv("SCRAPER_ACTOR_USER_ID", raising=False)
    with pytest.raises(RuntimeError, match="SCRAPER_ACTOR_USER_ID"):
        discovery_worker.discover_for_tenant("tenant-1")


def test_discover_for_tenant_runs_both_discovery_passes_and_closes_the_connection(monkeypatch):
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "actor-1")
    fake_conn = MagicMock()
    with patch("src.market_scraper.discovery_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.discovery_worker.discover_competitors_for_tenant", return_value=[]) as mock_product, \
         patch("src.market_scraper.discovery_worker.discover_domain_level_competitors_for_tenant", return_value=[]) as mock_domain:
        result = discovery_worker.discover_for_tenant("tenant-1")

    mock_product.assert_called_once_with(fake_conn, "tenant-1", "actor-1")
    mock_domain.assert_called_once_with(fake_conn, "tenant-1", "actor-1")
    fake_conn.close.assert_called_once()
    assert result == {"product_level_candidates": 0, "domain_level_candidates": 0, "enqueued_source_ids": []}


def test_discover_for_tenant_only_auto_enqueues_already_allowed_sources(monkeypatch):
    """
    The real safety property: a fully automated discovery run never
    supplies terms_evidence, so a brand-new source can only ever land
    RESTRICTED or BLOCKED (see discovery_worker.py's own module
    docstring) - only a result whose policy_status already reads ALLOWED
    (a human approved that exact site for a different product earlier)
    is eligible for automatic collection here.
    """
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "actor-1")
    fake_conn = MagicMock()
    product_results = [
        {"source_id": "s-allowed", "policy_status": "ALLOWED"},
        {"source_id": "s-restricted", "policy_status": "RESTRICTED"},
        {"source_id": "s-blocked", "policy_status": "BLOCKED"},
    ]
    with patch("src.market_scraper.discovery_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.discovery_worker.discover_competitors_for_tenant", return_value=product_results), \
         patch("src.market_scraper.discovery_worker.discover_domain_level_competitors_for_tenant", return_value=[]), \
         patch("src.market_scraper.discovery_worker.enqueue_collection") as mock_enqueue:
        result = discovery_worker.discover_for_tenant("tenant-1")

    mock_enqueue.assert_called_once_with("tenant-1", "s-allowed")
    assert result["enqueued_source_ids"] == ["s-allowed"]


def test_discover_for_tenant_also_enqueues_allowed_domain_level_mapped_products(monkeypatch):
    """Domain-level ("field competitor") discovery's own mapped_products
    (map_products_on_domain_competitor_site(), run internally by
    discover_domain_level_competitors_for_tenant()) go through the exact
    same ALLOWED-only gate."""
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "actor-1")
    fake_conn = MagicMock()
    domain_results = [
        {
            "competitor_id": "c1", "mapped_products": [
                {"source_id": "s-domain-allowed", "policy_status": "ALLOWED"},
                {"source_id": "s-domain-restricted", "policy_status": "RESTRICTED"},
            ],
        },
        {"competitor_id": "c2"},  # no product mapping found at all - no "mapped_products" key
    ]
    with patch("src.market_scraper.discovery_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.discovery_worker.discover_competitors_for_tenant", return_value=[]), \
         patch("src.market_scraper.discovery_worker.discover_domain_level_competitors_for_tenant", return_value=domain_results), \
         patch("src.market_scraper.discovery_worker.enqueue_collection") as mock_enqueue:
        result = discovery_worker.discover_for_tenant("tenant-1")

    mock_enqueue.assert_called_once_with("tenant-1", "s-domain-allowed")
    assert result["enqueued_source_ids"] == ["s-domain-allowed"]


def test_discover_for_tenant_survives_a_single_enqueue_failure(monkeypatch):
    """One source's enqueue failing (e.g. the collector can't be resolved)
    must not abort the rest of the batch."""
    monkeypatch.setenv("SCRAPER_ACTOR_USER_ID", "actor-1")
    fake_conn = MagicMock()
    product_results = [
        {"source_id": "s-bad", "policy_status": "ALLOWED"},
        {"source_id": "s-good", "policy_status": "ALLOWED"},
    ]

    def _enqueue(tenant_id, source_id):
        if source_id == "s-bad":
            raise ValueError("collector could not be resolved")

    with patch("src.market_scraper.discovery_worker.data_access.get_tenant_connection", return_value=fake_conn), \
         patch("src.market_scraper.discovery_worker.discover_competitors_for_tenant", return_value=product_results), \
         patch("src.market_scraper.discovery_worker.discover_domain_level_competitors_for_tenant", return_value=[]), \
         patch("src.market_scraper.discovery_worker.enqueue_collection", side_effect=_enqueue):
        result = discovery_worker.discover_for_tenant("tenant-1")

    assert result["enqueued_source_ids"] == ["s-good"]


class FakeRedis:
    """Mirrors src/market_scraper/tests/test_worker.py's own FakeRedis -
    same attempt-tracking/dead-letter contract, same minimal double."""

    def __init__(self):
        self.attempts = 0
        self.acked = []
        self.dead = []

    def hincrby(self, *_):
        self.attempts += 1
        return self.attempts

    def hdel(self, *_):
        pass

    def xack(self, *args):
        self.acked.append(args[-1])

    def xadd(self, stream, payload):
        self.dead.append((stream, payload))


def test_handle_message_retries_then_dead_letters_a_permanently_failing_message(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(discovery_worker, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(discovery_worker, "discover_for_tenant", MagicMock(side_effect=RuntimeError("boom")))

    discovery_worker.handle_message(client, "1-0", {"tenant_id": "t1"})
    assert client.acked == []  # first failure: still pending, not dead-lettered yet

    discovery_worker.handle_message(client, "1-0", {"tenant_id": "t1"})
    assert client.acked == ["1-0"]  # second failure hits MAX_ATTEMPTS - dead-lettered and acked
    assert client.dead[0][0] == discovery_worker.DEAD_STREAM
    assert client.dead[0][1]["attempts"] == "2"


def test_handle_message_acks_and_clears_attempts_on_success(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(discovery_worker, "discover_for_tenant", MagicMock(return_value={"enqueued_source_ids": []}))

    discovery_worker.handle_message(client, "2-0", {"tenant_id": "t1"})

    assert client.acked == ["2-0"]
    assert client.dead == []


def test_claimed_messages_returns_empty_list_on_response_error():
    """AttributeError/ResponseError (an old redis-py version without
    xautoclaim, or a not-yet-created group) degrades to no reclaimed
    messages rather than crashing the worker loop."""
    client = MagicMock()
    client.xautoclaim.side_effect = redis.ResponseError("NOGROUP")

    assert discovery_worker._claimed_messages(client, "consumer-1") == []
