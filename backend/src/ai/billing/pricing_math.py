"""Shared Decimal financial primitives; callers own commercial policy."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def money(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def round_up(value, increment):
    if increment <= 0:
        return money(value)
    return money((value / increment).to_integral_value(rounding=ROUND_CEILING) * increment)


def price_for_margin(cost, margin, processing=Decimal('0'), fixed=Decimal('0')):
    denominator = Decimal('1') - margin - processing
    if denominator <= 0:
        raise ValueError('Margin plus payment processing must be below one')
    return (cost + fixed) / denominator


def usage_cost(units, unit_cost, operational, reserve):
    return units * unit_cost * operational * reserve
