"""
How each plan's Data Credit and AI Credit budget is derived - a planning
model, not a promise of profit (docs/SUBSCRIPTIONS_AND_CREDITS.md).

    net monthly revenue  = (period charge - payment processing fee - refund allowance) / months
    variable cost budget = net monthly revenue x (1 - target contribution margin)
    AI budget (USD)      = variable cost budget x AI share
    Data budget (USD)    = variable cost budget x Data share
    credits              = budget USD / credit USD value   (rounded down)

The remaining share of the variable budget is held back for storage and
processing, report generation and exports, infrastructure allocation, and
estimation error; it is never handed to customers as credits.

Every plan is sized on its LEAST profitable billing option (the six-month
period at 20% off), so the budget is safe whichever period a company picks.
Taxes are collected on top of the price (Stripe prices are tax-exclusive),
so they are not part of revenue. Refunds: KEEL doesn't refund a started
period (cancellation takes effect at period end), so the allowance is 0 by
default and configurable.

The processing fee defaults are a conservative planning assumption (card
rate plus international-card and currency-conversion surcharges) to be
replaced with the rates on KEEL's own Stripe account; they are not a
provider price used for metering.
"""
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Dict, Optional

PLAN_PRICES_USD = {"starter": Decimal("55"), "growth": Decimal("140"), "enterprise": Decimal("350")}


@dataclass(frozen=True)
class CostAssumptions:
    target_contribution_margin: Decimal = Decimal("0.70")
    processing_fee_percent: Decimal = Decimal("5.4")     # 2.9% card + 1.5% international + 1% conversion
    processing_fee_fixed_usd: Decimal = Decimal("0.30")  # per charge
    refund_allowance_percent: Decimal = Decimal("0")
    worst_case_months: int = 6
    worst_case_discount_percent: Decimal = Decimal("20")
    ai_share: Decimal = Decimal("0.35")
    data_share: Decimal = Decimal("0.35")
    credit_usd_value: Decimal = Decimal("0.01")
    trial_fraction: Decimal = Decimal("0.10")             # a trial gets a tenth of a paid month


@dataclass(frozen=True)
class PlanBudget:
    plan_key: str
    monthly_price_usd: Decimal
    period_charge_usd: Decimal
    processing_fee_usd: Decimal
    net_monthly_revenue_usd: Decimal
    variable_cost_budget_usd: Decimal
    ai_budget_usd: Decimal
    data_budget_usd: Decimal
    reserved_budget_usd: Decimal
    ai_credits: int
    data_credits: int
    trial_ai_credits: int
    trial_data_credits: int

    def as_dict(self) -> dict:
        return {key: (str(value) if isinstance(value, Decimal) else value) for key, value in asdict(self).items()}


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _credits(usd: Decimal, credit_usd_value: Decimal) -> int:
    return int((usd / credit_usd_value).to_integral_value(rounding=ROUND_DOWN))


def max_variable_cost(net_revenue_usd: Decimal, target_contribution_margin: Decimal) -> Decimal:
    """The spec's formula: net revenue x (1 - target contribution margin)."""
    if not (Decimal("0") <= target_contribution_margin < Decimal("1")):
        raise ValueError("target_contribution_margin must be in [0, 1)")
    return net_revenue_usd * (Decimal("1") - target_contribution_margin)


def plan_budget(plan_key: str, monthly_price: Decimal, a: Optional[CostAssumptions] = None) -> PlanBudget:
    a = a or CostAssumptions()
    if a.ai_share + a.data_share > Decimal("1"):
        raise ValueError("AI and Data shares can't exceed the whole variable budget")
    months = Decimal(a.worst_case_months)
    charge = monthly_price * months * (Decimal("1") - a.worst_case_discount_percent / Decimal("100"))
    fee = charge * a.processing_fee_percent / Decimal("100") + a.processing_fee_fixed_usd
    refunds = charge * a.refund_allowance_percent / Decimal("100")
    net_monthly = (charge - fee - refunds) / months
    variable = max_variable_cost(net_monthly, a.target_contribution_margin)
    ai_usd, data_usd = variable * a.ai_share, variable * a.data_share
    ai_credits, data_credits = _credits(ai_usd, a.credit_usd_value), _credits(data_usd, a.credit_usd_value)
    return PlanBudget(
        plan_key=plan_key, monthly_price_usd=monthly_price, period_charge_usd=_cents(charge),
        processing_fee_usd=_cents(fee), net_monthly_revenue_usd=_cents(net_monthly),
        variable_cost_budget_usd=_cents(variable), ai_budget_usd=_cents(ai_usd), data_budget_usd=_cents(data_usd),
        reserved_budget_usd=_cents(variable - ai_usd - data_usd),
        ai_credits=ai_credits, data_credits=data_credits,
        trial_ai_credits=int(ai_credits * a.trial_fraction), trial_data_credits=int(data_credits * a.trial_fraction),
    )


def recommended_budgets(a: Optional[CostAssumptions] = None) -> Dict[str, PlanBudget]:
    return {key: plan_budget(key, price, a) for key, price in PLAN_PRICES_USD.items()}
