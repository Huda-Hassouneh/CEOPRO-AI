"""Tier-2 market staging: retain raw candidates before validation/promotion."""

import hashlib
import json

from scrapy import signals

from src.market_scraper import data_access


def content_hash(item: dict) -> str:
    """Hash stable business content, never runtime timestamps or spider-provided hashes."""
    relevant = {key: item.get(key) for key in (
        "product_name", "category", "description", "price_amount", "currency",
        "availability", "rating", "review_count", "product_url",
    )}
    payload = json.dumps(relevant, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def stage_record(conn, item: dict) -> str:
    raw = {key: value for key, value in dict(item).items() if not key.startswith("_")}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO market_observation_staging
                (tenant_id, source_id, job_id, mapping_id, raw_payload,
                 content_hash, safety_flags)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
            ON CONFLICT (tenant_id, job_id, mapping_id, content_hash)
            DO UPDATE SET raw_payload = EXCLUDED.raw_payload,
                          safety_flags = EXCLUDED.safety_flags
            RETURNING staging_id;
            """,
            (
                item["tenant_id"], item["source_id"], item["job_id"], item["mapping_id"],
                json.dumps(raw, default=str), content_hash(item),
                json.dumps(item.get("safety_flags", [])),
            ),
        )
        staging_id = str(cursor.fetchone()[0])
    conn.commit()
    return staging_id


def resolve_stage(conn, tenant_id: str, staging_id: str, status: str, errors=()):
    if status not in {"REJECTED", "QUARANTINED", "PROMOTED"}:
        raise ValueError("invalid terminal staging status")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE market_observation_staging
            SET validation_status = %s, validation_errors = %s::jsonb, resolved_at = NOW()
            WHERE tenant_id = %s AND staging_id = %s;
            """,
            (status, json.dumps(list(errors)), tenant_id, staging_id),
        )
    conn.commit()


class PostgresMarketStagingPipeline:
    """Stage mapped items first and preserve validation failures for review."""

    def __init__(self, crawler):
        self.connection = None
        crawler.signals.connect(self.item_dropped, signal=signals.item_dropped)
        crawler.signals.connect(self.spider_closed, signal=signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        if not item.get("mapping_id"):
            return item
        if self.connection is None:
            self.connection = data_access.get_tenant_connection(item["tenant_id"])
        item["_staging_id"] = stage_record(self.connection, item)
        return item

    def item_dropped(self, item, response, exception, spider):
        staging_id = item.get("_staging_id")
        if staging_id and self.connection:
            resolve_stage(
                self.connection, item["tenant_id"], staging_id,
                "REJECTED", (str(exception),),
            )

    def spider_closed(self, spider, reason):
        if self.connection:
            self.connection.close()
