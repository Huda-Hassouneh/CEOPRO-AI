"""
Integration tests for source_review.py - the real fix for "discovery
correctly finds and classifies real, in-scope competitors (03851fb) but
nothing is ever collected because every data_source lands BLOCKED or
RESTRICTED, never ALLOWED." Exercises the real end-to-end chain: real
discovery registration -> real RESTRICTED/BLOCKED policy decision -> real
human review -> real ALLOWED transition -> real collection eligibility
(data_access.load_scrape_targets(), the exact query enqueue.py/cli.py
gate on). Same convention as every other live-DB test in this package:
skipped unless AI_TEST_DATABASE_URL is set.

Real network (robots.txt) fetches are mocked at the exact boundary
discovery.py/source_review.py themselves call through - this sandbox has
no general internet egress, and the codebase's own established convention
(test_domain_level_discovery_integration_db.py, test_tenant_discovery_
integration_db.py) already mocks exactly this boundary rather than the
policy/persistence logic around it, which stays fully real.
"""
import json
import os
import uuid
from unittest.mock import patch

import psycopg2
import pytest
import redis

from src.market_scraper import data_access, enqueue, source_review
from src.market_scraper.discovery import CandidateSource, evaluate_candidate, register_tenant_scoped_competitor

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn, country_code: str = "JO", search_scope_level: str = "COUNTRY") -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency, search_scope_level) "
            "VALUES (%s, %s, %s, 'JOD', %s);",
            (tenant_id, f"Test Co {tenant_id[:8]}", country_code, search_scope_level),
        )
    return tenant_id


def _insert_product(conn, tenant_id: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, 10.0, 'JOD');",
            (product_id, tenant_id, json.dumps({"en": name})),
        )
    return product_id


def _discover_restricted_source(conn, tenant_id: str, product_id: str, url: str = "https://real-competitor.example/p"):
    """Real discovery registration, exactly like tenant_discovery.py's own
    orchestration calls - robots.txt is mocked ALLOWED (True) at
    discovery time, matching the common real case (a genuinely public,
    crawlable site) rather than the network-unreachable case, so the
    resulting RESTRICTED status is reached via the real 'terms not yet
    reviewed' branch this whole feature is about, not a fetch failure."""
    candidate = CandidateSource("Widget A", url, "Real Competitor")
    with patch("src.market_scraper.discovery._fetch_robots_allows", return_value=True):
        decision = evaluate_candidate(candidate)
    registered = register_tenant_scoped_competitor(conn, tenant_id, str(uuid.uuid4()), decision, product_id)
    assert registered["policy_status"] == "RESTRICTED"
    return registered["source_id"], registered["competitor_id"]


def test_review_source_allows_when_reviewer_confirms_terms_and_robots_still_allow(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, competitor_id = _discover_restricted_source(conn, tenant_id, product_id)
    reviewer_id = str(uuid.uuid4())

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, reviewer_id,
            terms_permit=True, reviewer_reference="Checked /terms on 2026-09-29 - public catalog, no anti-scraping clause.",
        )

    assert result["status"] == "ALLOWED"
    assert result["method"] == "WEB_SCRAPE"

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT policy_status, approval_reference, approved_by, approved_at, privacy_reviewed_at "
            "FROM data_sources WHERE tenant_id = %s AND source_id = %s;",
            (tenant_id, source_id),
        )
        status, approval_reference, approved_by, approved_at, privacy_reviewed_at = cursor.fetchone()
    assert status == "ALLOWED"
    assert "public catalog" in approval_reference
    assert str(approved_by) == reviewer_id
    assert approved_at is not None
    assert privacy_reviewed_at is not None

    # Two real rows, not one: the original RESTRICTED decision at
    # discovery time, and this review's own ALLOWED decision - a full,
    # auditable history of the state transition, not just the end state.
    cursor = conn.cursor()
    cursor.execute(
        "SELECT changed_data_json->>'status' FROM audit_logs "
        "WHERE tenant_id = %s AND action_type = 'COLLECTION_POLICY_DECIDED' AND record_id = %s "
        "ORDER BY created_at;",
        (tenant_id, source_id),
    )
    statuses = [row[0] for row in cursor.fetchall()]
    assert statuses == ["RESTRICTED", "ALLOWED"]


