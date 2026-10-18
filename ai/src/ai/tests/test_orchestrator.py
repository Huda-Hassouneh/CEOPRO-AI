"""
Offline, mocked unit tests for rag/orchestrator.py's intent-keyword gate -
same style as test_business_tools.py: mock the underlying rag/tools.py
functions, verify the gate calls the right tool(s) for the right question
and none for an unrelated one, and verify formatting/labeling.
"""
from unittest.mock import patch

from src.ai.rag.orchestrator import build_tool_facts_blocks, format_blocks_for_prompt


def test_unrelated_question_calls_no_tools():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="what's the weather like")
        assert blocks == []
        mock_tools.search_application_knowledge.assert_not_called()
        mock_tools.get_top_selling_products.assert_not_called()


def test_how_do_i_question_calls_only_application_knowledge():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.search_application_knowledge.return_value = {
            "matches": [{"name": "Add a product", "route": "/products/new", "action_steps": ["Go to Products", "Click Add"]}]
        }
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="how do I add a product?")

        mock_tools.search_application_knowledge.assert_called_once()
        mock_tools.get_top_selling_products.assert_not_called()
        mock_tools.list_competitors.assert_not_called()
        assert len(blocks) == 1
        label, text = blocks[0]
        assert label == "CEOPRO_APPLICATION_KNOWLEDGE"
        assert "Add a product" in text


def test_best_selling_question_calls_only_top_products():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.get_top_selling_products.return_value = {
            "top_by_gross_profit": [{"product_name": "Widget", "units_sold": 10, "gross_profit": 50.0, "gross_margin_pct": 25.0}]
        }
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="what is my best selling product?")

        mock_tools.get_top_selling_products.assert_called_once()
        mock_tools.search_application_knowledge.assert_not_called()
        assert len(blocks) == 1
        label, text = blocks[0]
        assert label == "TENANT_BUSINESS_DATA"
        assert "Widget" in text


def test_low_stock_question_calls_only_inventory_tool():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.get_low_stock_products.return_value = {"low_stock_products": []}
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="which products are running low on stock?")

        mock_tools.get_low_stock_products.assert_called_once()
        mock_tools.get_top_selling_products.assert_not_called()
        assert len(blocks) == 1
        assert blocks[0][0] == "TENANT_BUSINESS_DATA"


def test_competitor_question_calls_directory_and_activity_tools():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.list_competitors.return_value = {"strategic": [], "relevant": []}
        mock_tools.get_competitor_activity.return_value = {"recent_price_changes": []}
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="who is my strongest competitor?")

        mock_tools.list_competitors.assert_called_once()
        mock_tools.get_competitor_activity.assert_called_once()
        assert len(blocks) == 1


def test_why_did_profit_change_calls_root_cause_tools():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.analyze_revenue_change.return_value = {
            "has_data": True, "revenue_change": 100.0,
            "drivers": {"units_effect": 60.0, "price_effect": 40.0},
            "top_movers": [{"product_name": "Widget", "revenue_change": 80.0}],
            "movers_caveat": "correlation/signal, not proof of causation.",
        }
        mock_tools.analyze_margin.return_value = {"has_data": False}
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="why did my profit go down this month?")

        mock_tools.analyze_revenue_change.assert_called_once()
        mock_tools.analyze_margin.assert_called_once()
        assert len(blocks) == 1
        label, text = blocks[0]
        assert label == "TENANT_BUSINESS_DATA"
        assert "correlation/signal, not proof of causation" in text


