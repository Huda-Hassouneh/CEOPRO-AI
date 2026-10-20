from unittest.mock import MagicMock, patch

import pytest

from src.ai.pricing import pipeline


@pytest.fixture
def fake_conn():
    return MagicMock()


@pytest.fixture(autouse=True)
def no_cross_currency_matches():
    """
    run_price_recommendation now unconditionally calls
    load_cross_currency_competitor_prices - default it to "nothing found" for
    every test in this file except the ones specifically exercising that
    path, so existing tests don't need to know about it.
    """
    with patch.object(pipeline.data_access, "load_cross_currency_competitor_prices", return_value=[]):
        yield


def _own_product(current_price: float, currency: str = "JOD", cost: float = None) -> dict:
    return {"product_name": "Sunscreen SPF 50", "current_price": current_price, "currency": currency, "cost": cost}


def _competitor_price(entry_id: str, competitor_id: str, price: float, currency: str = "JOD") -> dict:
    return {
        "price_entry_id": entry_id,
        "competitor_id": competitor_id,
        "competitor_name": "Rival Pharmacy",
        "price_found": price,
        "currency": currency,
        "captured_at": None,
    }


def test_missing_product_raises(fake_conn):
    with patch.object(pipeline.data_access, "load_own_product", return_value=None):
        with pytest.raises(ValueError, match="No product found"):
            pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")


def _no_local_data(own, references=None, snapshot=None, comparable=None):
    """Patches for a product with no tracked in-region competitor price."""
    return (
        patch.object(pipeline.data_access, "load_comparable_prices", return_value=comparable or []),
        patch.object(pipeline.data_access, "load_own_product", return_value=own),
        patch.object(pipeline.data_access, "load_competitor_prices", return_value=[]),
        patch.object(pipeline.data_access, "load_reference_competitor_prices", return_value=references or []),
        patch.object(pipeline.data_access, "load_tenant_market_snapshot", return_value=snapshot or []),
    )


def _run_without_local_data(fake_conn, own, references=None, snapshot=None, convert=None, comparable=None):
    patches = list(_no_local_data(own, references, snapshot, comparable))
    if convert is not None:
        patches.append(patch.object(pipeline.estimation, "convert_amount", side_effect=convert))
    evidence_patch = patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1")
    outcome_patch = patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1")
    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        mock_evidence = stack.enter_context(evidence_patch)
        stack.enter_context(outcome_patch)
        return pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1"), mock_evidence


def test_no_data_anywhere_still_returns_a_decision_never_unknown(fake_conn):
    result, mock_evidence = _run_without_local_data(fake_conn, _own_product(20.0))  # no cost either

    assert result["status"] == "OK"
    assert result["action"] == "hold"
    assert result["data_basis"] == "INTERNAL_ONLY"
    assert result["market"] is None  # there is no market figure to show
    assert mock_evidence.call_args.args[2] == "RECOMMENDATION"
    fake_conn.commit.assert_called_once()


def test_internal_only_raises_a_price_below_the_margin_floor(fake_conn):
    result, _ = _run_without_local_data(fake_conn, _own_product(10.0, cost=10.0))

    assert result["action"] == "raise"
    assert result["suggested_price"] == 11.0  # cost 10 + 10% minimum margin


def test_out_of_region_price_is_converted_adjusted_and_labelled(fake_conn):
    foreign = [{**_competitor_price("f1", "c9", 40.0, currency="USD"), "source": "competitor"}]

    result, mock_evidence = _run_without_local_data(
        fake_conn, _own_product(30.0), references=foreign, convert=lambda conn, amount, f, t: 28.0,
    )

    assert result["status"] == "OK"
    assert result["data_basis"] == "REGIONAL_ESTIMATE"
    assert result["action"] == "lower"  # 30 is ~7% above the converted 28 (default regional factor 1.0)
    assert result["confidence_score"] <= 0.30
    assert "[REGIONAL_ESTIMATE]" in mock_evidence.call_args.args[6]


def test_same_currency_market_reference_price_is_used_without_adjustment(fake_conn):
    reference = [{**_competitor_price("o1", None, 20.0), "source": "market_reference"}]

    result, mock_evidence = _run_without_local_data(fake_conn, _own_product(30.0), references=reference)

    assert result["data_basis"] == "MARKET_REFERENCE"
    assert result["action"] == "lower"
    assert mock_evidence.call_args.args[5] <= 0.50  # confidence is capped for a reference price
    assert mock_evidence.call_args.args[4]["market_observation_ids"] == ["o1"]


def _comparable(entry_id, price, tier):
    return {**_competitor_price(entry_id, "c2", price), "tier": tier}


