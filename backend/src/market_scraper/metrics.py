"""Prometheus metrics shared by market collection workers."""

from prometheus_client import Counter, Gauge, Histogram

COLLECTIONS = Counter(
    "ceopro_market_collections_total", "Collection subprocess outcomes", ("outcome",)
)
COLLECTION_SECONDS = Histogram(
    "ceopro_market_collection_duration_seconds", "Collection subprocess duration"
)
DEAD_LETTERS = Counter(
    "ceopro_market_dead_letters_total", "Collection jobs moved to the dead-letter stream"
)
PENDING_MESSAGES = Gauge(
    "ceopro_market_pending_messages", "Pending messages in the collection consumer group"
)
STALE_RECOVERED = Counter(
    "ceopro_market_stale_jobs_recovered_total", "Stale ingestion jobs recovered"
)
RETENTION_RUNS = Counter(
    "ceopro_market_retention_runs_total", "Retention runs", ("outcome",)
)
