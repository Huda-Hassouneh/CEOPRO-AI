"""
Enqueue side of the competitor-enrichment stream, shared by the API
(per-competitor background retry, "retry all failed") and the scheduled sweep.

Jobs are deduplicated with a short-lived Redis key per (tenant, competitor|all,
mode): clicking Retry five times, or a sweep overlapping a manual bulk retry,
queues one job. The worker deletes the key when the job finishes (or is
dead-lettered); it also expires on its own so a crashed worker can never block
a tenant for long. The same key doubles as the "queued" indicator the
data-status endpoint reports.
"""
import os
from typing import Optional

STREAM = os.getenv("ENRICHMENT_STREAM_KEY", "market.enrichment.requested")
DEAD_STREAM = os.getenv("ENRICHMENT_DEAD_STREAM_KEY", "market.enrichment.dead")
DEDUPE_SECONDS = int(os.getenv("ENRICHMENT_DEDUPE_SECONDS", "600"))

MODE_DUE = "due"      # never attempted, or a scheduled retry is due
MODE_FORCE = "force"  # also failed/partial regardless of schedule, and setup-blocked (key now fixed?)
MODE_PRICES = "prices"  # tenant-wide open-market price lookup for products with no price (price_lookup/)
MODES = (MODE_DUE, MODE_FORCE, MODE_PRICES)


def inflight_key(tenant_id: str, competitor_id: Optional[str], mode: str) -> str:
    return f"{STREAM}:inflight:{tenant_id}:{competitor_id or 'all'}:{mode}"


def enqueue_enrichment(
    redis_client, tenant_id: str, competitor_id: Optional[str] = None,
    facets: Optional[list] = None, mode: str = MODE_DUE,
) -> Optional[str]:
    """Returns the stream message id, or None when an identical job is already
    queued/running. Redis errors propagate - the caller decides how to report them."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    key = inflight_key(tenant_id, competitor_id, mode)
    if not redis_client.set(key, "1", nx=True, ex=DEDUPE_SECONDS):
        return None
    try:
        return str(redis_client.xadd(STREAM, {
            "tenant_id": tenant_id, "competitor_id": competitor_id or "",
            "facets": ",".join(facets or []), "mode": mode,
        }))
    except Exception:
        redis_client.delete(key)  # don't leave a phantom "queued" marker behind a failed enqueue
        raise


def is_queued(redis_client, tenant_id: str, competitor_id: Optional[str]) -> bool:
    modes = (MODE_DUE, MODE_FORCE)  # a tenant-wide price lookup is not a pending retry of this competitor
    keys = [inflight_key(tenant_id, competitor_id, m) for m in modes] + [inflight_key(tenant_id, None, m) for m in modes]
    return any(redis_client.exists(key) for key in keys)
