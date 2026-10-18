from datetime import date

from src.ai.marketing import occasions


def test_black_friday_is_the_day_after_us_thanksgiving():
    assert occasions._black_friday(2026) == date(2026, 11, 27)
    assert occasions._black_friday(2027) == date(2027, 11, 26)


def test_occasions_follow_the_country():
    jordan = {key for key, *_ in occasions.occasions_between("JO", date(2026, 5, 1), date(2026, 5, 31))}
    france = {key for key, *_ in occasions.occasions_between("FR", date(2026, 5, 1), date(2026, 5, 31))}
    assert {"national_day", "eid_adha"} <= jordan
    assert "national_day" not in france  # France's is in July


def test_islamic_dates_are_flagged_as_moon_dependent():
    windows = occasions.occasions_between("JO", date(2027, 2, 1), date(2027, 3, 31))
    ramadan = next(w for w in windows if w[0] == "ramadan")
    assert ramadan[1] == date(2027, 2, 8) and ramadan[3] is True


def test_every_occasion_has_a_creative_direction():
    keys = {key for key, *_ in occasions.occasions_between("JO", date(2026, 1, 1), date(2027, 12, 31))}
    assert keys <= set(occasions.OCCASION_STYLE)
