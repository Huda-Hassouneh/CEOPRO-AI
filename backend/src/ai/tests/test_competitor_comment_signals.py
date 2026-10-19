"""competitor_comments.signal_for: which comments are worth acting on."""
import pytest

from src.ai.market_inputs import competitor_comments as cc


@pytest.mark.parametrize("sentiment,agreeing,expected", [
    ("NEGATIVE", 3, "opportunity"),
    ("negative", 400, "opportunity"),
    ("positive", 3, "threat"),
    ("negative", 2, None),      # too few people agree
    ("negative", None, None),   # likes unknown
    ("neutral", 500, None),
    (None, 500, None),          # sentiment not analysed yet
])
def test_signal_needs_a_clear_sentiment_and_enough_people_agreeing(sentiment, agreeing, expected):
    assert cc.signal_for(sentiment, agreeing) == expected


def test_a_bad_sentiment_filter_is_refused_before_any_query():
    with pytest.raises(ValueError):
        cc.list_competitor_comments(object(), "t", "c", sentiment="angry")