def test_review_source_blocks_when_reviewer_denies_terms(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()),
            terms_permit=False, reviewer_reference="Terms explicitly prohibit automated access.",
        )

    assert result["status"] == "BLOCKED"
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT policy_status, approval_reference, approved_by FROM data_sources "
            "WHERE tenant_id = %s AND source_id = %s;",
            (tenant_id, source_id),
        )
        status, approval_reference, approved_by = cursor.fetchone()
    assert status == "BLOCKED"
    # A rejection is never recorded as an approval - these stay NULL even
    # though a real, non-empty reviewer_reference was supplied.
    assert approval_reference is None
    assert approved_by is None


def test_review_source_stays_blocked_when_robots_now_disallows_even_if_terms_permitted(conn):
    """The real 'never bypass robots' guarantee: a reviewer answering
    'yes' on terms cannot make a source collectible if its own robots.txt
    now disallows crawling - re-checked live, not trusted from discovery
    time."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=False):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()),
            terms_permit=True, reviewer_reference="Reviewed terms, they look fine.",
        )

    assert result["status"] == "BLOCKED"
    assert "robots" in result["justification"].lower() or "technical" in result["justification"].lower()


def test_review_source_stays_restricted_when_robots_cannot_be_read_at_review_time(conn):
    """Honesty contract: an unreachable robots.txt at review time is never
    silently treated as permission, even with a real, explicit terms
    approval."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=None):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()),
            terms_permit=True, reviewer_reference="Reviewed terms, they look fine.",
        )

    assert result["status"] == "RESTRICTED"


def test_review_source_rejects_an_empty_reviewer_reference(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with pytest.raises(ValueError, match="reviewer_reference"):
        source_review.review_source(conn, tenant_id, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="   ")


def test_review_source_rejects_reviewing_an_already_allowed_source(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)
    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="Reviewed, fine.",
        )

    with pytest.raises(ValueError, match="already ALLOWED"):
        source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="Reviewed again.",
        )


def test_review_source_enforces_tenant_isolation(conn):
    """A source belonging to tenant A must never be reviewable/visible
    from tenant B's context - load_source()'s own tenant_id scoping is
    what this relies on, exercised here through the real review path."""
    tenant_a = _insert_company(conn)
    tenant_b = _insert_company(conn)
    product_a = _insert_product(conn, tenant_a, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_a, product_a)

    with pytest.raises(ValueError, match="not found"):
        source_review.review_source(
            conn, tenant_b, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="Reviewed.",
        )


