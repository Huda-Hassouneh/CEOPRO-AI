"""
Consume post-upload discovery-requested events and run full competitor
discovery for the tenant - the real fix for the gap found in the
production-hardening audit: tenant_discovery.py::discover_competitors_
for_tenant()/discover_domain_level_competitors_for_tenant() were fully
built and correctly wired to each other (product-level Custom Search +
social-only discovery, domain-level Places/industry-keyword discovery,
the classification gate, website_identity_key dedup) but nothing in the
live system ever called them - only integration tests did. Production
discovery was 100% a manual `policy_cli.py`/CLI operation until this
module existed.

Consumes market.discovery.requested, published by src/ai/main.py's
POST /extraction/upload right after real new products are persisted -
same cross-service event-bus pattern already used for
market.scrape.requested (worker.py) and market.analysis.requested
(analysis_worker.py).

Does NOT auto-trigger scraping for every freshly-discovered candidate.
See tenant_discovery.py's own module docstring: a fully automated
discovery run never supplies terms_evidence, so policy.py::
evaluate_source() can only ever return RESTRICTED for a brand-new
source (never ALLOWED - that requires terms_evidence, which only the
existing human policy-approval workflow ever supplies). Auto-enqueuing
collection here is scoped to results whose policy_status ALREADY reads
ALLOWED - meaning a human already approved that exact website for a
DIFFERENT product earlier, and this discovery run just found it also
carries one of the tenant's newly-uploaded products. That extends an
already-approved site's coverage to a new product mapping on the same
site; it does not bypass the approval workflow for a genuinely new,
unreviewed source.
"""

import logging
import os

import redis

from src.market_scraper import data_access
from src.market_scraper.enqueue import enqueue_collection
from src.market_scraper.tenant_discovery import (
    discover_competitors_for_tenant, discover_domain_level_competitors_for_tenant,
)

STREAM = os.getenv("DISCOVERY_STREAM_KEY", "market.discovery.requested")
GROUP = "ceopro-market-discovery"
DEAD_STREAM = os.getenv("DISCOVERY_DEAD_STREAM_KEY", "market.discovery.dead")
MAX_ATTEMPTS = int(os.getenv("DISCOVERY_MAX_ATTEMPTS", "3"))
CLAIM_IDLE_MS = int(os.getenv("DISCOVERY_CLAIM_IDLE_MS", "300000"))
logger = logging.getLogger(__name__)


def _enqueue_allowed(tenant_id: str, results: list) -> list:
    """Enqueues real collection for every result whose policy_status is
    already ALLOWED (see this module's own docstring for why that never
    includes a brand-new, unreviewed source). Returns the source_ids
    actually enqueued; a single source's enqueue failure is logged and
    skipped, never allowed to abort the rest of the batch."""
    enqueued = []
    for result in results:
        if result.get("policy_status") != "ALLOWED":
            continue
        source_id = result.get("source_id")
        try:
            enqueue_collection(tenant_id, source_id)
            enqueued.append(source_id)
        except Exception as exc:
            logger.error(
                "could not enqueue collection for tenant=%s source=%s: %s", tenant_id, source_id, exc
            )
    return enqueued


def discover_for_tenant(tenant_id: str) -> dict:
    """
    Runs on every real market.discovery.requested event. Opens its own
    tenant-scoped connection (data_access.get_tenant_connection(), the
    same RLS-respecting pattern analysis_worker.py already uses), runs
    both discovery passes, then enqueues real collection for whichever
    results already carry an ALLOWED policy_status - see module docstring.
    """
    actor_user_id = os.getenv("SCRAPER_ACTOR_USER_ID")
    if not actor_user_id:
        raise RuntimeError("SCRAPER_ACTOR_USER_ID environment variable is not set.")

    conn = data_access.get_tenant_connection(tenant_id)
    try:
        product_results = discover_competitors_for_tenant(conn, tenant_id, actor_user_id)
        domain_results = discover_domain_level_competitors_for_tenant(conn, tenant_id, actor_user_id)
    finally:
        conn.close()

    enqueued = _enqueue_allowed(tenant_id, product_results)
    for domain_result in domain_results:
        enqueued.extend(_enqueue_allowed(tenant_id, domain_result.get("mapped_products") or []))

    return {
        "product_level_candidates": len(product_results),
        "domain_level_candidates": len(domain_results),
        "enqueued_source_ids": enqueued,
    }


def _claimed_messages(client, consumer: str):
    """Mirrors market_scraper/worker.py::_claimed_messages() exactly -
    reclaims a message left pending by a previous, failed/crashed attempt
    rather than leaving it invisible to every future xreadgroup call."""
    try:
        result = client.xautoclaim(STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=10)
    except (AttributeError, redis.ResponseError):
        return []
    return result[1] if len(result) > 1 else []


def handle_message(client, message_id: str, payload: dict) -> None:
    """Attempt-tracking/dead-letter wrapper around discover_for_tenant() -
    mirrors market_scraper/worker.py::handle_message()'s contract."""
    attempts_key = f"{STREAM}:attempts"
    try:
        tenant_id = payload["tenant_id"]
        result = discover_for_tenant(tenant_id)
        client.xack(STREAM, GROUP, message_id)
        client.hdel(attempts_key, message_id)
        logger.info("discovery %s completed: %s", message_id, result)
    except Exception as exc:
        attempts = int(client.hincrby(attempts_key, message_id, 1))
        logger.error("discovery %s failed attempt %s: %s", message_id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            client.xadd(DEAD_STREAM, {
                **{key: str(value) for key, value in payload.items()},
                "original_message_id": message_id,
                "attempts": str(attempts),
                "error": str(exc)[:1000],
            })
            client.xack(STREAM, GROUP, message_id)
            client.hdel(attempts_key, message_id)
            logger.error("discovery %s moved to dead-letter stream %s after %s attempts", message_id, DEAD_STREAM, attempts)


def run_forever():
    logging.basicConfig(level=logging.INFO)
    client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    consumer = f"market-discovery-{os.getpid()}"
    try:
        client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    while True:
        messages = _claimed_messages(client, consumer)
        if not messages:
            batches = client.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            messages = [message for _, batch in batches for message in batch]
        for message_id, payload in messages:
            handle_message(client, message_id, payload)


if __name__ == "__main__":
    run_forever()
