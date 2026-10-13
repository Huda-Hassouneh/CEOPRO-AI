"""
Unit tests for rag/business_tools.py - the query-driven (not always-on)
financial facts block. dashboard/financial_summary.py's own SQL
correctness is covered by test_financial_summary_integration_db.py; this
file mocks those two functions to test business_tools.py's own intent
gating and formatting logic in isolation, same convention as
test_marketing_content_generator.py mocking llm_client.chat_completion.
"""
from unittest.mock import patch

from src.ai.rag.business_tools import build_financial_facts_block, is_financial_question


# --- is_financial_question ---------------------------------------------

def test_recognizes_english_financial_questions():
    assert is_financial_question("Which products are most profitable?")
    assert is_financial_question("Where did my profit go?")
    assert is_financial_question("What is my gross margin this month?")
    assert is_financial_question("Which product is losing money?")


def test_recognizes_arabic_financial_questions():
    assert is_financial_question("وين راح الربح تبعي؟")
    assert is_financial_question("شو أكثر منتج ربحية؟")


def test_does_not_flag_unrelated_questions():
    assert not is_financial_question("How do I add a new product?")
    assert not is_financial_question("Who is my strongest competitor?")
    assert not is_financial_question("hello")


def test_handles_none_and_empty_query_text():
    assert not is_financial_question(None)
    assert not is_financial_question("")


# --- build_financial_facts_block --------------------------------------

_EMPTY_SUMMARY = {
    "window_days": 30, "currency": "JOD",
    "revenue": {"amount": 0.0, "change_pct": None},
    "cost_data_coverage_pct": None,
    "gross_profit": {"amount": None, "change_pct": None},
    "gross_margin_pct": {"recent": None, "change_pts": None},
    "excludes": ["fixed_operating_expenses", "marketing_spend", "discounts_and_returns", "taxes"],
}

_EMPTY_RANKING = {"window_days": 30, "most_profitable": [], "least_profitable": [], "no_cost_data": []}


def test_returns_empty_string_for_non_financial_question():
    with patch("src.ai.rag.business_tools.get_profitability_summary") as mock_summary:
        result = build_financial_facts_block(conn=None, tenant_id="t1", query_text="How do I add a product?")
    assert result == ""
    mock_summary.assert_not_called()  # never runs the extra queries for an irrelevant question


def test_returns_empty_string_when_no_revenue_at_all():
    with patch("src.ai.rag.business_tools.get_profitability_summary", return_value=_EMPTY_SUMMARY), \
         patch("src.ai.rag.business_tools.get_product_profitability", return_value=_EMPTY_RANKING):
        result = build_financial_facts_block(conn=None, tenant_id="t1", query_text="Where did my profit go?")
    assert result == ""


def test_builds_block_with_gross_margin_and_explicit_exclusions():
    summary = {
        "window_days": 30, "currency": "JOD",
        "revenue": {"amount": 500.0, "change_pct": 10.0},
        "cost_data_coverage_pct": 80.0,
        "gross_profit": {"amount": 150.0, "change_pct": 5.0},
        "gross_margin_pct": {"recent": 30.0, "change_pts": -2.0},
        "excludes": ["fixed_operating_expenses", "marketing_spend", "discounts_and_returns", "taxes"],
    }
    ranking = {
        "window_days": 30,
        "most_profitable": [{"product_id": "p1", "product_name": "Star", "units_sold": 20, "revenue": 200.0, "gross_profit": 100.0, "gross_margin_pct": 50.0}],
        "least_profitable": [{"product_id": "p2", "product_name": "Dud", "units_sold": 5, "revenue": 20.0, "gross_profit": -10.0, "gross_margin_pct": -50.0}],
        "no_cost_data": [{"product_id": "p3", "product_name": "Unknown", "units_sold": 3, "revenue": 30.0}],
    }
    with patch("src.ai.rag.business_tools.get_profitability_summary", return_value=summary), \
         patch("src.ai.rag.business_tools.get_product_profitability", return_value=ranking):
        result = build_financial_facts_block(conn=None, tenant_id="t1", query_text="Which product is most profitable?")

    assert "500.0" in result
    assert "gross margin 30.0%" in result
    assert "GROSS margin only" in result
    assert "fixed operating expenses" in result
    assert "Star" in result and "100.0" in result
    assert "Dud" in result  # losing money, flagged separately
    assert "Unknown" in result  # excluded-from-margin product named explicitly


def test_omits_losing_money_line_when_least_profitable_is_still_profitable():
    summary = dict(_EMPTY_SUMMARY, revenue={"amount": 500.0, "change_pct": None}, cost_data_coverage_pct=100.0,
                    gross_profit={"amount": 150.0, "change_pct": None}, gross_margin_pct={"recent": 30.0, "change_pts": None})
    ranking = {
        "window_days": 30,
        "most_profitable": [{"product_id": "p1", "product_name": "Good", "units_sold": 10, "revenue": 300.0, "gross_profit": 100.0, "gross_margin_pct": 33.3}],
        "least_profitable": [{"product_id": "p2", "product_name": "Still Fine", "units_sold": 5, "revenue": 200.0, "gross_profit": 50.0, "gross_margin_pct": 25.0}],
        "no_cost_data": [],
    }
    with patch("src.ai.rag.business_tools.get_profitability_summary", return_value=summary), \
         patch("src.ai.rag.business_tools.get_product_profitability", return_value=ranking):
        result = build_financial_facts_block(conn=None, tenant_id="t1", query_text="most profitable product")

    assert "Losing money" not in result  # nothing is actually losing money - never fabricate a loss
