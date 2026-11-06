"""Focused all-history sales scope and evidence regressions."""
from datetime import date

import pytest

from src.ai.rag import access, advisor, evidence, understanding


@pytest.mark.parametrize("question", [
    "Across all available invoice history, what are total sales and units sold?",
    "Across all history, what are total sales and units sold?",
    "Show all available sales history.",
])
def test_supported_all_history_phrasings_are_recognized(question):
    assert understanding.understand(question).slots["all_history"] is True


@pytest.mark.parametrize("question", [
    "Compare sales history for August and September.",
    "How did sales change over the last year?",
])
def test_ordinary_historical_comparisons_are_not_all_history(question):
    assert understanding.understand(question).slots.get("all_history") is not True


def test_all_history_uses_the_tenant_invoice_coverage_boundaries():
    u = understanding.understand("Across all history, what are total sales?")
    period = advisor._sales_periods(u, date(2026, 11, 6),
                                    (date(2024, 2, 3), date(2026, 11, 5)))
    assert period == [{"start": "2024-02-03", "end": "2026-11-06",
                       "label": "all stored history", "kind": "all_history"}]


def test_explicit_date_range_precedes_all_history_wording():
    u = understanding.understand("Across all history, what were sales in August 2026?")
    assert u.slots.get("all_history") is True
    assert advisor._sales_periods(u, date(2026, 11, 6), (date(2024, 1, 1), date(2026, 11, 5))) == u.slots["periods"]


def test_explicit_rolling_window_and_default_30_days_are_preserved():
    explicit = understanding.understand("Show sales for the last 14 days.")
    default = understanding.understand("How were my sales?")
    assert advisor._sales_periods(explicit, date(2026, 11, 6))[0]["start"] == "2026-10-24"
    assert advisor._sales_periods(default, date(2026, 11, 6))[0]["start"] == "2026-10-08"


def test_empty_all_history_has_an_explicit_no_invoices_evidence(monkeypatch):
    from src.ai.rag import business_records

    monkeypatch.setattr(business_records, "sales_coverage", lambda _conn, tenant: None)
    monkeypatch.setattr(business_records, "sales_lines",
                        lambda *_args, **_kwargs: pytest.fail("empty history must not invent a date interval"))
    registry = evidence.EvidenceRegistry()
    u = understanding.understand("Across all history, what are total sales?")
    added, replaced = advisor._records(object(), "tenant-a", u, access.FULL_ACCESS, registry, [],
                                       today=date(2026, 11, 6))
    assert added == 1 and replaced == frozenset({"sales"})
    item = registry.items()[0]
    assert item.route == "/sales"
    assert "no invoices recorded" in item.excerpt


class _AggregateCursor:
    def __init__(self):
        self.sql = ""
        self.params = None
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params
        assert "tenant_id" in sql.lower(), "every sales query must remain tenant scoped"
        self.calls.append((sql, params))

    def fetchone(self):
        assert "MIN(issue_date)" in self.sql
        assert self.params == ("tenant-b",)
        return date(2026, 8, 1), date(2026, 11, 5)

    def fetchall(self):
        if "COALESCE(SUM(total_amount)" in self.sql:
            return [("EUR", 100.0, 1), ("JOD", 998.38, 21)]
        if "localized_text(p.product_name" in self.sql:
            return [
                ("jod-product", "JOD product", "JOD", 64, 998.38, 21, None),
                ("eur-product", "EUR product", "EUR", 2, 100.0, 1, None),
            ]
        pytest.fail(f"unexpected query in focused fake: {self.sql}")


class _AggregateConnection:
    def __init__(self):
        self.cursor_instance = _AggregateCursor()

    def cursor(self):
        return self.cursor_instance


@pytest.mark.parametrize("question", [
    "Across all available invoice history, what are total sales and units sold?",
    "Across all history, what are total sales and units sold?",
])
def test_all_history_evidence_uses_complete_bounds_and_keeps_currency_groups(question):
    conn = _AggregateConnection()
    registry = evidence.EvidenceRegistry()
    u = understanding.understand(question)
    added, replaced = advisor._records(conn, "tenant-b", u, access.FULL_ACCESS, registry, [],
                                       today=date(2026, 11, 6))
    assert added > 0 and replaced == frozenset({"sales"})
    items = registry.items()
    text = "\n".join(f"{item.title}: {item.excerpt}" for item in items)
    assert "998.38 JOD" in text and "64 units" in text
    assert "100 EUR" in text and "2 units" in text
    assert "all stored history (2026-08-01 to 2026-11-05)" in text
    assert all(item.route == "/sales" for item in items)
    assert all(params[0] == "tenant-b" for _, params in conn.cursor_instance.calls)
    assert any(params[1:3] == (date(2026, 8, 1), date(2026, 11, 6))
               for _, params in conn.cursor_instance.calls if len(params) >= 3)
