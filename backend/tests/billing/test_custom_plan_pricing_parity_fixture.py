import json
from pathlib import Path

from src.ai.billing.custom_plan_pricing import calculate_custom_plan_price


def test_original_node_pricing_reference_fixture_expected_outputs():
    fixture = json.loads(Path(__file__).with_name("custom_plan_pricing_parity.json").read_text(encoding="utf-8"))
    result = calculate_custom_plan_price(fixture["input"])
    actual = {key: str(result[key]) for key in fixture["expected"]}
    assert actual == fixture["expected"]
