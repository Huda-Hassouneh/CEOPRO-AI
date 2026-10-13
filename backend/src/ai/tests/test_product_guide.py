"""
The assistant's product guide (rag/product_guide.py) may only name screens,
tabs and buttons that really exist: every [[English||Arabic]] label must be
an actual string in the frontend's own en.json / ar.json.
"""
import json
from pathlib import Path

import pytest

from src.ai.rag import product_guide

LOCALES = Path(__file__).resolve().parents[4] / "frontend" / "src" / "assets" / "locales"


def _strings(path: Path) -> set:
    out = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, str):
            out.add(node)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return out


@pytest.mark.skipif(not LOCALES.exists(), reason="frontend locales not present in this checkout")
@pytest.mark.parametrize("english, arabic", product_guide.labels())
def test_every_label_in_the_guide_is_a_real_interface_label(english, arabic):
    assert english in _strings(LOCALES / "en.json"), f"{english!r} is not an English interface label"
    assert arabic in _strings(LOCALES / "ar.json"), f"{arabic!r} is not an Arabic interface label"


@pytest.mark.parametrize("question, expected", [
    ("How do I add a product?", "add_product"),
    ("Where do I upload my sales file?", "upload_sales"),
    ("How do I create a campaign?", "campaign"),
    ("Where can I see competitors?", "competitors"),
    ("How do I generate a forecast?", "forecast"),
    ("How do I change my target market?", "target_markets"),
    ("كيف أضيف منتج جديد؟", "add_product"),
    ("وين أرفع ملف المبيعات؟", "upload_sales"),
    ("كيف أغير الأسواق المستهدفة؟", "target_markets"),
])
def test_questions_select_the_matching_section(question, expected):
    text = dict((key, body) for key, _kw, body in product_guide.SECTIONS)[expected]
    rendered_en = product_guide._render(text, "en")
    assert rendered_en in product_guide.select_sections(question, "en")


def test_labels_are_rendered_in_the_reader_s_language():
    en = product_guide.build_guide_block("How do I add a product?", "en")
    ar = product_guide.build_guide_block("كيف أضيف منتج؟", "ar")
    assert "«Add Product»" in en and "«إضافة منتج»" in ar and "[[" not in en + ar


def test_unrelated_questions_get_no_guide():
    assert product_guide.build_guide_block("What was my revenue yesterday?", "en") == ""


@pytest.mark.parametrize("question", [
    "What's my best selling product?",
    "Should I raise my price?",
    "Which products are declining?",
    "ما هو أكثر منتج مبيعاً؟",
])
def test_business_questions_get_no_navigation_steps(question):
    assert product_guide.build_guide_block(question) == ""


def test_short_keywords_match_whole_words_only():
    # "ad" (campaign) must not match inside "add"
    assert len(product_guide.select_sections("how do i add a product", "en")) == 1


def test_the_reader_s_language_is_taken_from_the_question():
    assert "«المنتجات»" in product_guide.build_guide_block("كيف أضيف منتج جديد؟")
    assert "«Products»" in product_guide.build_guide_block("How do I add a new product?")


def test_the_guide_is_placed_in_the_assistant_prompt():
    from src.ai.rag import llm_client
    from src.ai.rag.pipeline import AssembledContext

    block = product_guide.build_guide_block("How do I add a product?")
    context = AssembledContext(query="How do I add a product?", context_text="", sources=[])
    prompt = llm_client._build_user_prompt(context, product_guide_block=block)
    assert block in prompt and prompt.index(block) < prompt.index("Question:")
    assert "How to do this in KEEL" in llm_client.SYSTEM_PROMPT


def test_answer_query_sends_the_guide_and_not_the_old_registry_steps():
    from unittest.mock import patch
    from src.ai.rag import llm_client
    from src.ai.rag.pipeline import AssembledContext

    question = "How do I add a product?"
    empty = AssembledContext(query=question, context_text="", sources=[])
    registry = ("CEOPRO_APPLICATION_KNOWLEDGE", "Click 'Add product' ... Save")
    with patch.object(llm_client, "run_retrieval", return_value=empty), \
         patch.object(llm_client, "build_structured_facts_block", return_value=""), \
         patch.object(llm_client, "build_financial_facts_block", return_value=""), \
         patch("src.ai.rag.orchestrator.build_tool_facts_blocks", return_value=[registry]), \
         patch.object(llm_client.web_fallback, "build_web_fallback_context") as web, \
         patch.object(llm_client, "_generate_answer_with_usage", return_value=("ok", {})) as generate:
        llm_client.answer_query(object(), "tenant", question)
    kwargs = generate.call_args.kwargs
    assert "«Add Product»" in kwargs["product_guide_block"]
    assert "CEOPRO_APPLICATION_KNOWLEDGE" not in kwargs["structured_facts"]
    web.assert_not_called()  # a how-to question never triggers web research
