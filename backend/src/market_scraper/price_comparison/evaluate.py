"""
Scores the tier classifier against a hand-labelled set of (own product, competitor item) pairs.

A labelled row: own_name [own_name_alt] own_price | item_name item_price | label (EXACT | EQUIVALENT | SIMILAR |
ADDED_VALUE | NONE) | direction (SIMILAR rows: own_richer | own_leaner | same, blank = not scored) | kind (clear |
judgement) | split (dev | holdout).

Each row is run through engine.compare() - the code path production uses - and ends as one of:
  correct   the predicted tier is the label (NONE = nothing surfaced)
  held      the pair was left unsettled (an extra word the rules cannot place): not an error, but not an answer
  wrong     anything else

The numbers that matter most are the ones that put a wrong number in front of an owner or into a recommendation:
`exact_precision` (what is shown as exact really is), `like_for_like_precision` (EXACT + EQUIVALENT + same-direction
SIMILAR) and `false_relation_rate` (unrelated items shown as related).
"""
import csv
from collections import Counter, defaultdict
from typing import Callable, Dict, Iterable, List, Optional

from src.market_scraper.price_comparison import engine, tiers

NONE = "NONE"
HELD = "HELD"
LABELS = (*tiers.TIERS, NONE)
RELATED = tiers.TIERS


def load_labelled(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("label") or "").strip()]
    for row in rows:
        row["label"] = row["label"].strip().upper()
        if row["label"] not in LABELS:
            raise ValueError(f"{row.get('id')}: unknown label {row['label']!r}")
        row["own_price"], row["item_price"] = float(row["own_price"]), float(row["item_price"])
    return rows


def predict(row: dict, judge: Optional[Callable] = None) -> dict:
    """{"tier": a tier | NONE | HELD, "direction": ..., "ambiguous": ...} for one labelled row."""
    product = {"product_id": row.get("id") or "x", "name": row["own_name"], "name_alt": row.get("own_name_alt") or None,
               "price": row["own_price"], "currency": "XXX"}
    item = {"name": row["item_name"], "price": row["item_price"], "currency": "XXX"}
    found = engine.compare(product, [item], judge)
    if not found:
        return {"tier": NONE, "direction": None, "ambiguous": None}
    best = max(found, key=lambda e: e["comparison"].match_score)["comparison"]
    return {"tier": HELD if best.ambiguous else best.tier, "direction": best.direction,
            "ambiguous": best.ambiguous, "shown_as": best.tier}


def outcome(row: dict, pred: dict) -> str:
    if pred["tier"] == row["label"]:
        return "correct"
    if pred["tier"] == HELD and row["label"] in RELATED:
        return "held"
    return "wrong"


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 3) if den else None


def score(rows: Iterable[dict], judge_for: Optional[Callable[[dict], Callable]] = None) -> dict:
    """judge_for(row) -> a judge for that row (an oracle for the rules' ceiling), or None for rules only."""
    results = []
    for row in rows:
        pred = predict(row, judge_for(row) if judge_for else None)
        results.append({**row, "pred": pred, "outcome": outcome(row, pred)})

    counts = Counter(r["outcome"] for r in results)
    total = len(results)
    confusion: Dict[str, Counter] = defaultdict(Counter)
    for r in results:
        confusion[r["label"]][r["pred"]["tier"]] += 1

    shown = [r for r in results if r["pred"]["tier"] in RELATED]
    exact_shown = [r for r in results if r["pred"]["tier"] == tiers.EXACT]
    like = [r for r in results if r["pred"]["tier"] in (tiers.EXACT, tiers.EQUIVALENT)
            or (r["pred"]["tier"] == tiers.SIMILAR and r["pred"]["direction"] == tiers.SAME)]
    none_rows = [r for r in results if r["label"] == NONE]
    related_rows = [r for r in results if r["label"] in RELATED]
    dir_rows = [r for r in results if r["label"] == tiers.SIMILAR and r.get("direction") and r["pred"]["tier"] == tiers.SIMILAR]

    per_tier = {}
    for tier in tiers.TIERS:
        tp = sum(1 for r in results if r["label"] == tier and r["pred"]["tier"] == tier)
        predicted = sum(1 for r in results if r["pred"]["tier"] == tier)
        actual = sum(1 for r in results if r["label"] == tier)
        per_tier[tier] = {"precision": _ratio(tp, predicted), "recall": _ratio(tp, actual), "predicted": predicted, "actual": actual}

    return {
        "rows": total,
        "correct": counts["correct"], "held": counts["held"], "wrong": counts["wrong"],
        "accuracy": _ratio(counts["correct"], total),
        "accuracy_when_settled": _ratio(counts["correct"], total - counts["held"]),
        "held_rate": _ratio(counts["held"], total),
        "exact_precision": _ratio(sum(1 for r in exact_shown if r["label"] == tiers.EXACT), len(exact_shown)),
        "like_for_like_precision": _ratio(sum(1 for r in like if r["label"] in (tiers.EXACT, tiers.EQUIVALENT) or
                                              (r["label"] == tiers.SIMILAR and r.get("direction") in ("same", ""))), len(like)),
        "false_relation_rate": _ratio(sum(1 for r in none_rows if r["pred"]["tier"] in RELATED or r["pred"]["tier"] == HELD), len(none_rows)),
        "missed_relation_rate": _ratio(sum(1 for r in related_rows if r["pred"]["tier"] == NONE), len(related_rows)),
        "direction_accuracy": _ratio(sum(1 for r in dir_rows if r["pred"]["direction"] == r["direction"]), len(dir_rows)),
        "per_tier": per_tier,
        "confusion": {label: dict(confusion[label]) for label in LABELS if label in confusion},
        "by_kind": {kind: _ratio(sum(1 for r in results if r["kind"] == kind and r["outcome"] == "correct"),
                                 sum(1 for r in results if r["kind"] == kind)) for kind in ("clear", "judgement")},
        "results": results,
    }


def format_report(report: dict, title: str = "") -> str:
    pct = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    lines = [f"== {title or 'price comparison accuracy'} ({report['rows']} pairs) =="]
    lines.append(f"correct {report['correct']}  held-for-review {report['held']}  wrong {report['wrong']}   "
                 f"accuracy {pct(report['accuracy'])} (of settled: {pct(report['accuracy_when_settled'])})")
    lines.append(f"exact precision {pct(report['exact_precision'])} | like-for-like precision {pct(report['like_for_like_precision'])} | "
                 f"false relations {pct(report['false_relation_rate'])} | missed relations {pct(report['missed_relation_rate'])} | "
                 f"direction {pct(report['direction_accuracy'])}")
    lines.append(f"accuracy on clear pairs {pct(report['by_kind']['clear'])}, on judgement calls {pct(report['by_kind']['judgement'])}")
    lines.append("per tier:  " + "   ".join(f"{t} P {pct(v['precision'])} R {pct(v['recall'])}" for t, v in report["per_tier"].items()))
    predicted = [*tiers.TIERS, HELD, NONE]
    lines.append("label \\ predicted".ljust(18) + "".join(p[:9].rjust(11) for p in predicted))
    for label, cells in report["confusion"].items():
        lines.append(label.ljust(18) + "".join(str(cells.get(p, 0)).rjust(11) for p in predicted))
    return "\n".join(lines)


def failures(report: dict, kinds=("wrong", "held")) -> List[dict]:
    return [r for r in report["results"] if r["outcome"] in kinds]
