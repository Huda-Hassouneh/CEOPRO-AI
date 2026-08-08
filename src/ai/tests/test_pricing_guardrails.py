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


def test_margin_guardrail_leaves_price_alone_when_above_floor():
    result = apply_margin_guardrail(cost=10.0, suggested_price=20.0, min_margin_pct=0.10)
    assert result.clamped is False
    assert result.suggested_price == 20.0


def test_margin_guardrail_raises_price_when_below_floor():
    result = apply_margin_guardrail(cost=10.0, suggested_price=10.5, min_margin_pct=0.10)
    assert result.clamped is True
    assert result.price_floor == 11.0
    assert result.suggested_price == 11.0


def test_margin_guardrail_never_lowers_a_price():
    """A floor-raise only - a price already well above cost must never be pulled down toward it."""
    result = apply_margin_guardrail(cost=5.0, suggested_price=100.0, min_margin_pct=0.10)
    assert result.clamped is False
    assert result.suggested_price == 100.0


def test_margin_guardrail_default_min_margin_pct_is_used_when_not_specified():
    result = apply_margin_guardrail(cost=10.0, suggested_price=10.5)
    assert result.min_margin_pct > 0
