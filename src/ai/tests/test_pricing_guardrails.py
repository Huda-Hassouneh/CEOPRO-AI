from src.ai.pricing.guardrails import apply_margin_guardrail, apply_price_change_guardrail


def test_suggestion_within_bounds_is_not_clamped():
    result = apply_price_change_guardrail(current_price=100.0, raw_suggested_price=105.0, max_change_pct=0.15)
    assert result.suggested_price == 105.0
    assert result.clamped is False


def test_suggestion_above_upper_bound_is_clamped():
    result = apply_price_change_guardrail(current_price=100.0, raw_suggested_price=150.0, max_change_pct=0.15)
    assert result.suggested_price == 115.0
    assert result.clamped is True


def test_suggestion_below_lower_bound_is_clamped():
    result = apply_price_change_guardrail(current_price=100.0, raw_suggested_price=50.0, max_change_pct=0.15)
    assert result.suggested_price == 85.0
    assert result.clamped is True


def test_suggestion_equal_to_current_price_is_never_clamped():
    result = apply_price_change_guardrail(current_price=100.0, raw_suggested_price=100.0, max_change_pct=0.15)
    assert result.suggested_price == 100.0
    assert result.clamped is False


def test_custom_max_change_pct_is_respected():
    result = apply_price_change_guardrail(current_price=100.0, raw_suggested_price=110.0, max_change_pct=0.05)
    assert result.suggested_price == 105.0
    assert result.clamped is True


def test_margin_guardrail_returns_none_when_cost_unknown():
    assert apply_margin_guardrail(cost=None, suggested_price=50.0) is None


def test_margin_guardrail_no_op_when_already_above_floor():
    result = apply_margin_guardrail(cost=10.0, suggested_price=50.0, min_margin_pct=0.10)
    assert result.clamped is False
    assert result.suggested_price == 50.0
    assert result.floor_price == 11.0


def test_margin_guardrail_raises_price_below_floor():
    result = apply_margin_guardrail(cost=15.0, suggested_price=14.45, min_margin_pct=0.10)
    assert result.clamped is True
    assert result.suggested_price == 16.5
    assert result.floor_price == 16.5


def test_margin_guardrail_never_lowers_a_price():
    """A suggestion already well above the margin floor must pass through unchanged, never pulled down toward it."""
    result = apply_margin_guardrail(cost=10.0, suggested_price=200.0, min_margin_pct=0.10)
    assert result.suggested_price == 200.0
    assert result.clamped is False


def test_margin_guardrail_uses_default_min_margin_when_not_specified():
    result = apply_margin_guardrail(cost=100.0, suggested_price=105.0)
    assert result.min_margin_pct > 0
    assert result.floor_price == round(100.0 * (1 + result.min_margin_pct), 2)
