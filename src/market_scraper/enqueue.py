"""Validate an approved source and enqueue its background collection."""

import argparse
import os

import redis

from src.market_scraper import data_access
from src.market_scraper.collectors import resolve_collector


def enqueue_collection(tenant_id: str, source_id: str, redis_client=None) -> str:
    connection = data_access.get_tenant_connection(tenant_id)
    try:
        source = data_access.load_source(connection, tenant_id, source_id)
        if not source or source["policy_status"] != "ALLOWED":
            raise ValueError("source must exist, be active, and have ALLOWED policy")
        resolve_collector(source)
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
