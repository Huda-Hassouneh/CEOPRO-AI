from decimal import Decimal

from src.market_scraper.market_repository import _content_hash, _derive_events


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.rows = []
        self.event_count = 0

    def execute(self, query, params):
        self.calls.append((" ".join(query.split()), params))
        if "INSERT INTO market_events" in query:
            self.event_count += 1
            self.rows.append((f"event-{self.event_count}",))
        elif "SELECT alert_rule_id" in query:
            self.rows = []

    def fetchone(self):
        return self.rows.pop(0)

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows


def item(**updates):
    base = {
        "tenant_id": "t", "source_id": "s", "mapping_id": "m", "global_competitor_id": "c",
        "competitor_name": "Shop", "product_name": "Shoe", "price_amount": 90,
        "currency": "USD", "is_available": True, "product_url": "https://example.com/shoe",
        "captured_at": "2026-01-01T00:00:00Z",
    }
    return {**base, **updates}


def test_content_hash_is_stable_and_ignores_runtime_lineage():
    assert _content_hash(item(job_id="one")) == _content_hash(item(job_id="two"))


def test_price_and_availability_changes_create_events():
    cursor = FakeCursor()
    events = _derive_events(cursor, item(price_amount=90, is_available=False), (Decimal("100"), True, None))
    assert events == ["event-1", "event-2"]
    event_types = [params[4] for query, params in cursor.calls if "INSERT INTO market_events" in query]
    assert event_types == ["PRICE_CHANGED", "AVAILABILITY_CHANGED"]
