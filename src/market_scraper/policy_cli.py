"""Evaluate, persist, and audit a collection-source policy decision."""

import argparse

from src.market_scraper import data_access
from src.market_scraper.policy import SourceCapabilities, evaluate_source


def tri_state(value: str):
    return {"yes": True, "no": False, "unknown": None}[value]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--official-api-url")
    parser.add_argument("--rss-url")
    parser.add_argument("--structured-data", action="store_true")
    parser.add_argument("--public-web", action="store_true")
    parser.add_argument("--terms-permit", choices=("yes", "no", "unknown"), default="unknown")
    parser.add_argument("--technical-controls-permit", choices=("yes", "no", "unknown"), default="unknown")
    parser.add_argument("--rate-limit", type=int, default=30)
    parser.add_argument("--collector", choices=("standards", "books_to_scrape"), default="standards")
    parser.add_argument("--render-javascript", action="store_true")
    parser.add_argument("--approval-reference")
    parser.add_argument("--approved-by", help="UUID of the accountable reviewer")
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--contains-personal-data", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.rate_limit <= 600:
        parser.error("--rate-limit must be between 1 and 600 requests per minute")
    if not 1 <= args.retention_days <= 3650:
        parser.error("--retention-days must be between 1 and 3650")

    decision = evaluate_source(SourceCapabilities(
        source_url=args.source_url,
        official_api_url=args.official_api_url,
        rss_url=args.rss_url,
        has_structured_data=args.structured_data,
        public_web_collection_possible=args.public_web,
        terms_permit_collection=tri_state(args.terms_permit),
        technical_controls_permit_collection=tri_state(args.technical_controls_permit),
    ))
    if decision.status.value == "ALLOWED" and not (
        args.approval_reference and args.approved_by
    ):
        parser.error("ALLOWED sources require --approval-reference and --approved-by")
    connection = data_access.get_tenant_connection(args.tenant_id)
    try:
        data_access.record_policy_decision(
            connection,
            args.tenant_id,
            args.source_id,
            decision,
            restrictions={
                "terms_review": args.terms_permit,
                "technical_controls_review": args.technical_controls_permit,
            },
            rate_limit=args.rate_limit,
            collector_key=args.collector,
            render_javascript=args.render_javascript,
            approval_reference=args.approval_reference,
            approved_by=args.approved_by,
            retention_days=args.retention_days,
            contains_personal_data=args.contains_personal_data,
        )
    finally:
        connection.close()
    print(f"{decision.status.value}: {decision.method.value if decision.method else 'NONE'}")
    print(decision.justification)


if __name__ == "__main__":
    main()
