"""
Operator tool for KEEL billing: confirmed provider prices, spending caps and
kill switches, Custom contracts, manual credit adjustments, reconciliation,
and the recommended plan budgets. Every change is recorded in
entitlement_audit_log with who approved it and why. There is no customer
API for any of this.

Usage (from backend/, with DATABASE_URL set to the schema-owning role):
    python -m scripts.billing_admin budgets
    python -m scripts.billing_admin set-price --budget ai --provider groq --operation openai/gpt-oss-20b \\
        --unit input_token --usd-per-million 0.075 --source "Groq pricing page" --verified-on 2026-10-17 \\
        --by "Name" --reason "Confirmed from the Groq invoice"
    python -m scripts.billing_admin set-price --budget data --provider google_places --operation text_search \\
        --unit request --usd 0.032 --source "Google Maps Platform bill" --verified-on 2026-10-17 --by "Name" --reason "..."
    python -m scripts.billing_admin set-control --provider '*' --kill-switch on --by "Name" --reason "Incident 42"
    python -m scripts.billing_admin set-control --provider groq --monthly-cap-usd 200 --by "Name" --reason "..."
    python -m scripts.billing_admin set-contract --tenant <id> --contract-ref C-2026-001 --by "Name" --reason "..." \\
        --monthly-price 900 --limit tracked_products=2000 --limit data_credits=9000 --limit ai_credits=9000
    python -m scripts.billing_admin adjust-credits --tenant <id> --budget ai --credits -100 --reference T-7 --by "Name" --reason "..."
    python -m scripts.billing_admin reconcile --ledger <id> --actual-usd 0.84 --reference apify-run-123 --by "Name"
    python -m scripts.billing_admin expire-reservations
"""
import argparse
import json
import os
import sys
from datetime import date
from decimal import Decimal

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.billing import admin, cost_model, credits  # noqa: E402


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def _limits(pairs) -> dict:
    out = {}
    for pair in pairs or []:
        feature, _, value = pair.partition("=")
        if not value:
            raise admin.AdminError(f"--limit needs feature=value, got {pair!r}")
        out[feature.strip()] = int(value)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KEEL billing operations.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("budgets", help="the recommended Data/AI Credit budget per plan (cost model)")

    p = sub.add_parser("set-price")
    p.add_argument("--budget", required=True, choices=["data", "ai"])
    p.add_argument("--provider", required=True)
    p.add_argument("--operation", required=True, help="AI: the model id ('*' = every model of the provider)")
    p.add_argument("--unit", required=True)
    price = p.add_mutually_exclusive_group(required=True)
    price.add_argument("--usd", type=Decimal, help="USD per unit")
    price.add_argument("--usd-per-million", type=Decimal, help="USD per million units (token prices)")
    p.add_argument("--safety-margin", type=Decimal)
    p.add_argument("--not-charged-on-failure", action="store_true")
    p.add_argument("--not-final", action="store_true", help="the provider bills later; reconcile these calls")
    p.add_argument("--source", required=True)
    p.add_argument("--verified-on", required=True, type=date.fromisoformat)
    p.add_argument("--if-missing", action="store_true", help="keep a price that is already recorded")

    c = sub.add_parser("set-control")
    c.add_argument("--provider", required=True, help="'*' for every provider, or provider:model")
    c.add_argument("--monthly-cap-usd", type=Decimal)
    c.add_argument("--clear-cap", action="store_true")
    c.add_argument("--kill-switch", choices=["on", "off"])

    k = sub.add_parser("set-contract")
    k.add_argument("--tenant", required=True)
    k.add_argument("--contract-ref", required=True)
    k.add_argument("--monthly-price", type=Decimal)
    k.add_argument("--currency", default="USD")
    k.add_argument("--trial-days", type=int, default=0)
    k.add_argument("--period-months", type=int, default=1)
    k.add_argument("--refresh", choices=["hourly", "daily", "weekly"])
    k.add_argument("--support")
    k.add_argument("--data-source", action="append")
    k.add_argument("--limit", action="append", help="feature=value, e.g. data_credits=9000")

    a = sub.add_parser("adjust-credits")
    a.add_argument("--tenant", required=True)
    a.add_argument("--budget", required=True, choices=["data", "ai"])
    a.add_argument("--credits", required=True, type=Decimal, help="negative gives credits back")
    a.add_argument("--reference", required=True)

    r = sub.add_parser("reconcile")
    r.add_argument("--ledger", required=True)
    r.add_argument("--actual-usd", required=True, type=Decimal)
    r.add_argument("--reference", required=True)

    sub.add_parser("expire-reservations")

    for command in (p, c, k, a, r):
        command.add_argument("--by", required=True, help="who approved this (recorded)")
    for command in (p, c, k, a):
        command.add_argument("--reason", required=True)
    r.add_argument("--reason", default="provider-reported usage")

    args = parser.parse_args(argv)
    if args.command == "budgets":
        print(json.dumps({key: b.as_dict() for key, b in cost_model.recommended_budgets().items()}, indent=2))
        return 0

    conn = _connect()
    try:
        if args.command == "set-price":
            unit_cost = args.usd if args.usd is not None else args.usd_per_million / Decimal(1_000_000)
            written = admin.set_price(conn, budget_kind=args.budget, provider=args.provider, operation=args.operation,
                                      unit=args.unit, unit_cost_usd=unit_cost, source=args.source,
                                      verified_on=args.verified_on, approved_by=args.by, reason=args.reason,
                                      safety_margin=args.safety_margin, charged_on_failure=not args.not_charged_on_failure,
                                      cost_is_final=not args.not_final, if_missing=args.if_missing)
            if not written:
                print(f"Kept: {args.provider}/{args.operation} {args.unit} already has a recorded price.")
        elif args.command == "set-control":
            admin.set_control(conn, provider=args.provider, approved_by=args.by, reason=args.reason,
                              monthly_cap_usd=args.monthly_cap_usd, clear_cap=args.clear_cap,
                              kill_switch=None if args.kill_switch is None else args.kill_switch == "on")
        elif args.command == "set-contract":
            admin.set_custom_contract(conn, tenant_id=args.tenant, contract_ref=args.contract_ref, approved_by=args.by,
                                      reason=args.reason, limits=_limits(args.limit), monthly_price=args.monthly_price,
                                      currency=args.currency, trial_days=args.trial_days, data_sources=args.data_source,
                                      refresh_frequency=args.refresh, support_level=args.support,
                                      period_months=args.period_months)
        elif args.command == "adjust-credits":
            admin.adjust_credits(conn, tenant_id=args.tenant, budget_kind=args.budget, credits_delta=args.credits,
                                 reference=args.reference, approved_by=args.by, reason=args.reason)
        elif args.command == "reconcile":
            delta = credits.reconcile(conn, args.ledger, args.actual_usd, reference=args.reference, actor=args.by,
                                      reason=args.reason)
            print(f"credit difference recorded: {delta}")
        elif args.command == "expire-reservations":
            print(f"expired: {credits.expire_stale_reservations(conn)}")
        conn.commit()
    except admin.AdminError as err:
        conn.rollback()
        print(f"Refused: {err}", file=sys.stderr)
        return 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
