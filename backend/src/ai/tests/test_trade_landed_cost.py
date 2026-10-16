"""Landed cost (trade/landed_cost.py). Every expected figure below was worked
out by hand from the formulas in the module docstring; the inputs are test
fixtures, not market data."""
from decimal import Decimal as D

from src.ai.trade import landed_cost as lc
from src.ai.trade import messages


def _inputs(**overrides):
    base = {
        "supplier_unit_price": lc.Input(D("100"), lc.USER, "TRY", "E1"),
        "quantity": lc.Input(D("1000"), lc.USER, "units", "E1"),
        "fx_rate": lc.Input(D("0.0215"), lc.USER, "rate", "E1"),
        "freight": lc.Input(D("300"), lc.USER, "JOD", "E1"),
        "insurance": lc.Input(D("20"), lc.USER, "JOD", "E1"),
        "duty_rate": lc.Input(D("20"), lc.EVIDENCE, "percent", "E2"),
        "sales_tax_rate": lc.Input(D("16"), lc.EVIDENCE, "percent", "E3"),
        "clearance": lc.Input(D("150"), lc.USER, "JOD", "E1"),
        "local_unit_price": lc.Input(D("4.5"), lc.USER, "JOD", "E1"),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def _value(result, key):
    return result.step(key).value


def test_cif_landed_cost_with_duty_and_tax():
    result = lc.calculate(_inputs(), "JOD")
    assert result.complete and result.missing == []
    # goods 100 × 1000 = 100,000 TRY × 0.0215 = 2,150 JOD
    assert _value(result, "goods_value") == D("100000")
    assert _value(result, "goods_value_converted") == D("2150")
    # customs value (CIF) 2150 + 300 + 20 = 2470; duty 20% = 494
    assert _value(result, "customs_value") == D("2470")
    assert _value(result, "duty") == D("494")
    # tax base 2470 + 494 = 2964; tax 16% = 474.24
    assert _value(result, "tax_base") == D("2964")
    assert _value(result, "sales_tax") == D("474.24")
    # total 2150 + 300 + 20 + 494 + 474.24 + 150 = 3588.24; per unit 3.58824
    assert _value(result, "landed_total") == D("3588.24")
    assert _value(result, "landed_per_unit") == D("3.58824")
    assert _value(result, "landed_per_unit_excluding_tax") == D("3.114")


def test_comparison_with_the_local_price_and_break_even():
    comparison = lc.calculate(_inputs(), "JOD").comparison
    # local 4.5 × 1000 = 4500; saving 4500 − 3588.24 = 911.76 (20.3%)
    assert comparison["local_total"] == "4500" and comparison["saving_total"] == "911.760"
    assert comparison["saving_pct"] == "20.3" and comparison["cheaper"] == "import"
    # fixed 150 (clearance); variable per unit (3588.24 − 150) / 1000 = 3.43824
    # break-even 150 / (4.5 − 3.43824) = 141.27 → 142 units
    assert comparison["break_even_quantity"] == "142"


def test_no_break_even_when_importing_costs_more_per_unit():
    comparison = lc.calculate(_inputs(local_unit_price=lc.Input(D("3"), lc.USER, "JOD")), "JOD").comparison
    assert comparison["cheaper"] == "local"
    assert comparison["break_even_quantity"] is None and "no order size" in comparison["break_even_note"]


def test_a_fob_customs_basis_leaves_freight_out_of_the_duty_base():
    result = lc.calculate(_inputs(), "JOD", valuation_basis=lc.Input(D("1"), lc.EVIDENCE, "FOB", "E4"))
    assert _value(result, "customs_value") == D("2150")
    assert _value(result, "duty") == D("430")           # 2150 × 20%
    assert _value(result, "landed_total") == D("3462.8")  # 2150 + 300 + 20 + 430 + (2580 × 16% = 412.8) + 150
    assert not any("CIF basis" in a for a in result.assumptions)


def test_cif_incoterm_means_freight_and_insurance_are_already_in_the_price():
    result = lc.calculate(_inputs(), "JOD", incoterm="CIF")
    assert result.step("freight") is None and result.step("insurance") is None
    assert _value(result, "customs_value") == D("2150")
    assert any("included in the supplier's price under CIF" in a for a in result.assumptions)


def test_ddp_means_the_seller_pays_duty_and_tax():
    result = lc.calculate(_inputs(duty_rate=None, sales_tax_rate=None), "JOD", incoterm="DDP")
    assert result.complete
    assert result.step("duty") is None and result.step("sales_tax") is None
    assert _value(result, "landed_total") == D("2300")  # 2150 + 150 clearance


def test_missing_inputs_are_listed_and_nothing_is_guessed():
    result = lc.calculate(_inputs(duty_rate=None, freight=None), "JOD")
    assert not result.complete
    assert {m["key"] for m in result.missing} == {"duty_rate", "freight"}
    assert result.step("landed_total") is None and result.comparison is None


def test_a_foreign_price_without_an_exchange_rate_is_not_converted():
    result = lc.calculate(_inputs(fx_rate=None), "JOD")
    assert [m["key"] for m in result.missing] == ["fx_rate"]
    assert "TRY to JOD" in result.missing[0]["why"]
    assert result.step("goods_value_converted") is None


def test_no_supplier_price_or_quantity_stops_at_the_start():
    result = lc.calculate({"quantity": lc.Input(D("10"), lc.USER, "units")}, "JOD")
    assert result.missing == [{"key": "supplier_unit_price", "why": result.missing[0]["why"]}]
    assert result.steps == []


def test_margin_at_the_selling_price():
    result = lc.calculate(_inputs(selling_price=lc.Input(D("6"), lc.COMPANY, "JOD", "E5")), "JOD")
    assert _value(result, "margin_per_unit") == D("2.41176")      # 6 − 3.58824
    assert round(_value(result, "margin_pct"), 2) == D("40.20")   # 2.41176 / 6 × 100


def test_specific_duty_and_excise():
    result = lc.calculate(_inputs(specific_duty_per_unit=lc.Input(D("0.1"), lc.EVIDENCE, "JOD", "E2"),
                                  excise_rate=lc.Input(D("10"), lc.EVIDENCE, "percent", "E2")), "JOD")
    assert _value(result, "specific_duty") == D("100")         # 0.1 × 1000
    assert _value(result, "excise") == D("306.4")              # (2470 + 494 + 100) × 10%
    assert _value(result, "tax_base") == D("3370.4")           # 2470 + 594 + 306.4


def test_sensitivity_varies_only_the_inputs_given():
    rows = {row["label"]: row for row in lc.sensitivity(_inputs(), "JOD")}
    # fx +5%: goods 2257.5, customs 2577.5, duty 515.5, tax 3093 × 16% = 494.88
    # → total 2257.5 + 300 + 20 + 515.5 + 494.88 + 150 = 3737.88 → 3.738 per unit
    assert rows["Exchange rate 5% less favourable"]["landed_per_unit"] == "3.738"
    assert set(rows) == {"Exchange rate 5% less favourable", "Exchange rate 5% more favourable", "Freight 25% higher",
                         "Freight 25% lower", "Half the quantity", "Double the quantity"}
    assert lc.sensitivity(_inputs(duty_rate=None), "JOD") == []


def test_every_input_and_step_records_where_it_came_from():
    result = lc.calculate(_inputs(), "JOD")
    as_dict = result.as_dict()
    assert as_dict["inputs"]["duty_rate"] == {"value": "20", "unit": "percent", "source": "evidence",
                                              "evidence_id": "E2", "note": ""}
    duty = next(s for s in as_dict["steps"] if s["key"] == "duty")
    assert duty["formula"] == "customs value × duty rate" and duty["inputs"] == ["customs_value", "duty_rate"]


def test_the_calculation_reads_in_arabic():
    localized = messages.localize(lc.calculate(_inputs(duty_rate=None), "JOD").as_dict(), "ar")
    labels = {s["key"]: s["label"] for s in localized["steps"]}
    assert labels["goods_value"] == "قيمة البضاعة" and labels["goods_value_converted"] == "قيمة البضاعة بـ JOD"
    assert localized["missing"][0]["why"].startswith("نسبة الرسوم الجمركية")
    assert all(not a.startswith("No delivery term") for a in localized["assumptions"])
    assert messages.localize({"steps": []}, "en") == {"steps": []}
