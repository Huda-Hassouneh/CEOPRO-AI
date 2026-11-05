"""Score the assistant's deterministic question understanding against a labelled benchmark.

Usage (from backend/):
    python -m scripts.evaluate_understanding                 # dev split
    python -m scripts.evaluate_understanding --split holdout # aggregate scores only
    python -m scripts.evaluate_understanding --json out.json

The benchmark (src/ai/rag/eval/understanding_benchmark/) and its labelling rules
are described in that folder's README. The holdout split prints aggregate scores
only, never per-item failures, so it is not used to tune rules; its hash is
checked so an edited holdout cannot be reported as the original one.
"""
import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.rag.understanding import understand  # noqa: E402

BENCH = ROOT / "src" / "ai" / "rag" / "eval" / "understanding_benchmark"
TODAY = date(2026, 11, 5)


def load(split: str) -> list:
    path = BENCH / f"{split}.jsonl"
    if split == "holdout":
        pinned = (BENCH / "holdout.sha256").read_text().split()[0]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if pinned != actual:
            raise SystemExit("holdout.jsonl does not match holdout.sha256: the sealed split was edited")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wilson(correct: int, total: int, z: float = 1.96):
    if not total:
        return (0.0, 0.0)
    p = correct / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _periods(slots: dict) -> list:
    return [(p["start"], p["end"]) for p in slots.get("periods") or []]


def score_item(item: dict, catalog: list) -> dict:
    previous = None
    if item.get("previous"):
        previous = understand(item["previous"], catalog=catalog, today=TODAY).state()
    started = time.perf_counter()
    result = understand(item["question"], previous=previous, catalog=catalog, today=TODAY)
    elapsed_ms = (time.perf_counter() - started) * 1000
    intents = set(result.intents)
    missing = sorted(set(item["require"]) - intents)
    wrong = sorted(set(item.get("forbid") or []) & intents)
    intent_ok = not missing and not wrong

    period_ok = None
    if "period" in item:
        expected = item["period"]
        expected = [tuple(p) for p in expected] if isinstance(expected[0], list) else [tuple(expected)]
        got = _periods(result.slots)
        period_ok = (got[:1] == expected) if len(expected) == 1 else (sorted(set(got)) == sorted(set(expected)))

    product_ok = None
    if "products" in item:
        got_products = {p["product_id"] for p in result.slots.get("products") or []}
        product_ok = got_products == set(item["products"])

    correct = intent_ok and period_ok is not False and product_ok is not False
    return {
        "id": item["id"], "lang": item["lang"], "dialect": item["dialect"], "follow_up": bool(item.get("previous")),
        "correct": correct, "intent_ok": intent_ok, "period_ok": period_ok, "product_ok": product_ok,
        "missing": missing, "forbidden_found": wrong, "intents": sorted(intents),
        "periods": _periods(result.slots), "products": sorted(p["product_id"] for p in result.slots.get("products") or []),
        "ms": elapsed_ms,
    }


def summarize(rows: list) -> dict:
    def rate(values):
        values = [v for v in values if v is not None]
        hits = sum(1 for v in values if v)
        low, high = wilson(hits, len(values))
        return {"correct": hits, "total": len(values), "rate": round(hits / len(values), 4) if values else None,
                "ci95": [round(low, 4), round(high, 4)]}

    groups = defaultdict(list)
    for row in rows:
        groups[f"lang:{row['lang']}"].append(row["correct"])
        groups[f"dialect:{row['dialect']}"].append(row["correct"])
        if row["follow_up"]:
            groups["follow_up"].append(row["correct"])
    latencies = sorted(row["ms"] for row in rows)
    return {
        "overall": rate(r["correct"] for r in rows),
        "intent": rate(r["intent_ok"] for r in rows),
        "period": rate(r["period_ok"] for r in rows),
        "product": rate(r["product_ok"] for r in rows),
        "groups": {name: rate(values) for name, values in sorted(groups.items())},
        "latency_ms": {"median": round(latencies[len(latencies) // 2], 3),
                       "p95": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 3)},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--json", help="write the summary (and dev per-item rows) to this file")
    args = parser.parse_args(argv)
    catalog = json.loads((BENCH / "catalog.json").read_text(encoding="utf-8"))
    rows = [score_item(item, catalog) for item in load(args.split)]
    summary = summarize(rows)
    print(f"split={args.split} items={len(rows)} today={TODAY.isoformat()}")
    for key in ("overall", "intent", "period", "product"):
        s = summary[key]
        print(f"  {key:8s} {s['correct']}/{s['total']} = {s['rate']}  95% CI {s['ci95']}")
    for name, s in summary["groups"].items():
        print(f"  {name:22s} {s['correct']}/{s['total']} = {s['rate']}")
    print(f"  latency  median {summary['latency_ms']['median']} ms, p95 {summary['latency_ms']['p95']} ms")
    if args.split == "dev":
        for row in rows:
            if not row["correct"]:
                print(f"FAIL {row['id']}: missing={row['missing']} forbidden={row['forbidden_found']} "
                      f"period_ok={row['period_ok']} product_ok={row['product_ok']} intents={row['intents']} "
                      f"periods={row['periods']} products={row['products']}")
    if args.json:
        payload = {"split": args.split, "summary": summary}
        if args.split == "dev":
            payload["rows"] = rows
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