def test_equivalent_competitor_items_are_used_before_any_reference_or_peer_estimate(fake_conn):
    # A market reference exists too, but a tracked local competitor's equivalent item ranks above it.
    reference = [{**_competitor_price("o1", None, 99.0), "source": "market_reference"}]
    comparable = [_comparable("cmp1", 20.0, "EQUIVALENT"), _comparable("cmp2", 22.0, "SIMILAR")]

    result, mock_evidence = _run_without_local_data(fake_conn, _own_product(30.0), references=reference, comparable=comparable)

    assert result["data_basis"] == "COMPARABLE_ESTIMATE"
    assert result["market"]["average"] == 20.0  # the similar item is not blended into the equivalent tier
    assert result["action"] == "lower"
    assert result["confidence_score"] <= 0.55
    assert result["matched_competitor_count"] == 1
    assert "[COMPARABLE_ESTIMATE]" in mock_evidence.call_args.args[6] and "equivalent" in mock_evidence.call_args.args[6]
    assert mock_evidence.call_args.args[4]["price_comparison_ids"] == ["cmp1"]


def test_similar_items_alone_carry_a_lower_confidence_cap(fake_conn):
    result, _ = _run_without_local_data(fake_conn, _own_product(30.0), comparable=[_comparable("cmp2", 22.0, "SIMILAR")])

    assert result["data_basis"] == "COMPARABLE_ESTIMATE"
    assert result["confidence_score"] <= 0.40


def test_old_competitor_price_still_produces_recommendation_with_date_note(fake_conn):
    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(days=2 * 365)
    competitor_prices = [{**_competitor_price("p1", "c1", 20.0), "captured_at": old}]

    with patch.object(pipeline.data_access, "load_own_product", return_value=_own_product(30.0)), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitor_prices), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1"):
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["status"] == "OK"
    assert result["data_basis"] == "LOCAL_MARKET"
    assert old.date().isoformat() in mock_evidence.call_args.args[6]


def test_recommend_all_decides_every_product_and_continues_past_a_failure(fake_conn):
    fake_conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [("p1",), ("p2",), ("p3",)]

    def fake_run(conn, tenant_id, product_id):
        if product_id == "p2":
            raise RuntimeError("boom")
        return {"status": "OK", "action": "hold", "data_basis": "INTERNAL_ONLY"}

    with patch.object(pipeline, "run_price_recommendation", side_effect=fake_run):
        summary = pipeline.run_price_recommendations_for_all(fake_conn, "tenant-1")

    assert summary["total"] == 3 and summary["decided"] == 2
    assert summary["by_data_basis"] == {"INTERNAL_ONLY": 2}
    assert summary["failed"] == [{"product_id": "p2", "error": "boom"}]


def test_matched_competitors_produce_recommendation_and_outcome_row(fake_conn):
    own = _own_product(30.0)
    competitor_prices = [_competitor_price("p1", "c1", 18.0), _competitor_price("p2", "c2", 20.0)]

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitor_prices), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1") as mock_outcome:
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["status"] == "OK"
    assert result["action"] == "lower"  # 30.0 is well above the ~19.0 market average
    assert result["evidence_id"] == "evidence-1"
    assert result["outcome_id"] == "outcome-1"
    assert result["margin_guardrail_clamped"] is None  # no cost known
    assert result["explanation"]
    assert mock_evidence.call_args.args[2] == "RECOMMENDATION"
    mock_outcome.assert_called_once_with(fake_conn, "evidence-1", "tenant-1", "Lower price to 25.500 JOD")
    fake_conn.commit.assert_called_once()


def test_recommendation_respects_price_change_guardrail(fake_conn):
    own = _own_product(100.0)
    # market average ~10.0, a 90% drop - the guardrail (default 15%) must clamp this
    competitor_prices = [_competitor_price("p1", "c1", 10.0)]

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitor_prices), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1"):
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["guardrail_clamped"] is True
    assert result["suggested_price"] == 85.0  # 100 * (1 - 0.15)


def test_recommendation_with_no_cost_skips_margin_guardrail(fake_conn):
    own = _own_product(100.0, cost=None)
    competitor_prices = [_competitor_price("p1", "c1", 10.0)]

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitor_prices), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1"):
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["margin_guardrail_clamped"] is None
    assert result["suggested_price"] == 85.0  # unaffected, price-change guardrail's floor only


