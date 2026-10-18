"""
Phase 0 diagnostic: how complete is each competitor's data, and WHY not?

Read-only. Run it against the real database (tenant-scoped, so RLS applies
exactly as it does for the app) to confirm where the gaps come from before
trusting any fix:

    SCRAPER_DATABASE_URL=postgresql://ceopro_app:...@host/db \\
    SCRAPER_ACTOR_USER_ID=<uuid> \\
        python scripts/competitor_coverage_report.py --tenant-id <uuid>

It prints (1) which discovery/enrichment keys are configured in THIS
process's environment - run it in the same container/env as the discovery
worker to see what that worker sees - and (2) per competitor: the
data-completeness facets and reasons the dashboard shows, plus the raw counts
behind them, and a summary of the dominant cause.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.market_scraper import competitor_enrichment, data_access  # noqa: E402

ENV_KEYS = (
    "GOOGLE_PLACES_API_KEY", "GOOGLE_CUSTOM_SEARCH_API_KEY", "GOOGLE_CUSTOM_SEARCH_CX",
    "SEARXNG_INSTANCE_URL", "SCRAPER_ACTOR_USER_ID",
)


def _env_report() -> None:
    print("Environment (this process):")
    for key in ENV_KEYS:
        print(f"  {key:32s} {'SET' if os.getenv(key) else 'MISSING'}")
    print()


def _counts(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.competitor_name, gc.website_url, gc.google_place_id IS NOT NULL,
                   gc.rating IS NOT NULL, gc.social_profiles IS NOT NULL, tc.discovery_method, tc.tier,
                   (SELECT COUNT(*) FROM competitor_product_mappings m WHERE m.tenant_id = tc.tenant_id AND m.global_competitor_id = gc.global_competitor_id),
                   (SELECT COUNT(*) FROM competitor_product_mappings m JOIN data_sources d ON d.tenant_id = m.tenant_id AND d.source_id = m.source_id
                     WHERE m.tenant_id = tc.tenant_id AND m.global_competitor_id = gc.global_competitor_id AND d.policy_status = 'ALLOWED')
            FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE
            ORDER BY gc.competitor_name;
            """,
            (tenant_id,),
        )
        return {str(r[0]): r[1:] for r in cursor.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()

    _env_report()
    conn = data_access.get_tenant_connection(args.tenant_id)
    try:
        raw = _counts(conn, args.tenant_id)
        completeness = competitor_enrichment.load_data_completeness(conn, args.tenant_id)
    finally:
        conn.close()

    if not raw:
        print("No tracked competitors for this tenant.")
        return 0

    causes: Counter = Counter()
    for cid, (name, website, has_place, has_rating, has_social, method, tier, mappings, allowed) in raw.items():
        report = completeness.get(cid, {"score": 0, "facets": {}})
        print(f"{name}  [{tier}, via {method or 'MANUAL'}]  completeness={report['score']}%")
        print(f"    website={website or '-'}  place_id={'yes' if has_place else 'no'}  rating={'yes' if has_rating else 'no'}  "
              f"social={'yes' if has_social else 'no'}  mappings={mappings} (ALLOWED sources: {allowed})")
        for facet, info in report["facets"].items():
            if info["status"] == competitor_enrichment.STATUS_SUCCEEDED:
                line = f"{info['items_found']} item(s)"
            else:
                line = f"{info['reason_code']}: {info['reason_detail']}"
                causes[(facet, info["reason_code"])] += 1
            print(f"    {facet:15s} {info['status']:15s} {line}")
        print()
    total = len(raw)
    print(f"Summary over {total} competitor(s) - most common gaps:")
    for (facet, reason), count in causes.most_common(10):
        print(f"  {count:4d}/{total}  {facet:15s} {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
