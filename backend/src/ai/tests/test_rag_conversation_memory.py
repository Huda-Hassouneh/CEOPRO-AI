"""Conversation memory (rag/conversation_memory.py): long messages and long
conversations reach the model by relevance, within a bounded prompt."""
from src.ai.rag import conversation_memory as memory


def _filler(words, word="lorem"):
    return " ".join(f"{word}{i}" for i in range(words))


def test_a_short_message_is_left_as_it_is():
    assert memory.focus("What were sales last week?") == "What were sales last week?"


def test_a_long_message_keeps_its_start_and_end():
    text = "Here is our export. " + _filler(3000) + " Which supplier was cheapest?"
    focused = memory.focus(text)
    assert len(focused) <= memory.LONG_MESSAGE_CHARS + 3
    assert focused.startswith("Here is our export.") and focused.endswith("Which supplier was cheapest?")


def test_the_passage_that_answers_is_found_in_the_middle_of_a_huge_text():
    text = _filler(20000) + " The supplier Nablus Olive Co charged 3.75 JOD per litre. " + _filler(20000, "ipsum")
    passages = memory.relevant_passages([("Your message", text)], "what did Nablus Olive charge per litre")
    assert any("3.75 JOD" in passage for _, passage in passages)
    assert sum(len(passage) for _, passage in passages) <= memory.MEMORY_BUDGET_CHARS


def test_passages_come_back_in_the_order_they_were_written():
    sources = [("Earlier", f"Message one about pricing {_filler(200)}"),
               ("Earlier", f"Message two about pricing {_filler(200, 'x')}")]
    passages = memory.relevant_passages(sources, "pricing", budget=10**6)
    assert passages[0][1].startswith("Message one") and passages[-1][1].endswith(_filler(200, "x").split()[-1])


def test_no_shared_word_still_recalls_the_newest_passages():
    sources = [("Earlier", "first old message"), ("Earlier", "the most recent message")]
    assert memory.relevant_passages(sources, "زيت", budget=25) == [("Earlier", "the most recent message")]


def test_nothing_to_recall():
    assert memory.relevant_passages([], "anything") == []
