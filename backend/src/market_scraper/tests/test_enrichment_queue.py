"""Offline tests for enrichment_queue.py (dedupe + queued marker) and
w.py (job routing, dead-letter, permanent errors, sweep)."""
from unittest.mock import MagicMock, patch

import pytest
import redis

from src.market_scraper import enrichment_queue as q
from src.market_scraper import enrichment_worker as w

T = "t1"
C = "c1"


def test_enqueue_dedupes_with_a_nx_key_and_publishes_the_payload():
    client = MagicMock()
    client.set.return_value = True
    client.xadd.return_value = "1-0"
    assert q.enqueue_enrichment(client, T, C, ["PROFILE", "SOCIAL_LINKS"], q.MODE_FORCE) == "1-0"
    assert client.set.call_args.kwargs == {"nx": True, "ex": q.DEDUPE_SECONDS}
    assert client.xadd.call_args.args[1] == {"tenant_id": T, "competitor_id": C, "facets": "PROFILE,SOCIAL_LINKS", "mode": "force"}


def test_an_identical_queued_job_is_not_duplicated():
    client = MagicMock()
    client.set.return_value = None  # key already present
    assert q.enqueue_enrichment(client, T, C) is None
    client.xadd.assert_not_called()


def test_a_failed_publish_releases_the_marker_so_the_next_click_can_retry():
    client = MagicMock()
    client.set.return_value = True
    client.xadd.side_effect = redis.ConnectionError("down")
    with pytest.raises(redis.ConnectionError):
        q.enqueue_enrichment(client, T, C)
    client.delete.assert_called_once_with(q.inflight_key(T, C, q.MODE_DUE))


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        q.enqueue_enrichment(MagicMock(), T, mode="everything")


def test_is_queued_sees_a_competitor_job_or_a_tenant_wide_job():
    client = MagicMock()
    client.exists.side_effect = lambda key: key == q.inflight_key(T, None, q.MODE_FORCE)
    assert q.is_queued(client, T, C) is True
    client.exists.side_effect = lambda key: False
    assert q.is_queued(client, T, C) is False


# ---- worker ----------------------------------------------------------------------------

def test_a_competitor_job_runs_enrich_competitor_with_its_facets_and_closes_the_connection():
    conn = MagicMock()
    payload = {"tenant_id": T, "competitor_id": C, "facets": "PROFILE", "mode": "force"}
    with patch.object(w.data_access, "get_tenant_connection", return_value=conn), \
         patch.object(w, "enrich_competitor", return_value={"PROFILE": {}}) as one:
        w.process_job(payload)
    one.assert_called_once_with(conn, T, C, facets=["PROFILE"])
    conn.close.assert_called_once()


def test_a_tenant_job_runs_the_batch_in_the_requested_mode():
    conn = MagicMock()
    with patch.object(w.data_access, "get_tenant_connection", return_value=conn), \
         patch.object(w, "enrich_tenant_competitors", return_value={}) as batch:
        w.process_job({"tenant_id": T, "competitor_id": "", "facets": "", "mode": "force"})
    batch.assert_called_once_with(conn, T, mode="force")


def test_success_acks_and_releases_the_marker():
    client = MagicMock()
    payload = {"tenant_id": T, "competitor_id": C, "facets": "", "mode": "force"}
    with patch.object(w, "process_job", return_value={}):
        w.handle_message(client, "1-0", payload)
    client.xack.assert_called_once()
    client.delete.assert_called_once_with(q.inflight_key(T, C, "force"))


def test_a_permanent_error_is_acked_without_retry():
    client = MagicMock()
    with patch.object(w, "process_job", side_effect=ValueError("competitor not found")):
        w.handle_message(client, "1-0", {"tenant_id": T, "competitor_id": C})
    client.xack.assert_called_once()
    client.hincrby.assert_not_called()


def test_a_transient_error_stays_pending_until_max_attempts_then_dead_letters():
    client = MagicMock()
    client.hincrby.return_value = 1
    with patch.object(w, "process_job", side_effect=RuntimeError("db down")):
        w.handle_message(client, "1-0", {"tenant_id": T, "competitor_id": C})
        client.xack.assert_not_called()
        client.delete.assert_not_called()  # marker kept: the job is still pending
        client.hincrby.return_value = w.MAX_ATTEMPTS
        w.handle_message(client, "1-0", {"tenant_id": T, "competitor_id": C})
    client.xadd.assert_called_once()
    client.xack.assert_called_once()
    client.delete.assert_called_once()


