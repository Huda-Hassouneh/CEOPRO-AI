"""comment_themes: deterministic themes in English and Arabic."""
from src.ai.market_inputs import comment_themes as ct


def test_a_comment_can_touch_several_themes_in_either_language():
    assert set(ct.themes_in("The waiter was rude and the prices are far too high")) == {"staff", "price"}
    assert set(ct.themes_in("الخدمة بطيئة جدا والأسعار مرتفعة")) == {"service", "waiting", "price"}
    assert ct.themes_in("Went on Sunday") == [] and ct.themes_in(None) == []


def test_summary_counts_complaints_first_and_picks_the_most_agreed_example():
    rows = [
        ("a", "Slow service, waited an hour", "NEGATIVE", 3),
        ("b", "Very slow again", "negative", 40),
        ("c", "Great service and fresh food", "POSITIVE", 5),
        ("d", "Nothing to say", None, 0),
    ]
    summary = ct.summarise(rows)
    by = {t["theme"]: t for t in summary}
    assert by["waiting"]["mentions"] == 2 and by["waiting"]["negative"] == 2
    assert by["waiting"]["example"] == {"id": "b", "text": "Very slow again", "people_agreeing": 40}
    assert by["service"]["mentions"] == 2 and by["service"]["positive"] == 1
    assert summary[0]["theme"] == "waiting"  # most complaints first
    assert "quality" in by and by["quality"]["positive"] == 1


def test_like_patterns_escape_wildcards():
    assert all(p.startswith("%") and p.endswith("%") for p in ct.ilike_patterns("price"))
    assert set(ct.THEME_KEYS) == set(ct.THEMES)
