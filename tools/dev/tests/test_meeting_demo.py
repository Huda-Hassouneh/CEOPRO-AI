"""Seed-specific contracts: real source totals, stable payload, safe replay."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("meeting_demo", TOOLS / "seed_meeting_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class MeetingDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.patch = patch.object(demo, "BASE", self.base)
        self.patch.start()
        self.journal = patch.object(demo, "JOURNAL", self.base / "journal.json")
        self.journal.start()

    def tearDown(self):
        self.journal.stop()
        self.patch.stop()
        self.temp.cleanup()

    def test_fixed_business_inputs_reconcile_and_parse_published_contract(self):
        from decimal import Decimal
        from src.ai.extraction.structured_business import parse
        truth = demo.inputs()
        self.assertEqual(truth, demo.inputs())
        self.assertEqual(len(truth["invoices"]), 360)
        self.assertEqual(len(truth["lines"]), 1800)
        self.assertEqual(len({x["invoice"] for x in truth["lines"]}), 360)
        self.assertEqual(sum(Decimal(x["total"]) for x in truth["lines"]), Decimal(truth["totals"]["revenue"]))
        products = {p["sku"]: {**p, "id": f"00000000-0000-0000-0000-{i:012d}"} for i, p in enumerate(truth["products"], 1)}
        invoices = truth["invoices"][:180]
        numbers = {x["number"] for x in invoices}
        lines = [x for x in truth["lines"] if x["invoice"] in numbers]
        first = demo.workbook_bytes(invoices, lines, products)
        self.assertEqual(first, demo.workbook_bytes(invoices, lines, products))
        parsed = parse("invoices", "sales.xlsx", first)
        self.assertEqual(len(parsed["invoices"]), 180)
        self.assertEqual(len(parsed["items"]), 900)
        self.assertTrue(all(x["payment_status"] == "PAID" and x["tax_amount"] == "0.0000" for x in parsed["invoices"]))

    def test_confirmation_replay_reuses_exact_review_without_another_preview(self):
        calls = []
        class Client:
            headers = {}
            def request(self, method, path, **kwargs):
                calls.append((path, kwargs))
                if path.endswith("/preview"):
                    return {"draftId": "draft", "reviewHash": "a" * 64, "issues": [], "counts": {"needsAttention": 0}}
                return {"kind": "invoices", "imported": 180}
        journal = {}
        for _ in range(2):
            demo.post_import(Client(), "invoices", "sales.xlsx", b"fixed-content", journal)
        self.assertEqual(sum(x[0].endswith("/preview") for x in calls), 1)
        self.assertEqual(calls[1], calls[2])
        with self.assertRaisesRegex(RuntimeError, "payload changed"):
            demo.post_import(Client(), "invoices", "sales.xlsx", b"changed-content", journal)

    def test_unresolved_identity_cannot_be_confirmed(self):
        class Client:
            headers = {}
            def request(self, method, path, **kwargs):
                if not path.endswith("/preview"):
                    raise AssertionError("Must not confirm unresolved inputs")
                return {"draftId": "draft", "reviewHash": "a" * 64, "issues": [{"message": "conflict"}], "counts": {"needsAttention": 1}}
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            demo.post_import(Client(), "invoices", "sales.xlsx", b"fixed-content", {})


if __name__ == "__main__":
    unittest.main()
