"""
CEOPRO AI - Event-Timing Causal-Chain Detection.

The vision's own example: "Sales increasing -> Competitor launches
cheaper product -> Sales begin declining -> Negative reviews increase ->
System identifies a possible relationship -> Business owner receives an
insight", with an explicit requirement to "distinguish between confirmed
relationships, strong evidence, possible relationships, speculation" and
to "never present correlation as definite causation without sufficient
evidence."

cross_signal.py's engine (built earlier) correlates CURRENT-SNAPSHOT
signals - is the price high right now, is sentiment negative right now,
are sales falling right now. That answers "what's going on today" but
not the vision's specific example, which is about EVENT TIMING: a real
price-drop event at a real point in time, followed by a real change in
the tenant's own sales starting at or after that same point in time.
This module is that second, genuinely different kind of detection - pure
logic, no I/O (mirrors cross_signal.py's own separation from
insights/pipeline.py, which does the real querying).

Confidence is deliberately binary (STRONG vs. POSSIBLE), never a bare
"speculation" tier: this codebase's established honesty principle
(cold_start.py, UNKNOWN evidence records, pricing's own confidence
gating) is to say nothing rather than manufacture a low-value guess -
speculation-tier findings are simply not surfaced as insights at all,
the same way a signal with zero real data is treated as "not available"
rather than "the answer is probably no".
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from src.ai.insights.cross_signal import Insight

# A price move below this is ordinary noise (currency rounding, a minor
# markdown), not a real pricing event worth correlating against.
PRICE_DROP_THRESHOLD_PCT = 10.0

# How many days on each side of a price-drop event to compare the
# tenant's own sales pace - long enough to smooth out day-to-day noise,
# short enough that the comparison is still plausibly about THIS event
# rather than some unrelated later development.
COMPARISON_WINDOW_DAYS = 14

# A sales change below this after a price-drop event isn't a strong
# enough signal to call even "possible" - matches cross_signal.py's own
# SALES_TREND_THRESHOLD_PCT default, kept as a separate constant since
# the two modules could reasonably be tuned independently.
POSSIBLE_SALES_DECLINE_THRESHOLD_PCT = 15.0

# The higher bar for STRONG (not just POSSIBLE) evidence: both signals
# have to be genuinely large, not just past the "possible" floor.
STRONG_PRICE_DROP_THRESHOLD_PCT = 20.0
STRONG_SALES_DECLINE_THRESHOLD_PCT = 30.0


@dataclass
class PriceDropEvent:
    event_date: date
    price_before: float
    price_after: float
    drop_pct: float


def detect_price_drop_events(
    price_history: List["tuple[date, float]"], threshold_pct: float = PRICE_DROP_THRESHOLD_PCT,
) -> List[PriceDropEvent]:
    """
    price_history: (observed_date, price) pairs for ONE competitor/
    product pairing, already sorted ascending by date (insights/
    pipeline.py's job to sort - this stays pure and order-dependent by
    contract, not by re-sorting defensively every call). Returns one
    event per consecutive pair that drops by at least threshold_pct -
    a genuinely real, dated event, never an average or a guess.
    """
    events = []
    for (_, price_before), (date_after, price_after) in zip(price_history, price_history[1:]):
        if price_before <= 0:
            continue
        drop_pct = (price_before - price_after) / price_before * 100
        if drop_pct >= threshold_pct:
            events.append(PriceDropEvent(
                event_date=date_after, price_before=price_before, price_after=price_after, drop_pct=drop_pct,
            ))
    return events


def _avg_daily_units(daily_sales: Dict[date, float], start: date, end: date) -> Optional[float]:
    """Average units/day strictly within [start, end) - None (never 0)
    when there's no sales data at all in that window, so the caller can
    tell "confirmed zero sales" apart from "no data to judge from"."""
    total_days = (end - start).days
    if total_days <= 0:
        return None
    in_range = [quantity for day, quantity in daily_sales.items() if start <= day < end]
    if not in_range:
        return None
    return sum(in_range) / total_days


def detect_causal_price_sales_insight(
    product_id: str, product_name: str, competitor_name: str,
    price_events: List[PriceDropEvent], daily_sales: Dict[date, float],
) -> Optional[Insight]:
    """
    Checks each real price-drop event against the tenant's OWN sales
    pace immediately before vs. immediately after that same date -
    genuine event-timing correlation, not just two unrelated numbers
    placed side by side. Returns the single strongest matching event as
    one Insight, or None when no event has a real, timing-consistent
    sales decline following it (a real absence of evidence, not
    withheld for being inconvenient).
    """
    best: Optional["tuple[PriceDropEvent, float]"] = None

    for event in price_events:
        before_avg = _avg_daily_units(
            daily_sales, event.event_date - timedelta(days=COMPARISON_WINDOW_DAYS), event.event_date,
        )
        after_avg = _avg_daily_units(
            daily_sales, event.event_date, event.event_date + timedelta(days=COMPARISON_WINDOW_DAYS),
        )
        if before_avg is None or after_avg is None or before_avg <= 0:
            continue  # not enough real sales history on one side to judge timing at all

        sales_change_pct = (after_avg - before_avg) / before_avg * 100
        if sales_change_pct > -POSSIBLE_SALES_DECLINE_THRESHOLD_PCT:
            continue  # sales didn't meaningfully decline following this event

        if best is None or abs(sales_change_pct) > abs(best[1]):
            best = (event, sales_change_pct)

    if best is None:
        return None

    event, sales_change_pct = best
    is_strong = (
        event.drop_pct >= STRONG_PRICE_DROP_THRESHOLD_PCT
        and abs(sales_change_pct) >= STRONG_SALES_DECLINE_THRESHOLD_PCT
    )

    if is_strong:
        strength_phrase = "This is a strong pattern worth acting on"
        confidence = 0.85
    else:
        strength_phrase = "This could be related, though it's not certain yet"
        confidence = 0.55

    message = (
        f"{competitor_name} lowered their price for something similar to {product_name} by about "
        f"{event.drop_pct:.0f}% around {event.event_date.isoformat()}, and your own sales for {product_name} "
        f"fell by about {abs(sales_change_pct):.0f}% in the two weeks that followed. {strength_phrase} - "
        f"it's worth keeping an eye on this competitor's pricing."
    )
    return Insight(message=message, category="causal_timing", product_id=product_id, confidence=confidence)
