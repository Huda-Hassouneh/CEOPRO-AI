"""
Quantities (units sold, stock levels) are NUMERIC(14,4): businesses sell by
weight, length, volume and time, not only by the piece - see migration
20261006010000_fractional_quantities.sql. Every API/LLM-facing value goes
through as_quantity() so a whole number still reads as 5 (never 5.0 or
"5.0000") while 2.5 kg stays 2.5 instead of being truncated by int().
"""
from decimal import Decimal
from typing import Optional, Union

Number = Union[int, float, Decimal]


def as_quantity(value: Optional[Number]) -> Optional[Union[int, float]]:
    if value is None:
        return None
    rounded = round(float(value), 4)
    return int(rounded) if rounded.is_integer() else rounded


def format_quantity(value: Optional[Number]) -> str:
    """For prompt/summary text: '5', '2.5', '12.75'."""
    quantity = as_quantity(value)
    return "0" if quantity is None else f"{quantity:g}" if isinstance(quantity, float) else str(quantity)
