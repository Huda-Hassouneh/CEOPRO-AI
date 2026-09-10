"""Evaluate/persist a collection-source policy decision, and manage its
paid-vendor credentials.

Two subcommands:
  register-source   Evaluate and persist the policy decision for a source
                     (the original, only behavior this file used to have).
  set-credentials    Write connection_credentials_vault for an existing
                     source - the real replacement for a raw SQL UPDATE,
                     the only way this was previously done.
"""

import argparse
import json
import sys

from src.market_scraper import data_access
from src.market_scraper.policy import SourceCapabilities, evaluate_source


def tri_state(value: str):
    return {"yes": True, "no": False, "unknown": None}[value]


def _add_register_source_parser(subparsers):
    parser = subparsers.add_parser(
        "register-source", help="Evaluate and persist a source's collection policy decision.",
    )
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
    parser.add_argument(
        "--collector",
        choices=(
            "standards", "books_to_scrape", "google_places", "amazon_paapi",
            "digikey_api", "mouser_api", "social_data_provider", "scrape_creators",
        ),
        default="standards",
    )
    parser.add_argument("--render-javascript", action="store_true")
    parser.add_argument("--approval-reference")
    parser.add_argument("--approved-by", help="UUID of the accountable reviewer")
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--contains-personal-data", action="store_true")
    parser.set_defaults(func=_run_register_source)
    return parser


def _run_register_source(args, parser):
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


def _add_set_credentials_parser(subparsers):
    parser = subparsers.add_parser(
        "set-credentials",
        help="Write a source's connection_credentials_vault (Apify/Digi-Key/Mouser/ScrapeCreators/etc token).",
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--source-id", required=True, help="An existing source, already created via register-source.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--credentials",
        help='Inline JSON, e.g. \'{"api_token": "..."}\'. Prefer --credentials-file when possible - '
             "this puts the secret in your shell history.",
    )
    group.add_argument(
        "--credentials-file",
        help="Path to a JSON file containing the credentials object - the secret never touches "
             "shell history this way.",
    )
    parser.set_defaults(func=_run_set_credentials)
    return parser


def _run_set_credentials(args, parser):
    if args.credentials_file:
        with open(args.credentials_file) as f:
            raw = f.read()
    else:
        raw = args.credentials
    source_flag = "--credentials-file" if args.credentials_file else "--credentials"
    try:
        credentials = json.loads(raw)
    except json.JSONDecodeError as exc:
        parser.error(f"{source_flag} is not valid JSON: {exc}")
        return
    if not isinstance(credentials, dict):
        parser.error('credentials must be a JSON object, e.g. {"api_token": "..."}')
        return

    connection = data_access.get_tenant_connection(args.tenant_id)
    try:
        data_access.set_source_credentials(connection, args.tenant_id, args.source_id, credentials)
    except ValueError as exc:
        parser.error(str(exc))
        return
    finally:
        connection.close()
    print(f"Credentials set for source {args.source_id} ({', '.join(sorted(credentials))}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_register_source_parser(subparsers)
    _add_set_credentials_parser(subparsers)
    args = parser.parse_args()
    args.func(args, parser)


if __name__ == "__main__":
    main()
