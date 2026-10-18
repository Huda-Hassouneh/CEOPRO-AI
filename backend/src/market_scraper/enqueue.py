"""Validate an approved source and enqueue its background collection."""

import argparse
import logging
import os

import redis

from src.market_scraper import cost_ledger, data_access, product_families
from src.market_scraper.collectors import resolve_collector

logger = logging.getLogger(__name__)


def _load_mapped_product_ids(connection, tenant_id: str, source_id: str) -> list:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT product_id FROM competitor_product_mappings "
            "WHERE tenant_id = %s AND source_id = %s AND is_active = TRUE;",
            (tenant_id, source_id),
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _cost_margin_gate_blocks(connection, tenant_id: str, source_id: str) -> "tuple[bool, str]":
    """
    Real cost-to-margin check before spending money on this scrape - see
    cost_ledger.py's own docstring for the full reasoning. Never blocks a
    source with no real product mapping yet (a domain-level discovery
    target, or a source that simply hasn't been matched to a product) -
    the gate protects PRODUCT tracking spend specifically, it has nothing
    to weigh yet for anything else. Blocks only when every real mapped
    product is over its own configured ratio - a source mapped to several
    products stays worth scraping as long as even one of them still is.

    A product priced below the gate's minimum price floor is never
    blocked on that basis alone here: product_families.py::
    find_cost_sharing_family_size() resolves how many REAL, active,
    price-collapse-eligible siblings this product shares a family with
    in the tenant's own catalog (1 = no real family to share with, the
    floor still applies), and that real size is passed into the gate so
    it amortizes cost across the family instead of judging one cheap
    member alone - forced family-keyed group routing instead of a blind
    per-SKU block, the same real grouping tenant_discovery.py already
    applies at discovery time.
    """
    product_ids = _load_mapped_product_ids(connection, tenant_id, source_id)
    if not product_ids:
        return False, "no mapped product yet - gate does not apply"

    decisions = [
        cost_ledger.evaluate_cost_margin_gate(
            connection, tenant_id, pid,
            family_size=product_families.find_cost_sharing_family_size(connection, tenant_id, pid),
        )
        for pid in product_ids
    ]
    if any(decision.allow for decision in decisions):
        return False, "at least one mapped product is still within its cost-to-margin limit"

    reasons = "; ".join(decision.reason for decision in decisions)
    return True, f"every mapped product is over its cost-to-margin limit: {reasons}"


def enqueue_collection(tenant_id: str, source_id: str, redis_client=None) -> str:
    connection = data_access.get_tenant_connection(tenant_id)
    try:
        source = data_access.load_source(connection, tenant_id, source_id)
        if not source or source["policy_status"] != "ALLOWED":
            raise ValueError("source must exist, be active, and have ALLOWED policy")
        resolve_collector(source)

        blocked, reason = _cost_margin_gate_blocks(connection, tenant_id, source_id)
        if blocked:
            logger.info("cost-margin gate blocked scrape for tenant=%s source=%s: %s", tenant_id, source_id, reason)
            raise ValueError(f"cost-margin gate blocked this scrape: {reason}")
    finally:
        connection.close()
    client = redis_client or redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    return str(client.xadd(
        os.getenv("SCRAPER_STREAM_KEY", "market.scrape.requested"),
        {"tenant_id": tenant_id, "source_id": source_id},
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()
    print(enqueue_collection(args.tenant_id, args.source_id))


if __name__ == "__main__":
    main()
