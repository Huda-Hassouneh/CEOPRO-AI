"""
Country-level calendar facts the analytics need. The forecasting weekend
flag was hard-coded to Friday/Saturday ("spec targets MENA/Africa"), which
is wrong for most countries the product signs up - France, Morocco,
Tunisia, Senegal, the UAE since 2022 and everywhere else that rests on
Saturday/Sunday. Days use pandas' convention: Monday=0 ... Sunday=6.
"""
from typing import FrozenSet, Optional

import pytz

SATURDAY_SUNDAY = frozenset({5, 6})
FRIDAY_SATURDAY = frozenset({4, 5})

_WEEKEND_BY_COUNTRY = {
    # Friday/Saturday
    "BH": FRIDAY_SATURDAY, "DZ": FRIDAY_SATURDAY, "EG": FRIDAY_SATURDAY, "IQ": FRIDAY_SATURDAY,
    "JO": FRIDAY_SATURDAY, "KW": FRIDAY_SATURDAY, "LY": FRIDAY_SATURDAY, "OM": FRIDAY_SATURDAY,
    "QA": FRIDAY_SATURDAY, "SA": FRIDAY_SATURDAY, "SD": FRIDAY_SATURDAY, "SY": FRIDAY_SATURDAY,
    # Thursday/Friday
    "YE": frozenset({3, 4}),
    # Friday only
    "IR": frozenset({4}), "DJ": frozenset({4}),
    # Sunday only
    "IN": frozenset({6}), "MX": frozenset({6}),
}


def weekend_days(country_code: Optional[str]) -> FrozenSet[int]:
    return _WEEKEND_BY_COUNTRY.get((country_code or "").strip().upper(), SATURDAY_SUNDAY)


def default_timezone_for_country(country_code: Optional[str]) -> str:
    """The country's primary IANA zone (its first, most populous listing),
    UTC when unknown. A starting default the owner can change in Settings."""
    zones = pytz.country_timezones.get((country_code or "").strip().upper())
    return zones[0] if zones else "UTC"
