"""
KEEL - Subscription Floor Price (Master Pricing Model).

cost_ledger.py's own docstring already named this gap: it deliberately
excludes server/hardware depreciation and other PERIOD costs from its
per-scrape gate, and says those "belong in a separate periodic (e.g.
monthly) margin report computed from real infrastructure bills divided by
real request volume". This module is that report - the Subscription
Pricing & Finance team's own formula for the minimum price a subscription
tier must charge to keep a real risk margin, given what this deployment
is actually spending:

    Subscription Floor Price = (Variable Cost + Server Allocation) / (1 - Risk Margin Ratio)

- Variable Cost: real, known scraping spend (cost_ledger.py's own
  scraping_cost_ledger rows - the same per-request vendor costs that
  table already tracks), never a guessed projection.
- Server Allocation: fixed hosting/infra cost, already expressed as a
  per-subscription share (i.e. Total Monthly Hosting Invoice / Total
  Active Subscriptions - that division happens before this module ever
  sees the number, not inside it). A CONFIGURABLE PLACEHOLDER for now
  (SERVER_ALLOCATION_USD) - there's no real hosting invoice or live
  subscription count wired into this deployment yet, so this is an
  explicit stand-in finance can set and swap for the real figure later,
  never a baked-in guess. Same "unconfigured stays honestly unconfigured"
  discipline cost_ledger.py's own _cost_per_request() already follows -
  calculate_tenant_subscription_floor_price() below reports "not
  computed" rather than silently treating a missing allocation as $0,
  which would understate the floor price.
- Risk Margin Ratio: reuses cost_ledger.py's own COST_GATE_MAX_RATIO
  (20% default) for consistency - the same business risk-tolerance
  number the per-product gate already uses, not a second, different
  constant to keep in sync by hand.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.market_scraper.cost_ledger import DEFAULT_GATE_WINDOW_DAYS, DEFAULT_MAX_COST_TO_MARGIN_RATIO

_SERVER_ALLOCATION_ENV = "SERVER_ALLOCATION_USD"


def _server_allocation_usd() -> Optional[float]:
    """None (never a guessed number) until a real per-subscription
    hosting-cost allocation is configured."""
    raw = os.getenv(_SERVER_ALLOCATION_ENV)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def calculate_subscription_floor_price(
    variable_cost_usd: float, server_allocation_usd: float, risk_margin_ratio: float = DEFAULT_MAX_COST_TO_MARGIN_RATIO,
) -> float:
    """
    The pure formula, no database involved - callers who already have
    their own real variable-cost figure (a blended number across
    tenants, say, rather than one tenant's own real spend) can call this
    directly instead of going through calculate_tenant_subscription_floor_price()
    below.
    """
    if not (0 <= risk_margin_ratio < 1):
        raise ValueError(f"risk_margin_ratio must be in [0, 1) - got {risk_margin_ratio!r}")
    return round((variable_cost_usd + server_allocation_usd) / (1 - risk_margin_ratio), 2)


def sum_real_variable_cost(conn, tenant_id: str, window_days: int = DEFAULT_GATE_WINDOW_DAYS) -> float:
    """
    Real, known (cost_amount IS NOT NULL) scraping spend for one tenant
    across every collector and every mapped product, in the trailing
    window - reuses cost_ledger.py's own scraping_cost_ledger rows
    directly rather than re-deriving them. 0.0 is a real, honest answer
    (a tenant that recorded zero non-null-cost ledger rows this window
    really did spend zero known cost) - unlike cost_ledger.py's own
    per-product None-vs-zero distinction, which exists only because a
    single product with no ledger rows yet is genuinely "unknown, not
    confirmed zero"; summing a tenant's whole real ledger history over a
    real window doesn't carry that same ambiguity.
    """
    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT SUM(cost_amount) FROM scraping_cost_ledger "
            "WHERE tenant_id = %s AND observed_at >= %s AND cost_amount IS NOT NULL;",
            (tenant_id, window_start),
        )
        total = cursor.fetchone()[0]
    return float(total) if total is not None else 0.0


@dataclass(frozen=True)
class SubscriptionFloorPriceResult:
    computed: bool
    reason: str
    floor_price: Optional[float]
    variable_cost: Optional[float]
    server_allocation: Optional[float]
    risk_margin_ratio: float
    window_days: int

    def as_dict(self) -> dict:
        return {
            "computed": self.computed,
            "reason": self.reason,
            "floor_price": self.floor_price,
            "variable_cost": self.variable_cost,
            "server_allocation": self.server_allocation,
            "risk_margin_ratio": self.risk_margin_ratio,
            "window_days": self.window_days,
        }


def calculate_tenant_subscription_floor_price(
    conn, tenant_id: str,
    window_days: int = DEFAULT_GATE_WINDOW_DAYS,
    server_allocation_usd: Optional[float] = None,
    risk_margin_ratio: float = DEFAULT_MAX_COST_TO_MARGIN_RATIO,
) -> SubscriptionFloorPriceResult:
    """
    The real-data convenience wrapper: sums one tenant's own real
    variable cost (sum_real_variable_cost()) and combines it with a
    server allocation (the server_allocation_usd argument when the
    caller has one, else SERVER_ALLOCATION_USD from the environment) via
    calculate_subscription_floor_price() above. Reports computed=False
    (never a fabricated $0 allocation) when neither source has a real
    number yet - the Action Required item this whole module exists to
    eventually close.
    """
    resolved_server_allocation = server_allocation_usd if server_allocation_usd is not None else _server_allocation_usd()
    if resolved_server_allocation is None:
        return SubscriptionFloorPriceResult(
            computed=False,
            reason=(
                f"{_SERVER_ALLOCATION_ENV} is not configured - Server Allocation is a real, required "
                "input to this formula (this deployment's own fixed hosting/infra cost share), never "
                "guessed as $0. Set it (a configurable placeholder, per finance's own direction, until "
                "a real Total Monthly Hosting Invoice / Total Active Subscriptions figure replaces it) "
                "to compute a real floor price."
            ),
            floor_price=None, variable_cost=None, server_allocation=None,
            risk_margin_ratio=risk_margin_ratio, window_days=window_days,
        )

    variable_cost = sum_real_variable_cost(conn, tenant_id, window_days)
    floor_price = calculate_subscription_floor_price(variable_cost, resolved_server_allocation, risk_margin_ratio)
    return SubscriptionFloorPriceResult(
        computed=True,
        reason=(
            f"real variable cost ({variable_cost:.2f}) + server allocation "
            f"({resolved_server_allocation:.2f}), divided by (1 - {risk_margin_ratio:.0%} risk margin), "
            f"over the last {window_days} days"
        ),
        floor_price=floor_price, variable_cost=variable_cost, server_allocation=resolved_server_allocation,
        risk_margin_ratio=risk_margin_ratio, window_days=window_days,
    )