def test_recommendation_respects_margin_guardrail_when_cost_present(fake_conn):
    # own price 17.0, cost 15.0 -> price-change-guardrailed suggestion would be
    # 14.45 (17 * 0.85), below cost - the margin guardrail (default 10%) must
    # raise it back to 15 * 1.10 = 16.5.
    own = _own_product(17.0, cost=15.0)
    competitor_prices = [_competitor_price("p1", "c1", 10.0)]

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitor_prices), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1"):
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["margin_guardrail_clamped"] is True
    assert result["suggested_price"] == 16.5
    explanation = mock_evidence.call_args.args[6]
    assert "minimum-margin floor" in explanation


def test_cross_currency_reference_appended_to_recommendation_explanation(fake_conn):
    own = _own_product(30.0)
    same_currency = [_competitor_price("p1", "c1", 18.0), _competitor_price("p2", "c2", 20.0)]
    cross_currency = [_competitor_price("p3", "c3", 75.0, currency="SAR")]

    def fake_convert(conn, amount, from_currency, to_currency):
        from src.ai.pricing.currency import ConversionResult
        import datetime
        return ConversionResult(
            amount, from_currency, round(amount * 0.95, 2), to_currency, 0.95, datetime.date(2026, 8, 1), "test"
        )

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=same_currency), \
         patch.object(pipeline.data_access, "load_cross_currency_competitor_prices", return_value=cross_currency), \
         patch.object(pipeline.currency, "convert", side_effect=fake_convert), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1"):
        pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    explanation = mock_evidence.call_args.args[6]
    assert "reference only" in explanation
    assert "75.00 SAR" in explanation
    assert "71.250 JOD" in explanation


def test_cross_currency_reference_notes_missing_rate(fake_conn):
    own = _own_product(20.0)
    cross_currency = [_competitor_price("p3", "c3", 75.0, currency="EGP")]

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=[]), \
         patch.object(pipeline.data_access, "load_cross_currency_competitor_prices", return_value=cross_currency), \
         patch.object(pipeline.currency, "convert", return_value=None), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    explanation = mock_evidence.call_args.args[6]
    assert "No current exchange rate available" in explanation
    assert "EGP" in explanation


def test_no_cross_currency_matches_leaves_explanation_unchanged(fake_conn):
    own = _own_product(20.0)

    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=[]), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    explanation = mock_evidence.call_args.args[6]
    assert "reference" not in explanation


def test_action_follows_the_final_price_when_the_margin_floor_overrides_a_cut(fake_conn):
    """Found in acceptance testing: market average 8.00 says 'lower', the
    15% change guardrail caps the cut at 8.500, then the 10% margin floor
    over a 9.50 cost lifts it to 10.450 - above the current 10.00. The
    result used to still say 'Lower price to 10.45'."""
    own = _own_product(10.0, cost=9.5)
    competitors = [_competitor_price("p1", "c1", 8.0), _competitor_price("p2", "c2", 8.0)]
    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=competitors), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1") as mock_outcome:
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")

    assert result["suggested_price"] == 10.45
    assert result["action"] == "raise"
    assert result["margin_guardrail_clamped"] is True
    assert mock_outcome.call_args.args[3] == "Raise price to 10.450 JOD"
    assert "Net recommendation: raise" in result["explanation"]


@pytest.mark.parametrize("currency,current,competitor,expected", [
    ("JOD", 1.125, 1.0, 1.0),      # 3-decimal dinar: 1.000, not 1.00 or 1.13
    ("USD", 9.99, 9.0, 9.0),
    ("XOF", 1500.0, 1300.0, 1300.0),  # CFA franc has no minor unit
])
def test_suggested_prices_use_the_currency_minor_unit(fake_conn, currency, current, competitor, expected):
    own = _own_product(current, currency=currency)
    with patch.object(pipeline.data_access, "load_own_product", return_value=own), \
         patch.object(pipeline.data_access, "load_competitor_prices", return_value=[_competitor_price("p1", "c1", competitor, currency)]), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_recommendation_outcome", return_value="outcome-1") as mock_outcome:
        result = pipeline.run_price_recommendation(fake_conn, "tenant-1", "product-1")
    assert result["suggested_price"] == expected
    text = mock_outcome.call_args.args[3]
    assert text.endswith({"JOD": "1.000 JOD", "USD": "9.00 USD", "XOF": "1300 XOF"}[currency])


def test_money_minor_units():
    from src.ai.core.money import format_money, minor_units, round_money
    assert (minor_units("jod"), minor_units("KWD"), minor_units("USD"), minor_units("JPY"), minor_units(None)) == (3, 3, 2, 0, 2)
    assert round_money(1.1255, "JOD") == 1.126 or round_money(1.1255, "JOD") == 1.125  # binary float tie
    assert format_money(12.5, "JOD") == "12.500" and format_money(1500, "XOF") == "1500" and format_money(9.999, "EUR") == "10.00"
