from unittest.mock import patch

from src.market_scraper.price_comparison import adjudicate


def setup_function():
    adjudicate._CACHE.clear()


def _ask(reply):
    return patch("src.ai.rag.llm_client.chat_completion", return_value=reply)


def test_a_one_word_answer_is_read_and_cached():
    with patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), _ask("Addition.") as ask:
        assert adjudicate.model_judge("Conversation class", "class", "own", ["conversation"]) == "addition"
        assert adjudicate.model_judge("Conversation class", "class", "own", ["conversation"]) == "addition"
    assert ask.call_count == 1


def test_an_unclear_answer_is_no_verdict():
    with patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), _ask("It depends on the menu"):
        assert adjudicate.model_judge("A b", "b", "own", ["a"]) is None


def test_ai_hints_off_asks_nothing():
    with patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "false"}), _ask("addition") as ask:
        assert adjudicate.model_judge("A b", "b", "own", ["a"]) is None
    ask.assert_not_called()


def test_a_model_error_is_no_verdict_and_not_cached():
    with patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), patch("src.ai.rag.llm_client.chat_completion", side_effect=RuntimeError("down")):
        assert adjudicate.model_judge("A b", "b", "own", ["a"]) is None
    with patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), _ask("variant"):
        assert adjudicate.model_judge("A b", "b", "own", ["a"]) == "variant"
