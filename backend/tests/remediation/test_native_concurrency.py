"""Real concurrent HTTP requests; a multiplexed WASM engine is not sufficient."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.ai.core import usage
from tests.integration_review.test_http_database import headers


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_report_http_enforcement(
    client, assigned, billing_connections, owner_db, same_key
):
    if os.getenv("BILLING_TEST_ENGINE") == "pglite":
        pytest.skip(
            "Requires native PostgreSQL independent sessions and concurrent HTTP requests"
        )
    tid, _ = assigned
    limit = usage.get_plan(owner_db, tid)["features"][usage.MONTHLY_REPORTS]["limit"]
    usage.reserve(owner_db, tid, usage.MONTHLY_REPORTS, limit - 2)
    barrier = Barrier(12)

    def request(index):
        barrier.wait(timeout=10)
        auth = headers(
            assigned, "concurrent-shared-key" if same_key else f"concurrent-key-{index}"
        )
        return client.get("/reports/sales/export?format=csv", headers=auth).status_code

    with ThreadPoolExecutor(max_workers=12) as executor:
        statuses = list(executor.map(request, range(12)))
    if same_key:
        assert statuses == [200] * 12
        expected = limit - 1
    else:
        assert statuses.count(200) == 2 and statuses.count(402) == 10
        expected = limit
    with owner_db.cursor() as cur:
        cur.execute(
            "SELECT used FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='monthly_reports'",
            (tid,),
        )
        assert cur.fetchone()[0] == expected
