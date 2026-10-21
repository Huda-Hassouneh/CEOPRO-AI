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
RECEIPT_STREAM = os.getenv("ENRICHMENT_RECEIPT_STREAM_KEY", "market.enrichment.receipt.v1")
DEAD_STREAM = os.getenv("ENRICHMENT_DEAD_STREAM_KEY", "market.enrichment.dead")
DEDUPE_SECONDS = int(os.getenv("ENRICHMENT_DEDUPE_SECONDS", "600"))

MODE_DUE = "due"      # never attempted, or a scheduled retry is due
MODE_FORCE = "force"  # also failed/partial regardless of schedule, and setup-blocked (key now fixed?)
MODE_PRICES = "prices"  # tenant-wide open-market price lookup for products with no price (price_lookup/)
MODE_COMMENTS = "comments"  # tenant-wide weekly refresh of competitor comments, within a daily search budget
MODES = (MODE_DUE, MODE_FORCE, MODE_PRICES, MODE_COMMENTS)


def receipt_operations_enabled() -> bool:
    return os.getenv("KEEL_ENT008_STAGE2_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def receipt_inflight_key(tenant_id: str, competitor_id: str) -> str:
    return f"{RECEIPT_STREAM}:inflight:{tenant_id}:{competitor_id}"


def enqueue_receipt(redis_client, tenant_id: str, competitor_id: str, receipt_id: str) -> str:
    """Redis carries only the durable receipt reference, never request secrets."""
    if not receipt_operations_enabled():
        raise RuntimeError("receipt-backed enrichment is disabled pending worker rollout")
    key = receipt_inflight_key(tenant_id, competitor_id)
    redis_client.set(key, receipt_id, ex=DEDUPE_SECONDS)
    try:
        return str(redis_client.xadd(RECEIPT_STREAM, {"tenant_id": tenant_id, "receipt_id": receipt_id}))
    except Exception:
        redis_client.delete(key)
        raise


def inflight_key(tenant_id: str, competitor_id: Optional[str], mode: str) -> str:
    return f"{STREAM}:inflight:{tenant_id}:{competitor_id or 'all'}:{mode}"


def enqueue_enrichment(
    redis_client, tenant_id: str, competitor_id: Optional[str] = None,
    facets: Optional[list] = None, mode: str = MODE_DUE, depth: str = "standard",
) -> Optional[str]:
    """Returns the stream message id, or None when an identical job is already
    queued/running. Redis errors propagate - the caller decides how to report them."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    key = inflight_key(tenant_id, competitor_id, mode)
    if not redis_client.set(key, "1", nx=True, ex=DEDUPE_SECONDS):
        return None
    try:
        payload = {"tenant_id": tenant_id, "competitor_id": competitor_id or "", "facets": ",".join(facets or []), "mode": mode}
        if depth != "standard":
            payload["depth"] = depth  # absent = standard, so older workers and payloads keep working
        return str(redis_client.xadd(STREAM, payload))
    except Exception:
        redis_client.delete(key)  # don't leave a phantom "queued" marker behind a failed enqueue
        raise


def is_queued(redis_client, tenant_id: str, competitor_id: Optional[str]) -> bool:
    modes = (MODE_DUE, MODE_FORCE)  # a tenant-wide price lookup is not a pending retry of this competitor
    keys = [inflight_key(tenant_id, competitor_id, m) for m in modes] + [inflight_key(tenant_id, None, m) for m in modes]
    if competitor_id:
        keys.append(receipt_inflight_key(tenant_id, competitor_id))
    return any(redis_client.exists(key) for key in keys)
