"""
Landed cost of an import, compared with buying the same goods locally.

Deterministic and exact (Decimal arithmetic, no model involved). Every
input carries where it came from - the user, a cited source, the
company's own records, or an explicit assumption - and every step of the
result records its formula and the inputs it used, so each figure in an
answer can be traced back to its sources.

The calculation follows the transaction as described:

  goods value            = unit price x quantity                (supplier currency)
  in destination currency = goods value x exchange rate
  freight, insurance      = added only when the Incoterm does not already include them
  customs value           = goods + freight + insurance  (CIF basis)
                          = goods                        (FOB basis)
  duty                    = customs value x duty rate  (+ any specific duty per unit)
  sales tax / VAT base    = customs value + duty (+ excise)
  sales tax / VAT         = tax base x tax rate
  landed cost             = goods + freight + insurance + duty + excise + tax + other costs
  per unit                = landed cost / quantity

Nothing is defaulted silently. An input the calculation needs but does
not have is reported as missing (with what would establish it), and the
steps that depend on it are not computed. The customs valuation basis and
the tax base differ by country: when no cited source states them, the
result says which basis it used and that it is an assumption to confirm.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, List, Optional

USER = "user"
EVIDENCE = "evidence"
COMPANY = "company"
ASSUMPTION = "assumption"

# What the seller's price already covers under each Incoterms 2020 rule
# (the buyer pays everything else).
INCOTERM_INCLUDES = {
    "EXW": (), "FCA": (), "FAS": (), "FOB": (),
    "CFR": ("freight",), "CPT": ("freight",),
    "CIF": ("freight", "insurance"), "CIP": ("freight", "insurance"),
    "DAP": ("freight", "insurance"), "DPU": ("freight", "insurance"),
    "DDP": ("freight", "insurance", "duty", "tax"),
}

MONEY_COST_KEYS = ("brokerage", "clearance", "port_handling", "inspection", "testing", "certification", "permits",
                   "documentation", "bank_fees", "warehousing", "local_delivery", "other")
FIXED_COST_KEYS = ("brokerage", "clearance", "inspection", "testing", "certification", "permits", "documentation",
                   "bank_fees")


@dataclass
class Input:
    value: Decimal
    source: str
    unit: str = ""                  # currency code, "percent", "units" or "rate"
    evidence_id: Optional[str] = None
    note: str = ""

    def as_dict(self) -> dict:
        return {"value": _text(self.value), "unit": self.unit, "source": self.source,
                "evidence_id": self.evidence_id, "note": self.note}


@dataclass
class Step:
    key: str
    label: str
    formula: str
    value: Decimal
    unit: str
    inputs: List[str]

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "formula": self.formula, "value": _text(self.value),
                "unit": self.unit, "inputs": self.inputs}


@dataclass
class Result:
    steps: List[Step] = field(default_factory=list)
    inputs: Dict[str, Input] = field(default_factory=dict)
    missing: List[dict] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    exclusions: List[str] = field(default_factory=list)
    comparison: Optional[dict] = None
    sensitivity: List[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and any(step.key == "landed_per_unit" for step in self.steps)

    def step(self, key: str) -> Optional[Step]:
        return next((step for step in self.steps if step.key == key), None)

    def as_dict(self) -> dict:
        return {"complete": self.complete, "steps": [s.as_dict() for s in self.steps],
                "inputs": {k: v.as_dict() for k, v in self.inputs.items()}, "missing": self.missing,
                "assumptions": self.assumptions, "exclusions": self.exclusions, "comparison": self.comparison,
                "sensitivity": self.sensitivity}


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral() else format(value, "f")


def money(value: Decimal) -> Decimal:
    """Money shown to two decimals (three for dinar currencies is applied by the caller's formatting)."""
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def to_decimal(value) -> Optional[Decimal]:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _missing(result: Result, key: str, why: str) -> None:
    if not any(item["key"] == key for item in result.missing):
        result.missing.append({"key": key, "why": why})


def calculate(inputs: Dict[str, Input], destination_currency: str, incoterm: Optional[str] = None,
              valuation_basis: Optional[Input] = None, tax_base_includes_duty: Optional[Input] = None) -> Result:
    """
    inputs keys (all optional; missing ones are reported):
      supplier_unit_price (supplier currency), quantity (units), fx_rate (destination per 1 supplier currency),
      freight, insurance (any currency with an fx rate, or destination currency),
      duty_rate (percent), specific_duty_per_unit (destination currency), excise_rate (percent),
      sales_tax_rate (percent), local_unit_price (destination currency), selling_price (destination currency),
      and other costs (MONEY_COST_KEYS) in the destination currency.
    """
    result = Result(inputs=dict(inputs))
    incoterm = (incoterm or "").upper() or None
    included = INCOTERM_INCLUDES.get(incoterm, ())
    if incoterm is None:
        result.assumptions.append("No delivery term (Incoterm) was given: the supplier price is treated as "
                                  "covering the goods only (like EXW/FOB), so freight and insurance are added.")

    price, quantity = inputs.get("supplier_unit_price"), inputs.get("quantity")
    if price is None:
        _missing(result, "supplier_unit_price", "the supplier's price per unit (a written quotation is best)")
    if quantity is None:
        _missing(result, "quantity", "how many units the order is for")
    if price is None or quantity is None:
        return result
    if quantity.value <= 0:
        _missing(result, "quantity", "the order quantity must be more than zero")
        return result

    supplier_currency = price.unit or destination_currency
    goods = price.value * quantity.value
    result.steps.append(Step("goods_value", "Goods value", "unit price × quantity", goods, supplier_currency,
                             ["supplier_unit_price", "quantity"]))

    def to_destination(key: str, item: Input) -> Optional[Decimal]:
        currency = item.unit or destination_currency
        if currency == destination_currency:
            return item.value
        rate = inputs.get("fx_rate")
        if rate is None or currency != supplier_currency:
            _missing(result, "fx_rate", f"the exchange rate from {currency} to {destination_currency} on the payment date")
            return None
        return item.value * rate.value

    goods_dest = to_destination("supplier_unit_price", price)
    if goods_dest is None:
        return result
    goods_dest *= quantity.value
    if supplier_currency != destination_currency:
        result.steps.append(Step("goods_value_converted", f"Goods value in {destination_currency}",
                                 "goods value × exchange rate", goods_dest, destination_currency,
                                 ["goods_value", "fx_rate"]))

    def cost(key: str, label: str, explain: str) -> Decimal:
        if key in included:
            result.assumptions.append(f"{label} is included in the supplier's price under {incoterm}.")
            return Decimal("0")
        item = inputs.get(key)
        if item is None:
            _missing(result, key, explain)
            return Decimal("0")
        converted = to_destination(key, item)
        if converted is None:
            return Decimal("0")
        result.steps.append(Step(key, label, f"{label.lower()} for the shipment", converted, destination_currency, [key]))
        return converted

    freight = cost("freight", "Freight", "the freight cost for this shipment (a forwarder's quotation)")
    insurance = cost("insurance", "Insurance", "the cargo insurance cost (often a small % of the goods value)")

    # valuation_basis.unit is "CIF" or "FOB", as stated by its cited source.
    basis_code = "FOB" if valuation_basis is not None and (valuation_basis.unit or "").upper() == "FOB" else "CIF"
    if valuation_basis is None:
        result.assumptions.append("Customs value is taken on a CIF basis (goods + freight + insurance), the basis "
                                  "most Arab and WTO customs administrations use; confirm it for the destination.")
    customs_value = goods_dest + (freight + insurance if basis_code == "CIF" else Decimal("0"))
    result.steps.append(Step("customs_value", f"Customs value ({basis_code} basis)",
                             "goods + freight + insurance" if basis_code == "CIF" else "goods value",
                             customs_value, destination_currency,
                             ["goods_value_converted" if supplier_currency != destination_currency else "goods_value",
                              "freight", "insurance"] if basis_code == "CIF" else ["goods_value"]))

    duty = Decimal("0")
    if "duty" in included:
        result.assumptions.append(f"Import duty is paid by the seller under {incoterm}.")
    elif inputs.get("duty_rate") is None:
        _missing(result, "duty_rate", "the customs duty rate for the product's HS code, origin and destination")
    else:
        duty = customs_value * inputs["duty_rate"].value / Decimal(100)
        result.steps.append(Step("duty", "Customs duty", "customs value × duty rate", duty, destination_currency,
                                 ["customs_value", "duty_rate"]))
    if inputs.get("specific_duty_per_unit") is not None and "duty" not in included:
        specific = inputs["specific_duty_per_unit"].value * quantity.value
        duty += specific
        result.steps.append(Step("specific_duty", "Specific duty", "duty per unit × quantity", specific,
                                 destination_currency, ["specific_duty_per_unit", "quantity"]))

    excise = Decimal("0")
    if inputs.get("excise_rate") is not None:
        excise = (customs_value + duty) * inputs["excise_rate"].value / Decimal(100)
        result.steps.append(Step("excise", "Excise tax", "(customs value + duty) × excise rate", excise,
                                 destination_currency, ["customs_value", "duty", "excise_rate"]))

    tax = Decimal("0")
    if "tax" in included:
        result.assumptions.append(f"Import sales tax / VAT is paid by the seller under {incoterm}.")
    elif inputs.get("sales_tax_rate") is None:
        _missing(result, "sales_tax_rate", "the import sales tax / VAT rate for this product in the destination")
    else:
        includes_duty = tax_base_includes_duty is None or tax_base_includes_duty.value != 0
        if tax_base_includes_duty is None:
            result.assumptions.append("Sales tax / VAT is charged on the customs value plus duty and excise, the "
                                      "usual import base; confirm it for the destination.")
        base = customs_value + (duty + excise if includes_duty else Decimal("0"))
        result.steps.append(Step("tax_base", "Sales tax / VAT base",
                                 "customs value + duty + excise" if includes_duty else "customs value",
                                 base, destination_currency, ["customs_value", "duty", "excise"]))
        tax = base * inputs["sales_tax_rate"].value / Decimal(100)
        result.steps.append(Step("sales_tax", "Import sales tax / VAT", "tax base × tax rate", tax,
                                 destination_currency, ["tax_base", "sales_tax_rate"]))

    other_total, fixed_total = Decimal("0"), Decimal("0")
    for key in MONEY_COST_KEYS:
        item = inputs.get(key)
        if item is None:
            continue
        converted = to_destination(key, item)
        if converted is None:
            continue
        other_total += converted
        if key in FIXED_COST_KEYS:
            fixed_total += converted
        result.steps.append(Step(key, key.replace("_", " ").capitalize(), "as stated", converted,
                                 destination_currency, [key]))
    if not any(inputs.get(key) is not None for key in MONEY_COST_KEYS):
        result.exclusions.append("Clearance, brokerage, inspection, certification, permits, port handling, storage "
                                 "and local delivery were not provided, so they are not included.")

    if result.missing:
        return result

    total = goods_dest + freight + insurance + duty + excise + tax + other_total
    result.steps.append(Step("landed_total", "Landed cost (total)",
                             "goods + freight + insurance + duty + excise + tax + other costs", total,
                             destination_currency, [s.key for s in result.steps if s.unit == destination_currency
                                                    and s.key not in ("customs_value", "tax_base")]))
    per_unit = total / quantity.value
    result.steps.append(Step("landed_per_unit", "Landed cost per unit", "landed cost ÷ quantity", per_unit,
                             destination_currency, ["landed_total", "quantity"]))
    if tax:
        result.steps.append(Step("landed_per_unit_excluding_tax", "Landed cost per unit before recoverable VAT",
                                 "(landed cost − import VAT) ÷ quantity", (total - tax) / quantity.value,
                                 destination_currency, ["landed_total", "sales_tax", "quantity"]))
        result.assumptions.append("If the business is VAT/sales-tax registered and can reclaim import VAT, the "
                                  "per-unit cost before recoverable VAT is the relevant one.")

    local = inputs.get("local_unit_price")
    if local is not None:
        local_value = to_destination("local_unit_price", local)
        if local_value is not None:
            local_total = local_value * quantity.value
            saving = local_total - total
            variable_per_unit = (total - fixed_total) / quantity.value
            comparison = {
                "local_unit_price": _text(money(local_value)), "local_total": _text(money(local_total)),
                "landed_total": _text(money(total)), "landed_per_unit": _text(money(per_unit)),
                "saving_total": _text(money(saving)), "saving_per_unit": _text(money(local_value - per_unit)),
                "saving_pct": _text((saving / local_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
                if local_total else None,
                "cheaper": "import" if saving > 0 else ("local" if saving < 0 else "equal"),
                "currency": destination_currency,
            }
            if fixed_total and local_value > variable_per_unit:
                breakeven = (fixed_total / (local_value - variable_per_unit)).to_integral_value(rounding="ROUND_CEILING")
                comparison["break_even_quantity"] = _text(breakeven)
                comparison["break_even_note"] = ("counts clearance, brokerage, inspection, certification, permits, "
                                                 "documentation and bank fees as fixed per shipment; freight, "
                                                 "insurance, duty and tax as changing with the quantity")
            elif local_value <= variable_per_unit:
                comparison["break_even_quantity"] = None
                comparison["break_even_note"] = ("importing costs more per unit than buying locally before any fixed "
                                                 "costs, so no order size makes it cheaper at these rates")
            result.comparison = comparison
            result.steps.append(Step("saving_total", "Saving versus local purchase (total)",
                                     "local price × quantity − landed cost", saving, destination_currency,
                                     ["local_unit_price", "quantity", "landed_total"]))
    selling = inputs.get("selling_price")
    if selling is not None:
        margin = selling.value - per_unit
        result.steps.append(Step("margin_per_unit", "Margin per unit at your selling price",
                                 "selling price − landed cost per unit", margin, destination_currency,
                                 ["selling_price", "landed_per_unit"]))
        if selling.value:
            result.steps.append(Step("margin_pct", "Margin", "margin per unit ÷ selling price × 100",
                                     margin / selling.value * 100, "percent", ["margin_per_unit", "selling_price"]))
    return result


def sensitivity(inputs: Dict[str, Input], destination_currency: str, incoterm: Optional[str] = None,
                valuation_basis: Optional[Input] = None, tax_base_includes_duty: Optional[Input] = None) -> List[dict]:
    """How the per-unit landed cost (and saving) moves when an uncertain
    input changes: exchange rate ±5%, freight ±25%, quantity halved or
    doubled. Only inputs actually present are varied."""
    base = calculate(inputs, destination_currency, incoterm, valuation_basis, tax_base_includes_duty)
    if not base.complete:
        return []
    scenarios = []

    def scenario(label: str, key: str, factor: Decimal) -> None:
        if inputs.get(key) is None:
            return
        changed = dict(inputs)
        original = inputs[key]
        changed[key] = Input(original.value * factor, original.source, original.unit, original.evidence_id,
                             f"{original.note} (scenario)".strip())
        outcome = calculate(changed, destination_currency, incoterm, valuation_basis, tax_base_includes_duty)
        if not outcome.complete:
            return
        scenarios.append({
            "label": label, "input": key, "factor": _text(factor),
            "landed_per_unit": _text(money(outcome.step("landed_per_unit").value)),
            "saving_total": outcome.comparison["saving_total"] if outcome.comparison else None,
        })

    if (inputs.get("supplier_unit_price") and (inputs["supplier_unit_price"].unit or destination_currency)
            != destination_currency):
        scenario("Exchange rate 5% less favourable", "fx_rate", Decimal("1.05"))
        scenario("Exchange rate 5% more favourable", "fx_rate", Decimal("0.95"))
    scenario("Freight 25% higher", "freight", Decimal("1.25"))
    scenario("Freight 25% lower", "freight", Decimal("0.75"))
    scenario("Half the quantity", "quantity", Decimal("0.5"))
    scenario("Double the quantity", "quantity", Decimal("2"))
    return scenarios