def test_where_did_my_profits_go_calls_root_cause_tools():
    """Regression test for a real gap a verification pass found: the
    canonical "Where did my profits go?" phrasing (this feature's own
    originating worked example) did not match the original
    _ROOT_CAUSE_KEYWORDS list, which only covered "why did/is/..."
    phrasing. Fixed by adding "where did"/"where has" patterns."""
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.analyze_revenue_change.return_value = {
            "has_data": True, "revenue_change": -50.0,
            "drivers": {"units_effect": -30.0, "price_effect": -20.0},
            "top_movers": [], "movers_caveat": "x",
        }
        mock_tools.analyze_margin.return_value = {"has_data": False}
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="Where did my profits go?")

        mock_tools.analyze_revenue_change.assert_called_once()
        assert len(blocks) == 1
        assert blocks[0][0] == "TENANT_BUSINESS_DATA"


def test_root_cause_omits_block_when_no_data_at_all():
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.analyze_revenue_change.return_value = {"has_data": False}
        mock_tools.analyze_margin.return_value = {"has_data": False}
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="why is revenue falling?")

        assert blocks == []


def test_multiple_intents_in_one_question_call_multiple_tools():
    """"why did my best selling product's revenue drop" should plausibly
    match both the top-products and root-cause gates - proving the gate
    can select MORE than one tool for one question when the text
    genuinely matches more than one category, without calling every tool."""
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.get_top_selling_products.return_value = {"top_by_gross_profit": [{"product_name": "Widget", "units_sold": 5, "gross_profit": 10.0, "gross_margin_pct": 10.0}]}
        mock_tools.analyze_revenue_change.return_value = {"has_data": False}
        mock_tools.analyze_margin.return_value = {"has_data": False}

        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="why did my best selling product change?")

        mock_tools.get_top_selling_products.assert_called_once()
        mock_tools.analyze_revenue_change.assert_called_once()
        mock_tools.list_competitors.assert_not_called()
        mock_tools.get_low_stock_products.assert_not_called()


def test_conflicting_signals_from_two_tools_are_both_surfaced_unreconciled():
    """Part 6's "conflicting data" category: a question that plausibly
    triggers two tools whose facts could look contradictory (the
    best-selling product is ALSO critically low on stock) must return
    BOTH blocks verbatim - the orchestrator's job is deterministic
    retrieval, never silent reconciliation or picking a "winner" between
    two real facts. Resolving the tension (e.g. "your best seller is
    about to stock out") is the LLM synthesis layer's job, with both
    facts visible and citable, not something decided before the LLM ever
    sees the question."""
    with patch("src.ai.rag.orchestrator._tools") as mock_tools:
        mock_tools.get_top_selling_products.return_value = {
            "top_by_gross_profit": [{"product_name": "Widget", "units_sold": 200, "gross_profit": 900.0, "gross_margin_pct": 45.0}]
        }
        mock_tools.get_low_stock_products.return_value = {
            "low_stock_products": [{"product_name": "Widget", "stock_quantity": 2, "reorder_level": 20}]
        }
        blocks = build_tool_facts_blocks(conn=None, tenant_id="t1", query_text="is my best selling product running low on stock?")

        mock_tools.get_top_selling_products.assert_called_once()
        mock_tools.get_low_stock_products.assert_called_once()
        assert len(blocks) == 2
        combined_text = " ".join(text for _label, text in blocks)
        # Both the strong-seller fact and the low-stock fact for the same
        # product must be present, unmodified - neither tool's output
        # suppresses or overrides the other's.
        assert "200" in combined_text
        assert "2" in combined_text
        assert all(label == "TENANT_BUSINESS_DATA" for label, _text in blocks)


def test_format_blocks_for_prompt_labels_each_block():
    blocks = [("TENANT_BUSINESS_DATA", "Revenue: 100"), ("CEOPRO_APPLICATION_KNOWLEDGE", "Go to Products")]
    formatted = format_blocks_for_prompt(blocks)
    assert "[TENANT_BUSINESS_DATA]" in formatted
    assert "[CEOPRO_APPLICATION_KNOWLEDGE]" in formatted
    assert "Revenue: 100" in formatted
    assert "Go to Products" in formatted


def test_format_blocks_for_prompt_empty_list_returns_empty_string():
    assert format_blocks_for_prompt([]) == ""
