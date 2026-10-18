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


def test_the_guide_becomes_evidence_in_the_assistant_prompt(monkeypatch):
    from src.ai.rag import advisor, llm_client

    prompts = []
    monkeypatch.setattr(advisor, "_call", lambda messages, usage, max_tokens=None: prompts.append(messages) or
                        '{"blocks": [{"type": "paragraph", "claims": [{"text": "Open Products.", "kind": "fact", "evidence": ["E1"]}]}]}')
    result = advisor.answer(None, "t", "How do I add a product?")
    user_prompt = prompts[0][-1]["content"]
    assert "product guide" in user_prompt and "«Add Product»" in user_prompt
    assert user_prompt.index("Evidence:") < user_prompt.index("Question:")
    assert "product guide" in llm_client.SYSTEM_PROMPT
    assert result["references"][0]["kind"] == "product_guide"
    assert result["references"][0]["route"] == "/products", "the reference opens the screen the steps start from"


def test_every_section_starts_from_a_real_screen():
    import re

    routes = Path(__file__).resolve().parents[4] / "frontend" / "src" / "app" / "router" / "routePaths.js"
    real = set(re.findall(r":\s*'(/[^']*)'", routes.read_text(encoding="utf-8")))
    assert set(product_guide.SCREENS) == {key for key, _keywords, _text in product_guide.SECTIONS}
    assert set(product_guide.SCREENS.values()) <= real
    assert product_guide.guide_screens("How do I invite a colleague to my team?") == ["/settings/team"]
    assert product_guide.guide_screens("How were my sales?") == []


def test_a_how_to_question_never_triggers_research_or_the_old_registry_steps(monkeypatch):
    from src.ai.rag import advisor

    researched = []
    monkeypatch.setattr(advisor.public_research, "research", lambda *a, **k: researched.append(1))
    monkeypatch.setattr(advisor, "build_tool_facts_blocks", lambda *a, **k: [("CEOPRO_APPLICATION_KNOWLEDGE", "Click 'Add product' ... Save")])
    prompts = []
    monkeypatch.setattr(advisor, "_call", lambda messages, usage, max_tokens=None: prompts.append(messages) or
                        '{"blocks": [{"type": "paragraph", "claims": [{"text": "Use Products.", "kind": "general", "evidence": []}]}]}')
    advisor.answer(None, "tenant", "How do I add a product?")
    assert "Click 'Add product'" not in prompts[0][-1]["content"]
    assert researched == []
