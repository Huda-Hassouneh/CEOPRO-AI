"""
CEOPRO AI - Scraping Cost Ledger & Cost-to-Margin Gate.

The real gap this closes: every scrape this platform runs against a paid
API/vendor (ScrapeCreators, Apify, Digi-Key, Mouser, Google Places, Google
CSE) has a real per-request cost, and nothing anywhere recorded it or
weighed it against what the product being tracked is actually worth. A
$0.15 API call scraped weekly against a $0.80 product is a real, silent
loss - this module makes that loss visible and, if asked, stoppable.

Two halves, deliberately kept separate (the same split this session's own
cost-formula discussion landed on):

1. record_scrape_cost() - the real, per-request LEDGER. Called once per
   real scrape attempt (persistence.py::PostgresPricePipeline wires this
   in - see that module's own comment). This is the only half that writes
   anything.

2. evaluate_cost_margin_gate() - the DYNAMIC GATE. A pure read: sums real,
   KNOWN costs for one product over a rolling window and compares that
   sum against the product's own real margin (or price, when cost_price
   isn't set) as a ratio - never a flat dollar amount. "Never spend more
   than X% of what this product is worth tracking it" scales automatically
   whether the product is $0.50 or $50, and automatically gets stricter
   the moment a vendor raises its real price, since the cost side of the
   ratio is real ledger data, not a number typed in once and forgotten.

Deliberately excluded from both halves: server/hardware depreciation,
electricity, and marketing overhead. Those are real costs, but they are
PERIOD costs (a monthly bill), not per-request events - dividing a
request-level ledger by them would either be a meaningless instant number
(a lone request doesn't "cause" a slice of a server's depreciation) or,
worse, would make a live per-request gate swing on pure traffic-volume
noise rather than the actual scrape economics. Those belong in a separate
periodic (e.g. monthly) margin report computed from real infrastructure
bills divided by real request volume - a planning number, never a live
gate input. Marketing spend doesn't belong in a cost-of-service formula
at all - it's customer acquisition cost, amortized per customer, not per
scrape.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

# Real per-request cost for each collector, in USD, sourced ONLY from an
# explicit env var per collector - deliberately no baked-in default for
# any of them. A guessed number here would be exactly the kind of silent
# fabrication this codebase's own honesty discipline (cold_start.py,
# UNKNOWN evidence records, the "never treat missing as zero" rule
# cost_price already follows) exists to prevent - an unconfigured
# collector's real cost is UNKNOWN, not free, and a ledger row for it
# stays honestly NULL until whoever knows the real vendor rate sets it.
_COST_ENV_PREFIX = "SCRAPE_COST_PER_REQUEST_"

# Rolling window the gate looks back over - matches this codebase's own
# established "recent window, not lifetime-forever" convention (dashboard/
# metrics.py's window_days, competitor_activity.py's MARKET_ACTIVITY_
# WINDOW_DAYS): a product's tracking cost should be judged against its
# recent real spend, not an ever-growing lifetime total that would
# eventually flag every product no matter how cheap it is to keep tracking
# going forward.
DEFAULT_GATE_WINDOW_DAYS = int(os.getenv("COST_GATE_WINDOW_DAYS", "30"))

# The dynamic ratio itself - a business risk-tolerance choice, not a
# researched constant (unlike, say, the real vendor identities in
# pos_erp_presets.py). Default is a starting point: tune it once real
# ledger data exists to see what tracking actually costs in practice.
DEFAULT_MAX_COST_TO_MARGIN_RATIO = float(os.getenv("COST_GATE_MAX_RATIO", "0.20"))

# The hard floor underneath the dynamic ratio above - also a business
# policy choice, not a researched constant. A product whose real price (or
# margin, whichever the ratio itself would use) never clears this floor is
# blocked on day one, before a single real ledger row exists to judge a
# ratio from: fixed team/overhead costs mean a sub-floor product can never
# be made profitable purely by scraping it less often, so there is no
# rolling-window cost pattern that would ever legitimately clear it either.
DEFAULT_MIN_PRODUCT_PRICE = float(os.getenv("COST_GATE_MIN_PRODUCT_PRICE", "1.00"))


def _cost_per_request(collector_key: str) -> Optional[float]:
    """None (never a guessed number) when this collector's real per-
    request cost hasn't been configured for this deployment yet."""
    env_name = _COST_ENV_PREFIX + collector_key.upper()
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def record_scrape_cost(conn, tenant_id: str, mapping_id: str, collector_key: str, currency: str = "USD") -> str:
    """
    Writes one real ledger row for one real scrape attempt against a
    mapped product. Always writes a row (even when the real cost is
    unknown) - a missing row would make an unmetered collector invisible
    to the gate below instead of honestly "we don't know what this costs
    yet", which is a materially different, more dangerous state to be in
    silently.
    """
    cost_amount = _cost_per_request(collector_key)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO scraping_cost_ledger (tenant_id, mapping_id, collector_key, cost_amount, currency)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING cost_id;
            """,
            (tenant_id, mapping_id, collector_key, cost_amount, currency),
        )
        return str(cursor.fetchone()[0])


@dataclass(frozen=True)
class CostMarginGateDecision:
    allow: bool
    reason: str
    cumulative_cost: Optional[float]
    basis_amount: Optional[float]
    basis_kind: Optional[str]  # "margin" | "price" | None (no basis available)
    ratio: Optional[float]
    threshold: float
    window_days: int
    min_product_price: float

    def as_dict(self) -> dict:
        return {
            "allow": self.allow,
            "reason": self.reason,
            "cumulative_cost": self.cumulative_cost,
            "basis_amount": self.basis_amount,
            "basis_kind": self.basis_kind,
            "ratio": self.ratio,
            "threshold": self.threshold,
            "window_days": self.window_days,
            "min_product_price": self.min_product_price,
        }


def _load_product_pricing(conn, tenant_id: str, product_id: str):
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT current_price, cost_price FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;",
            (tenant_id, product_id),
        )
        return cursor.fetchone()


def _load_cumulative_known_cost(conn, tenant_id: str, product_id: str, window_start: datetime) -> Optional[float]:
    """Sum of real, KNOWN costs (cost_amount IS NOT NULL) across every
    mapping this product has to any competitor, in the window - a
    competitor's own individual mapping is an implementation detail here,
    the product is the real unit this gate protects. None (not 0) when
    zero ledger rows with a known cost exist yet - "no real cost data" and
    "confirmed zero cost" are different states, same distinction
    price_competitiveness.py/inventory_recommendations.py already apply."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT SUM(scl.cost_amount), COUNT(*) FILTER (WHERE scl.cost_amount IS NOT NULL)
            FROM scraping_cost_ledger scl
            JOIN competitor_product_mappings cpm
                ON cpm.tenant_id = scl.tenant_id AND cpm.mapping_id = scl.mapping_id
            WHERE scl.tenant_id = %s AND cpm.product_id = %s AND scl.observed_at >= %s;
            """,
            (tenant_id, product_id, window_start),
        )
        total, known_count = cursor.fetchone()
    if known_count == 0:
        return None
    return float(total)


def evaluate_cost_margin_gate(
    conn, tenant_id: str, product_id: str,
    window_days: int = DEFAULT_GATE_WINDOW_DAYS, max_ratio: float = DEFAULT_MAX_COST_TO_MARGIN_RATIO,
    min_product_price: float = DEFAULT_MIN_PRODUCT_PRICE,
) -> CostMarginGateDecision:
    """
    Two checks, in order:

    1. The hard floor: does this product's real basis (margin when a real
       cost_price is on file, else price) clear `min_product_price` at
       all? Below it, this BLOCKS immediately - day one, before a single
       ledger row exists - since fixed team/overhead costs mean no amount
       of real scraping-cost data could ever justify tracking a product
       priced beneath the floor; there's no ratio pattern worth waiting
       for. This is the only branch that can block without first checking
       real cost data.

    2. The dynamic ratio (unchanged from before this floor existed): has
       real, known scraping cost for this product in the trailing
       `window_days` crossed `max_ratio` of that same basis?

    Both checks ALLOW (never block) when there isn't enough real
    information to judge at all - no product record, or a product with no
    positive price/margin on file whatsoever - "insufficient data" is
    never treated as "over budget", the same discipline this codebase
    applies everywhere else a real number might simply not exist yet. That
    is different from the floor case above: a real, known basis that is
    simply too low is a confirmed fact, not missing data, so it blocks.

    basis_kind="margin" (current_price - cost_price) is used whenever a
    real, positive cost_price is on file - the true profit at stake, not
    just revenue. Falls back to basis_kind="price" (current_price alone)
    when cost_price is unset, which real product records frequently are
    (see inventory_recommendations.py's own note on this) - a real but
    less precise basis, always labeled as such rather than silently
    presented as a margin figure it isn't.
    """
    row = _load_product_pricing(conn, tenant_id, product_id)
    if row is None:
        return CostMarginGateDecision(
            allow=True, reason="no real product record found - nothing to gate",
            cumulative_cost=None, basis_amount=None, basis_kind=None, ratio=None,
            threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
        )
    current_price, cost_price = row
    current_price = float(current_price)

    basis_amount: Optional[float] = None
    basis_kind: Optional[str] = None
    if cost_price is not None and float(cost_price) < current_price:
        basis_amount = current_price - float(cost_price)
        basis_kind = "margin"
    elif current_price > 0:
        basis_amount = current_price
        basis_kind = "price"

    if basis_amount is None:
        return CostMarginGateDecision(
            allow=True, reason="no positive margin or price on file to weigh cost against",
            cumulative_cost=None, basis_amount=None, basis_kind=None, ratio=None,
            threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
        )

    if basis_amount < min_product_price:
        reason = (
            f"this product's real {basis_kind} ({basis_amount:.4f}) is below the "
            f"{min_product_price:.2f} minimum price floor - blocked on day one, before any "
            f"scraping cost has even been recorded"
        )
        return CostMarginGateDecision(
            allow=False, reason=reason,
            cumulative_cost=None, basis_amount=basis_amount, basis_kind=basis_kind, ratio=None,
            threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
        )

    window_start = datetime.now(timezone.utc) - timedelta(days=window_days)
    cumulative_cost = _load_cumulative_known_cost(conn, tenant_id, product_id, window_start)
    if cumulative_cost is None:
        return CostMarginGateDecision(
            allow=True, reason="no real scraping cost data recorded yet for this product",
            cumulative_cost=None, basis_amount=basis_amount, basis_kind=basis_kind, ratio=None,
            threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
        )

    ratio = round(cumulative_cost / basis_amount, 4)
    if ratio >= max_ratio:
        reason = (
            f"real scraping cost ({cumulative_cost:.4f}) is {ratio:.0%} of this product's "
            f"{basis_kind} ({basis_amount:.4f}) over the last {window_days} days - at or above "
            f"the {max_ratio:.0%} limit"
        )
        return CostMarginGateDecision(
            allow=False, reason=reason,
            cumulative_cost=cumulative_cost, basis_amount=basis_amount, basis_kind=basis_kind, ratio=ratio,
            threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
        )

    reason = (
        f"real scraping cost ({cumulative_cost:.4f}) is {ratio:.0%} of this product's "
        f"{basis_kind} ({basis_amount:.4f}) over the last {window_days} days - under the "
        f"{max_ratio:.0%} limit"
    )
    return CostMarginGateDecision(
        allow=True, reason=reason,
        cumulative_cost=cumulative_cost, basis_amount=basis_amount, basis_kind=basis_kind, ratio=ratio,
        threshold=max_ratio, window_days=window_days, min_product_price=min_product_price,
    )
