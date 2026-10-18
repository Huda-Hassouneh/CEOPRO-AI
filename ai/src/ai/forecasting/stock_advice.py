"""
One stock rule for every screen (Demand Prediction, the dashboard's restock
list, product pages): will the stock on hand cover the demand forecast for
the next 30 days?

- restock: stock is at or below the reorder level the business set, or it
  will run out before the forecast period ends. Order enough to cover the
  forecast plus the safety stock.
- reduce:  stock covers more than REDUCE_COVER_DAYS of forecast demand, so
  further orders can be reduced or paused.
- monitor: stock covers the forecast period without a large excess.
- none:    stock isn't tracked (services, or no inventory record).

Everything here is arithmetic on the business's own numbers; the reason
fields say exactly which numbers produced the advice.
"""

import math
from typing import Optional

HORIZON_DAYS = 30
REDUCE_COVER_DAYS = 90
# Stock lasting less than half the forecast period is urgent.
HIGH_PRIORITY_COVER_DAYS = 15

RESTOCK = "restock"
REDUCE = "reduce"
MONITOR = "monitor"
NONE = "none"


def advise(
    stock: Optional[float],
    forecast_demand: Optional[float],
    reorder_level: Optional[float] = None,
    safety_stock: Optional[float] = None,
    horizon_days: int = HORIZON_DAYS,
) -> dict:
    """Returns {action, suggested_qty, days_of_cover, priority, reason_code}.

    suggested_qty is always >= 0: units to order for `restock`, excess units
    for `reduce`, 0 otherwise. days_of_cover is None when there is no
    forecast demand to divide by.
    """
    if stock is None:
        return {"action": NONE, "suggested_qty": 0, "days_of_cover": None, "priority": "low", "reason_code": "not_tracked"}

    stock = float(stock)
    demand = max(float(forecast_demand or 0.0), 0.0)
    reorder_level = float(reorder_level) if reorder_level is not None else None
    safety_stock = max(float(safety_stock or 0.0), 0.0)
    daily = demand / horizon_days if horizon_days else 0.0
    days_of_cover = round(stock / daily, 1) if daily > 0 else None

    at_reorder_level = reorder_level is not None and reorder_level > 0 and stock <= reorder_level
    runs_out = demand > 0 and stock < demand

    if at_reorder_level or runs_out:
        target = max(demand + safety_stock, (reorder_level or 0.0) + safety_stock)
        suggested = max(0, math.ceil(target - stock))
        urgent = stock <= 0 or (days_of_cover is not None and days_of_cover < HIGH_PRIORITY_COVER_DAYS)
        return {
            "action": RESTOCK,
            "suggested_qty": suggested,
            "days_of_cover": days_of_cover,
            "priority": "high" if urgent else "medium",
            "reason_code": "runs_out" if runs_out else "at_reorder_level",
        }

    if demand > 0 and days_of_cover is not None and days_of_cover > REDUCE_COVER_DAYS:
        excess = max(0, math.floor(stock - demand * (REDUCE_COVER_DAYS / horizon_days)))
        return {
            "action": REDUCE,
            "suggested_qty": excess,
            "days_of_cover": days_of_cover,
            "priority": "medium" if days_of_cover > 2 * REDUCE_COVER_DAYS else "low",
            "reason_code": "overstocked",
        }

    if demand == 0 and stock > 0:
        return {"action": MONITOR, "suggested_qty": 0, "days_of_cover": None, "priority": "low", "reason_code": "no_demand"}

    return {"action": MONITOR, "suggested_qty": 0, "days_of_cover": days_of_cover, "priority": "low", "reason_code": "covered"}
