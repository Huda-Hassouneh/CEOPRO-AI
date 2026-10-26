"""Shared expectations observed from the actual original Node function."""
from pathlib import Path
from decimal import Decimal
import json
import pytest
from src.ai.billing.custom_plan_pricing import calculate_custom_plan_price
FIXTURE=json.loads(Path(__file__).with_name('custom_plan_pricing_runtime_vectors.json').read_text())
@pytest.mark.parametrize('vector',FIXTURE['vectors'],ids=lambda v:v['name'])
def test_original_node_runtime_financial_vector(vector):
    actual=calculate_custom_plan_price(vector['input'])
    for key,value in vector['expected'].items():assert actual[key]==Decimal(value),(key,actual[key],value)
