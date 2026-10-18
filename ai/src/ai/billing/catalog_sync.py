"""
Reconciles KEEL's plan catalog (billing_plan_prices) with the Stripe account
before anything is created, so the sync is safely repeatable on its own - it
never leans on Stripe idempotency keys, which expire after 24 hours.

For every self-serve plan price that has no stripe_price_id yet:
  ADOPT   an existing active Stripe price on the KEEL product already matches
          (same plan_key + period_code metadata, amount, currency and billing
          interval): link it, create nothing.
  CREATE  none matches: create exactly one (the old one, if the amount changed,
          is reported as SUPERSEDED and left for a person to archive).
For every row that already has a stripe_price_id:
  VERIFY  that price still exists, is active, and matches amount/currency/
          interval - drift is reported, never silently "fixed".
More than one matching price is reported as DUPLICATE: the oldest is adopted,
the rest are listed to archive by hand; nothing new is created.

Pure planning (plan()) is separate from applying (apply()) so --dry-run and the
tests see exactly what a real run would do.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

PRODUCT_NAME = "KEEL"
PRODUCT_METADATA = {"app": "apex"}


class CatalogError(Exception):
    """The Stripe account and the database disagree in a way a person must resolve."""


@dataclass
class Action:
    kind: str                       # adopt | create | verify_ok | drift | missing | duplicate | superseded
    label: str
    price_row_id: Optional[str] = None
    stripe_price_id: Optional[str] = None
    detail: str = ""
    params: dict = field(default_factory=dict)   # for create


def minor_units(amount: float, currency: str) -> int:
    zero_decimal = {"jpy", "krw", "vnd", "clp", "xaf", "xof", "xpf", "bif", "djf", "gnf", "kmf", "mga", "pyg", "rwf", "ugx", "vuv"}
    return int(round(amount)) if currency.lower() in zero_decimal else int(round(amount * 100))


def pick_product(products: List[dict], configured_id: Optional[str]) -> Optional[str]:
    """The KEEL product id to use, or None when one must be created."""
    if configured_id:
        if not any(p["id"] == configured_id for p in products):
            raise CatalogError(f"STRIPE_PRODUCT_ID {configured_id} is not an active product in this Stripe account.")
        return configured_id
    ours = [p for p in products if p.get("name") == PRODUCT_NAME and (p.get("metadata") or {}).get("app") == PRODUCT_METADATA["app"]]
    if len(ours) > 1:
        ids = ", ".join(sorted(p["id"] for p in ours))
        raise CatalogError(f"{len(ours)} active '{PRODUCT_NAME}' products exist ({ids}). Set STRIPE_PRODUCT_ID to the right one.")
    return ours[0]["id"] if ours else None


def _matches(stripe_price: dict, plan_key: str, period: str, months: int, unit_amount: int, currency: str) -> bool:
    recurring = stripe_price.get("recurring") or {}
    meta = stripe_price.get("metadata") or {}
    return (stripe_price.get("active", True) and stripe_price.get("unit_amount") == unit_amount
            and (stripe_price.get("currency") or "").lower() == currency.lower()
            and recurring.get("interval") == "month" and recurring.get("interval_count") == months
            and meta.get("plan_key") == plan_key and meta.get("period_code") == period)


def plan(rows: List[dict], stripe_prices: List[dict], product_id: Optional[str]) -> List[Action]:
    """rows: billing_plan_prices (price_id, plan_key, display_name, period_code, interval_months,
    amount, currency, stripe_price_id). stripe_prices: active prices on the KEEL product."""
    by_id = {p["id"]: p for p in stripe_prices}
    claimed = {r["stripe_price_id"] for r in rows if r["stripe_price_id"]}
    actions: List[Action] = []
    for row in rows:
        unit = minor_units(float(row["amount"]), row["currency"])
        label = f'{row["display_name"]} - {row["period_code"]} - {row["amount"]} {row["currency"]}'
        if row["stripe_price_id"]:
            live = by_id.get(row["stripe_price_id"])
            if live is None:
                actions.append(Action("missing", label, row["price_id"], row["stripe_price_id"],
                                      "recorded in the database but not an active price on the KEEL product"))
            elif _matches(live, row["plan_key"], row["period_code"], row["interval_months"], unit, row["currency"]):
                actions.append(Action("verify_ok", label, row["price_id"], row["stripe_price_id"]))
            else:
                actions.append(Action("drift", label, row["price_id"], row["stripe_price_id"],
                                      "amount/currency/interval/metadata differ from the database"))
            continue
        candidates = sorted((p for p in stripe_prices if p["id"] not in claimed
                             and _matches(p, row["plan_key"], row["period_code"], row["interval_months"], unit, row["currency"])),
                            key=lambda p: p.get("created", 0))
        if candidates:
            actions.append(Action("adopt", label, row["price_id"], candidates[0]["id"]))
            claimed.add(candidates[0]["id"])
            for extra in candidates[1:]:
                actions.append(Action("duplicate", label, None, extra["id"], "same plan/period/amount - archive it in Stripe"))
            continue
        stale = [p["id"] for p in stripe_prices if p["id"] not in claimed
                 and (p.get("metadata") or {}).get("plan_key") == row["plan_key"]
                 and (p.get("metadata") or {}).get("period_code") == row["period_code"]]
        for old in stale:
            actions.append(Action("superseded", label, None, old, "older price for this plan/period with a different amount - archive it after switching"))
        actions.append(Action("create", label, row["price_id"], None, params={
            "product": product_id, "currency": row["currency"].lower(), "unit_amount": unit,
            "recurring": {"interval": "month", "interval_count": row["interval_months"]},
            "nickname": f'KEEL {row["display_name"]} ({row["period_code"]})',
            "metadata": {"plan_key": row["plan_key"], "period_code": row["period_code"]}}))
    return actions


def apply(actions: List[Action], link: Callable[[str, str], None], create_price: Callable[[dict], dict]) -> Dict[str, int]:
    """Performs adopt/create. link(price_row_id, stripe_price_id) records it (and commits)."""
    done = {"adopted": 0, "created": 0}
    for a in actions:
        if a.kind == "adopt":
            link(a.price_row_id, a.stripe_price_id)
            done["adopted"] += 1
        elif a.kind == "create":
            created = create_price(a.params)
            link(a.price_row_id, created["id"])
            a.stripe_price_id = created["id"]
            done["created"] += 1
    return done


def problems(actions: List[Action]) -> List[Action]:
    return [a for a in actions if a.kind in ("drift", "missing")]