def test_approval_makes_the_source_a_real_collection_target(conn):
    """The actual end of the traced gap: before review, load_scrape_
    targets() (the exact function enqueue.py/cli.py gate real collection
    on) returns nothing for this source, even though the product mapping
    and a tracked/confirmed competitor already exist - after a real
    approval, the same query returns the real, unfabricated mapping."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, competitor_id = _discover_restricted_source(conn, tenant_id, product_id)

    # classify_competitor() already ran inside register_tenant_scoped_
    # competitor() - confirm the competitor is really tracked (03851fb's
    # own gate), so this test proves POLICY is the only remaining gate.
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked, is_confirmed_competitor FROM tenant_competitors "
            "WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        is_tracked, is_confirmed = cursor.fetchone()
    assert is_tracked is True
    assert is_confirmed is True

    assert data_access.load_scrape_targets(conn, tenant_id, source_id) == []

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="Reviewed, fine.",
        )
    assert result["status"] == "ALLOWED"

    targets = data_access.load_scrape_targets(conn, tenant_id, source_id)
    assert len(targets) == 1
    assert targets[0]["product_id"] == product_id


def test_out_of_scope_competitor_source_still_never_becomes_a_collection_target_even_if_allowed(conn):
    """Preserves 03851fb: policy approval and geographic/business-type
    relevance are two independent gates - approving a source's policy
    never overrides classify_competitor()'s own is_tracked decision for
    an out-of-scope competitor."""
    tenant_id = _insert_company(conn, country_code="JO", search_scope_level="COUNTRY")
    product_id = _insert_product(conn, tenant_id, "Widget A")
    # A competitor whose ccTLD resolves to a country outside the tenant's
    # own operating_countries - 03851fb's real, non-fabricated exclusion
    # signal.
    source_id, competitor_id = _discover_restricted_source(
        conn, tenant_id, product_id, url="https://somefactory.cn/p",
    )

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT is_tracked FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s;",
            (tenant_id, competitor_id),
        )
        is_tracked = cursor.fetchone()[0]
    assert is_tracked is False  # excluded by the real geo-scope gate, not policy

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()), terms_permit=True, reviewer_reference="Reviewed, fine.",
        )
    assert result["status"] == "ALLOWED"  # policy alone has no opinion on geo-relevance

    # Still zero real collection targets - tc.is_tracked = TRUE is a
    # separate, still-enforced AND condition.
    assert data_access.load_scrape_targets(conn, tenant_id, source_id) == []


# --- enqueue.py::enqueue_collection() - the actual collector-dispatch gate ---
#
# enqueue_collection() normally opens its OWN pooled, RLS-actor connection
# via data_access.get_tenant_connection() (SCRAPER_DATABASE_URL/
# SCRAPER_ACTOR_USER_ID infrastructure this feature didn't touch - see
# test_enqueue_cost_gate_integration_db.py's own docstring for why every
# other enqueue.py test in this package deliberately avoids standing that
# up too). The one boundary mocked here is exactly that connection
# acquisition - swapped for this test's own already-open, already-
# transactional `conn` (the review decision and the enqueue check then see
# the exact same uncommitted rows, no cross-connection visibility gap to
# fake) - everything else (the real policy_status read, the real
# resolve_collector() lookup, the real cost-margin gate, the real Redis
# XADD against this sandbox's real local Redis) runs unmocked.
class _NonClosingConnProxy:
    """enqueue_collection() always closes whatever get_tenant_connection()
    hands it - here that's this test's own `conn`, which its fixture still
    needs open afterward to roll back and close itself. close() is the only
    method suppressed; every other call passes straight through."""

    def __init__(self, real_conn):
        self._real_conn = real_conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._real_conn, name)


def test_enqueue_collection_rejects_a_restricted_source(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with patch("src.market_scraper.enqueue.data_access.get_tenant_connection", return_value=_NonClosingConnProxy(conn)):
        with pytest.raises(ValueError, match="ALLOWED"):
            enqueue.enqueue_collection(tenant_id, source_id)


def test_enqueue_collection_rejects_a_blocked_source(conn):
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)
    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()),
            terms_permit=False, reviewer_reference="Terms explicitly prohibit automated access.",
        )
    assert result["status"] == "BLOCKED"

    with patch("src.market_scraper.enqueue.data_access.get_tenant_connection", return_value=_NonClosingConnProxy(conn)):
        with pytest.raises(ValueError, match="ALLOWED"):
            enqueue.enqueue_collection(tenant_id, source_id)


def test_enqueue_collection_succeeds_for_an_allowed_source_and_writes_a_real_redis_stream_entry(conn):
    """The actual end of the traced gap, one layer further than
    test_approval_makes_the_source_a_real_collection_target above: not just
    eligible per load_scrape_targets(), but genuinely enqueued - a real
    message landing on this sandbox's real local Redis stream, readable
    back by its own returned message id, with no fabricated price/review
    data anywhere in this path (enqueue_collection() only ever schedules a
    scrape; it never invents collected data itself)."""
    tenant_id = _insert_company(conn)
    product_id = _insert_product(conn, tenant_id, "Widget A")
    source_id, _ = _discover_restricted_source(conn, tenant_id, product_id)

    with patch("src.market_scraper.source_review._fetch_robots_allows", return_value=True):
        result = source_review.review_source(
            conn, tenant_id, source_id, str(uuid.uuid4()),
            terms_permit=True, reviewer_reference="Checked /terms on 2026-09-29 - public catalog, no anti-scraping clause.",
        )
    assert result["status"] == "ALLOWED"

    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    stream_key = os.getenv("SCRAPER_STREAM_KEY", "market.scrape.requested")

    with patch("src.market_scraper.enqueue.data_access.get_tenant_connection", return_value=_NonClosingConnProxy(conn)):
        message_id = enqueue.enqueue_collection(tenant_id, source_id, redis_client=redis_client)

    try:
        assert message_id
        entries = redis_client.xrange(stream_key, min=message_id, max=message_id)
        assert len(entries) == 1
        _, fields = entries[0]
        assert fields["tenant_id"] == tenant_id
        assert fields["source_id"] == source_id
    finally:
        redis_client.xdel(stream_key, message_id)
