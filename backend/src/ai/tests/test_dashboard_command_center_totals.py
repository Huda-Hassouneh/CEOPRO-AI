"""Focused contract checks for the canonical sales summary on the dashboard."""

import unittest
from datetime import date
from unittest.mock import patch

from src.ai.dashboard import command_center


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.conn.queries.append((sql, params))
        self.sql = sql

    def fetchone(self):
        if self.sql == "SELECT CURRENT_DATE;":
            return (date(2026, 10, 22),)
        if "SELECT COUNT(*), COALESCE(SUM(i.total_amount)" in self.sql:
            return (1, 30, 3, "JOD")
        if "SELECT EXISTS (SELECT 1 FROM invoices" in self.sql:
            return (True,)
        raise AssertionError(f"Unexpected query: {self.sql}")

    def fetchall(self):
        return []


class _Connection:
    def __init__(self):
        self.queries = []

    def cursor(self):
        return _Cursor(self)


class CommandCenterTotalsTest(unittest.TestCase):
    def test_invoice_total_and_historical_sales_state(self):
        conn = _Connection()
        metrics = {
            "revenue": {"amount": 0, "currency": "JOD"},
            "units_sold": {"units": 0},
        }
        forecast = {"products": [], "totals": {}}
        with patch.object(command_center.dashboard_metrics, "get_dashboard_metrics", return_value=metrics), \
             patch.object(command_center.dashboard_metrics, "get_sales_trend", return_value={"points": []}), \
             patch.object(command_center.forecast_overview, "build_overview", return_value=forecast), \
             patch.object(command_center.discovered_competitors, "market_summary", return_value={}):
            result = command_center.build_command_center(conn, "tenant-a", 7)

        self.assertEqual(result["today"]["orders"], 1)
        self.assertEqual(result["today"]["revenue"], 30)
        self.assertEqual(result["today"]["units"], 3)
        self.assertTrue(result["has_sales"])  # Old sales do not reopen onboarding.
        sql, params = next((sql, params) for sql, params in conn.queries if "SUM(i.total_amount)" in sql)
        self.assertIn("JOIN invoices sale", sql)
        self.assertNotIn("transactions", sql)  # Mirrors are never a second sale.
        self.assertEqual(params, ("tenant-a", "tenant-a"))


if __name__ == "__main__":
    unittest.main()