def test_sweep_queues_one_job_per_tenant_with_work():
    client = MagicMock()
    with patch.object(w, "list_tenants_with_due_enrichment", return_value=["a", "b"]), \
         patch.object(w.enrichment_queue, "enqueue_enrichment", side_effect=["1-0", None]) as enqueue:
        result = w.run_sweep(client)
    assert result == {"tenants_with_work": 2, "jobs_queued": 1}
    assert enqueue.call_args_list[0].kwargs == {"mode": "due"}


def test_sweep_survives_a_listing_failure_and_a_redis_failure():
    client = MagicMock()
    with patch.object(w, "list_tenants_with_due_enrichment", side_effect=RuntimeError("db")):
        assert w.run_sweep(client) == {"error": "list_failed"}
    with patch.object(w, "list_tenants_with_due_enrichment", return_value=["a"]), \
         patch.object(w.enrichment_queue, "enqueue_enrichment", side_effect=redis.ConnectionError("x")):
        assert w.run_sweep(client) == {"tenants_with_work": 1, "jobs_queued": 0}


def test_a_prices_job_runs_the_tenant_wide_lookup_and_is_not_a_competitor_retry():
    conn = MagicMock()
    with patch.object(w.data_access, "get_tenant_connection", return_value=conn), \
         patch("src.market_scraper.price_lookup.pipeline.lookup_missing_prices", return_value={"products_attempted": 3}) as lookup:
        assert w.process_job({"tenant_id": T, "competitor_id": "", "facets": "", "mode": "prices"}) == {"products_attempted": 3}
    lookup.assert_called_once_with(conn, T)
    conn.close.assert_called_once()
    client = MagicMock()
    client.exists.side_effect = lambda key: key == q.inflight_key(T, None, q.MODE_PRICES)
    assert q.is_queued(client, T, C) is False


def test_a_deep_job_carries_its_depth_to_enrich_competitor():
    client = MagicMock()
    client.set.return_value = True
    q.enqueue_enrichment(client, "t1", "c1", ["PRICES"], q.MODE_FORCE, "deep")
    assert client.xadd.call_args.args[1]["depth"] == "deep"
    with patch.object(w.data_access, "get_tenant_connection", return_value=MagicMock()), \
         patch.object(w, "enrich_competitor", return_value={}) as enrich:
        w.process_job({"tenant_id": "t1", "competitor_id": "c1", "facets": "PRICES", "depth": "deep"})
    assert enrich.call_args.kwargs == {"facets": ["PRICES"], "deep": True}


# ---- the weekly comments refresh and its daily search budget ----------------------------------

def test_the_daily_budget_allows_exactly_that_many_searches_then_says_no():
    client = MagicMock()
    client.incr.side_effect = [1, 2, 3]
    reserve = w.daily_search_reserve(client, budget=2)
    assert [reserve(), reserve(), reserve()] == [True, True, False]
    assert client.expire.called  # the counter cleans itself up


def test_a_comments_job_runs_the_refresh_with_the_shared_budget_and_needs_a_client():
    conn, client = MagicMock(), MagicMock()
    with patch.object(w.data_access, "get_tenant_connection", return_value=conn), \
         patch.object(w, "enrich_tenant_comments", return_value={"refreshed": 2}) as refresh:
        assert w.process_job({"tenant_id": T, "mode": "comments"}, client) == {"refreshed": 2}
    assert refresh.call_args.args[:2] == (conn, T) and callable(refresh.call_args.args[2])
    with patch.object(w.data_access, "get_tenant_connection", return_value=MagicMock()), pytest.raises(ValueError):
        w.process_job({"tenant_id": T, "mode": "comments"})


def test_the_comments_sweep_runs_once_a_day_and_queues_one_job_per_stale_tenant(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setenv("EXTERNAL_COMMENTS_APPROVAL_REFERENCE", "ops-1")
    client = MagicMock()
    client.exists.return_value = 0
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [("t1",), ("t2",)]
    with patch.object(w.data_access, "get_tenant_connection", return_value=conn), \
         patch.object(w.enrichment_queue, "enqueue_enrichment", return_value="1-0") as enqueue:
        assert w.run_comments_sweep(client) == {"tenants_with_stale_comments": 2, "jobs_queued": 2}
    assert enqueue.call_args_list[0].kwargs == {"mode": "comments"} and client.set.called
    client.exists.return_value = 1
    assert w.run_comments_sweep(client) == {"skipped": "already_ran_today"}


def test_the_comments_sweep_queues_nothing_when_collection_is_not_set_up(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    client = MagicMock()
    with patch.object(w.enrichment_queue, "enqueue_enrichment") as enqueue:
        assert w.run_comments_sweep(client) == {"skipped": "not_configured"}
    enqueue.assert_not_called()
