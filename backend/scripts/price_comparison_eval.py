"""
Accuracy of the price comparison tiers, and a worksheet to label YOUR OWN data.

  python -m scripts.price_comparison_eval score [--csv FILE] [--split dev|holdout|all] [--oracle] [--failures]
      Scores the classifier against a labelled CSV (default: the committed set).
  python -m scripts.price_comparison_eval export --tenant TENANT_ID --out worksheet.csv [--limit 300] [--negatives 0.25]
      Reads one company's stored competitor items and products (DATABASE_URL) and writes pairs the classifier
      relates, plus a share of unrelated pairs, with its prediction in `predicted`. Fill the `label` column
      (EXACT | EQUIVALENT | SIMILAR | ADDED_VALUE | NONE; `direction` for SIMILAR) and score the file with
      `score --csv worksheet.csv`. Read-only; nothing is written to the database.
"""
import argparse
import csv
import os
import random
import sys
from pathlib import Path

from src.market_scraper.price_comparison import evaluate, tiers

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "src" / "market_scraper" / "tests" / "data" / "price_comparison_labelled.csv"


def _score(args) -> int:
    rows = evaluate.load_labelled(args.csv)
    if args.split != "all":
        rows = [r for r in rows if r.get("split") == args.split]
    judge_for = None
    if args.oracle:
        judge_for = lambda row: (lambda own, item, side, words: "addition" if row["label"] == tiers.ADDED_VALUE and side == "own" else "variant")  # noqa: E731
    report = evaluate.score(rows, judge_for)
    print(evaluate.format_report(report, f"{args.split} set" + (" with an oracle judge" if args.oracle else "")))
    if args.failures:
        print("\nnot correct:")
        for r in evaluate.failures(report):
            print(f"  {r['id']} [{r['outcome']}] label={r['label']} predicted={r['pred']['tier']}"
                  f"{'/' + str(r['pred'].get('shown_as')) if r['pred']['tier'] == evaluate.HELD else ''}"
                  f" ({r['pred'].get('direction')}) | {r['own_name']!r} vs {r['item_name']!r}  [{r['kind']}]")
    return 0


def _export(args) -> int:
    import psycopg2

    from src.market_scraper.market_discovery import offerings
    from src.market_scraper.price_comparison import engine

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_tenant_id', %s, false);", (args.tenant,))
        products = offerings.company_products(conn, args.tenant)
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT global_competitor_id FROM competitor_intel WHERE tenant_id = %s AND kind = 'product';", (args.tenant,))
            competitor_ids = [str(r[0]) for r in cursor.fetchall()]
        rng = random.Random(args.seed)
        related, unrelated = [], []
        for competitor_id in competitor_ids:
            items = [i for i in offerings.competitor_items(conn, args.tenant, competitor_id) if i.get("price") is not None and i.get("currency")]
            for product in products:
                found = {e["item"]["name"]: e for e in engine.compare(product, items)}
                for item in items:
                    if item.get("currency") != product.get("currency"):
                        continue
                    base = {"own_name": product["name"], "own_name_alt": product.get("name_alt") or "", "own_price": product["price"],
                            "item_name": item.get("name"), "item_price": item["price"]}
                    entry = found.get(item.get("name"))
                    (related if entry else unrelated).append({**base, "predicted": entry["tier"] if entry else "NONE"})
    finally:
        conn.close()
    rng.shuffle(related)
    rng.shuffle(unrelated)
    picked = related[: args.limit] + unrelated[: int(args.limit * args.negatives)]
    rng.shuffle(picked)
    cols = ["id", "split", "company", "own_name", "own_name_alt", "own_price", "item_name", "item_price", "predicted",
            "label", "direction", "kind", "note"]
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        for i, row in enumerate(picked):
            writer.writerow({"id": f"w{i + 1:04d}", "split": "all", "company": args.tenant, "label": "", "direction": "", "kind": "clear", "note": "", **row})
    print(f"wrote {len(picked)} pairs ({min(len(related), args.limit)} related, {len(picked) - min(len(related), args.limit)} unrelated) to {args.out}; "
          "fill the label column, then: score --csv " + args.out)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("--csv", default=str(DEFAULT_CSV))
    score.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    score.add_argument("--oracle", action="store_true", help="settle unsettled pairs with the label: the rules' ceiling")
    score.add_argument("--failures", action="store_true")
    export = sub.add_parser("export")
    export.add_argument("--tenant", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--limit", type=int, default=300)
    export.add_argument("--negatives", type=float, default=0.25)
    export.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    return _score(args) if args.command == "score" else _export(args)


if __name__ == "__main__":
    sys.exit(main())
