"""
The time periods a question names, as exact calendar date ranges.

"Last month" is the previous calendar month, "this year" runs from 1 January
to today, "March 2026", "Q2 2025", "2025", "between 1 May and 15 June",
"آذار", "الربع الأول", "شهر 9", "yesterday" are each read as the dates they
mean - never as "the last 30 days". "Last 30 days" / "past 3 months" keep
their rolling meaning. Every period ends on its last day inclusive in the
label and exclusive in `end`, so `issue_date >= start AND issue_date < end`
is exact.

Deterministic pattern matching over the normalised text (understanding._norm:
lower case, Western digits, أ/إ/آ -> ا, ة -> ه, ى -> ي); nothing is inferred
that the text does not say. A month or quarter named without a year is the
most recent one that has started.
"""
import calendar
import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

# Normalised month names, English and Arabic (Levantine/Iraqi and Egyptian/Gulf names).
MONTH_NAMES = _MONTHS = {
    1: ("january", "jan", "كانون الثاني", "كانون ثاني", "يناير"),
    2: ("february", "feb", "شباط", "فبراير"),
    3: ("march", "اذار", "مارس"),
    4: ("april", "apr", "نيسان", "ابريل", "إبريل"),
    5: ("may", "ايار", "مايو"),
    6: ("june", "jun", "حزيران", "يونيو", "يونيه"),
    7: ("july", "jul", "تموز", "يوليو", "يوليه"),
    8: ("august", "aug", "اب", "اغسطس", "أغسطس"),
    9: ("september", "sept", "sep", "ايلول", "سبتمبر"),
    10: ("october", "oct", "تشرين الاول", "تشرين اول", "اكتوبر"),
    11: ("november", "nov", "تشرين الثاني", "تشرين ثاني", "نوفمبر"),
    12: ("december", "dec", "كانون الاول", "كانون اول", "ديسمبر"),
}
# Words that are only a month when they stand next to a month cue: "may" is a verb, "اب" a father.
_AMBIGUOUS = {"may", "اب", "mar", "jun", "jul"}
# Arabic letters only: Arabic punctuation (؟ ، ؛) shares the block and must still end a word.
_ARABIC = "ء-يٱ-ۓ"
_ORDINAL_QUARTER = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
                    "last": None, "الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4}
_RANGE_JOINERS = r"(?:to|until|till|through|and|-|–|الي|الى|حتى|لغايه|لغايت|ل|و)"


def _norm_name(name: str) -> str:
    return name.lower().translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))


def _word(name: str, prefixed: bool = False) -> str:
    """A whole-word pattern for an English or Arabic name; `prefixed` also
    allows an attached Arabic preposition/conjunction ("بآب", "وأيلول")."""
    prefix = "(?:[وبل])?" if prefixed and re.match(f"[{_ARABIC}]", name) else ""
    return rf"(?<![a-z{_ARABIC}]){prefix}{re.escape(name)}(?![a-z{_ARABIC}])"


_MONTH_NAMES = sorted(((n, _norm_name(name)) for n, names in _MONTHS.items() for name in names),
                      key=lambda item: -len(item[1]))
_MONTH_ALTERNATION = "|".join(_word(name, prefixed=True) for _, name in _MONTH_NAMES)
_MONTH_BY_NAME = {name: n for n, name in _MONTH_NAMES}
_YEAR = r"(?<!\d)(20\d{2})(?!\d)"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=1)


def _period(start: date, end: date, label: str, kind: str) -> dict:
    """end is exclusive."""
    return {"start": start.isoformat(), "end": end.isoformat(), "label": label, "kind": kind}


def _month_period(year: int, month: int, today: Optional[date] = None) -> dict:
    if today and (year, month) == (today.year, today.month):
        return _period(date(year, month, 1), today + timedelta(days=1), f"{calendar.month_name[month]} {year} to date",
                       "month_to_date")
    return _period(date(year, month, 1), _month_end(year, month), f"{calendar.month_name[month]} {year}", "month")


def _quarter_period(year: int, quarter: int, today: Optional[date] = None) -> dict:
    first = 3 * (quarter - 1) + 1
    if today and year == today.year and (today.month - 1) // 3 + 1 == quarter:
        return _period(date(year, first, 1), today + timedelta(days=1), f"Q{quarter} {year} to date", "quarter_to_date")
    return _period(date(year, first, 1), _month_end(year, first + 2), f"Q{quarter} {year}", "quarter")


def _year_period(year: int, today: date) -> dict:
    if year == today.year:
        return _period(date(year, 1, 1), today + timedelta(days=1), f"{year} to date", "year_to_date")
    return _period(date(year, 1, 1), date(year + 1, 1, 1), str(year), "year")


def _recent_year(month: int, today: date) -> int:
    """The year of the most recent `month` that has started."""
    return today.year if month <= today.month else today.year - 1


def previous_period(period: dict) -> dict:
    """The period of the same kind just before `period`: the previous month,
    quarter or year, else the same number of days just before."""
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    kind = period.get("kind")
    if kind == "month":
        before = start - timedelta(days=1)
        return _month_period(before.year, before.month)
    if kind == "quarter":
        before = start - timedelta(days=1)
        return _quarter_period(before.year, (before.month - 1) // 3 + 1)
    if kind == "year":
        return _period(date(start.year - 1, 1, 1), start, str(start.year - 1), "year")
    days = (end - start).days
    if kind in ("month_to_date", "year_to_date", "quarter_to_date"):
        # The same stretch of the previous month/year/quarter: 1-28 October vs 1-28 September.
        if kind == "month_to_date":
            prior_start = (start - timedelta(days=1)).replace(day=1)
        elif kind == "year_to_date":
            prior_start = start.replace(year=start.year - 1)
        else:
            prior_start = date(start.year if start.month > 3 else start.year - 1, (start.month - 4) % 12 + 1, 1)
        last_day = calendar.monthrange(prior_start.year, prior_start.month)[1]
        prior_end_day = prior_start + timedelta(days=days)
        if kind == "month_to_date" and days > last_day:
            prior_end_day = _month_end(prior_start.year, prior_start.month)
        return _period(prior_start, prior_end_day, f"{prior_start.isoformat()} to "
                       f"{(prior_end_day - timedelta(days=1)).isoformat()}", "days")
    prior_start = start - timedelta(days=days)
    return _period(prior_start, start, f"{prior_start.isoformat()} to {(start - timedelta(days=1)).isoformat()}", "days")


def label_dates(period: dict) -> str:
    """'1 September 2026 - 30 September 2026' style, exact days included."""
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"]) - timedelta(days=1)
    return f"{start.isoformat()} to {end.isoformat()}"


# --- relative periods ----------------------------------------------------------

_RELATIVE = (
    (("today", "اليوم", "هاليوم"), "today"),
    (("yesterday", "امس", "مبارح", "البارحه"), "yesterday"),
    (("this week", "هالاسبوع", "هذا الاسبوع", "الاسبوع الحالي"), "this_week"),
    (("last week", "previous week", "الاسبوع الماضي", "الاسبوع اللي فات", "الاسبوع السابق"), "last_week"),
    (("this month", "current month", "month to date", "month-to-date", "mtd", "هالشهر", "هذا الشهر", "الشهر الحالي"),
     "this_month"),
    (("last month", "previous month", "الشهر الماضي", "الشهر اللي فات", "الشهر السابق", "الشهر المنصرم"), "last_month"),
    (("this quarter", "current quarter", "الربع الحالي", "هذا الربع"), "this_quarter"),
    (("last quarter", "previous quarter", "الربع الماضي", "الربع السابق"), "last_quarter"),
    (("this year", "current year", "year to date", "year-to-date", "ytd", "هالسنه", "هذه السنه", "هذا العام",
      "السنه الحاليه", "العام الحالي"), "this_year"),
    (("last year", "previous year", "السنه الماضيه", "العام الماضي", "السنه اللي فاتت", "السنه السابقه",
      "العام السابق"), "last_year"),
)


def _relative(key: str, today: date) -> dict:
    if key == "today":
        return _period(today, today + timedelta(days=1), f"today ({today.isoformat()})", "days")
    if key == "yesterday":
        day = today - timedelta(days=1)
        return _period(day, today, f"yesterday ({day.isoformat()})", "days")
    if key == "this_week":
        start = today - timedelta(days=6)
        return _period(start, today + timedelta(days=1), f"the last 7 days ({start.isoformat()} to {today.isoformat()})",
                       "days")
    if key == "last_week":
        end = today - timedelta(days=6)
        start = end - timedelta(days=7)
        return _period(start, end, f"the 7 days before that ({start.isoformat()} to "
                       f"{(end - timedelta(days=1)).isoformat()})", "days")
    if key == "this_month":
        return _period(today.replace(day=1), today + timedelta(days=1),
                       f"{calendar.month_name[today.month]} {today.year} to date", "month_to_date")
    if key == "last_month":
        before = today.replace(day=1) - timedelta(days=1)
        return _month_period(before.year, before.month)
    quarter = (today.month - 1) // 3 + 1
    if key == "this_quarter":
        start = date(today.year, 3 * (quarter - 1) + 1, 1)
        return _period(start, today + timedelta(days=1), f"Q{quarter} {today.year} to date", "quarter_to_date")
    if key == "last_quarter":
        return _quarter_period(today.year if quarter > 1 else today.year - 1, quarter - 1 if quarter > 1 else 4)
    if key == "this_year":
        return _year_period(today.year, today)
    return _year_period(today.year - 1, today)  # last_year


# Rolling windows keep their meaning: "the last 3 months" is the trailing 90 days.
_ROLLING = (
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+days?|(?:اخر|الـ?)\s*(\d+)\s+(?:يوم|ايام)"), 1),
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+weeks?|اخر\s+(\d+)\s+(?:اسبوع|اسابيع)"), 7),
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+months?|اخر\s+(\d+)\s+(?:شهر|اشهر|شهور)"), 30),
    (re.compile(r"(?:last|past|previous)\s+(\d+)\s+years?|اخر\s+(\d+)\s+(?:سنه|سنوات|سنين)"), 365),
)
_ROLLING_WORDS = (
    (("past week", "past 7 days"), 7), (("past month", "past 30 days"), 30),
    (("past quarter", "last 3 months", "اخر ثلاث اشهر", "اخر 3 اشهر", "اخر تلات شهور"), 90),
    (("past year", "past 12 months", "last 12 months", "اخر سنه", "اخر 12 شهر"), 365),
)


def rolling_days(text: str) -> Optional[int]:
    for pattern, unit in _ROLLING:
        match = pattern.search(text)
        if match:
            number = next(group for group in match.groups() if group)
            return max(1, min(int(number) * unit, 1095))
    for phrases, days in _ROLLING_WORDS:
        if any(phrase in text for phrase in phrases):
            return days
    return None


# --- explicit dates --------------------------------------------------------------

_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
_SLASH_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(20\d{2})(?![\d/])")  # day/month/year, as written locally
_DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_ALTERNATION})(?:\s*,?\s*{_YEAR})?")
_MONTH_DAY = re.compile(rf"({_MONTH_ALTERNATION})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:\s*,?\s*{_YEAR})?")
_MONTH_YEAR = re.compile(rf"(?:(?:شهر|month(?:\s+of)?)\s+)?({_MONTH_ALTERNATION})(?:\s*(?:,|of|سنه|عام)?\s*{_YEAR})?")
_NUMERIC_MONTH = re.compile(r"(?:شهر|month)\s+(\d{1,2})(?!\d)(?:\s*(?:/|-|سنه|عام|of)?\s*" + _YEAR + ")?")
_QUARTER = re.compile(r"(?<![a-z])q([1-4])(?:\s*(?:of\s+)?" + _YEAR + r")?|"
                      r"(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+(?:of\s+)?" + _YEAR + r")?|"
                      r"الربع\s+(الاول|الثاني|الثالث|الرابع)(?:\s+(?:من\s+)?(?:سنه|عام)?\s*" + _YEAR + r")?")
_STANDALONE_YEAR = re.compile(_YEAR)


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_number(token: str) -> int:
    """The month a matched name means, attached preposition and all."""
    if token in _MONTH_BY_NAME:
        return _MONTH_BY_NAME[token]
    return _MONTH_BY_NAME[token[1:]]


def _mentions(text: str, today: date) -> List[Tuple[int, int, str, object]]:
    """(start, end, type, value) for every date, month, quarter and year named."""
    found: List[Tuple[int, int, str, object]] = []
    taken: List[Tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in taken)

    def add(start: int, end: int, kind: str, value) -> None:
        if value is not None and free(start, end):
            found.append((start, end, kind, value))
            taken.append((start, end))

    for match in _ISO_DATE.finditer(text):
        add(match.start(), match.end(), "day", _safe_date(int(match[1]), int(match[2]), int(match[3])))
    for match in _SLASH_DATE.finditer(text):
        add(match.start(), match.end(), "day", _safe_date(int(match[3]), int(match[2]), int(match[1])))
    for match in _DAY_MONTH.finditer(text):
        month = _month_number(match[2])
        year = int(match[3]) if match[3] else None
        add(match.start(), match.end(), "day_open", (year, month, int(match[1])))
    for match in _MONTH_DAY.finditer(text):
        if match[1] in _AMBIGUOUS:
            continue
        month = _month_number(match[1])
        year = int(match[3]) if match[3] else None
        add(match.start(), match.end(), "day_open", (year, month, int(match[2])))
    for match in _QUARTER.finditer(text):
        number = int(match[1]) if match[1] else _ORDINAL_QUARTER.get(match[3] or match[5])
        year = match[2] or match[4] or match[6]
        add(match.start(), match.end(), "quarter", (int(year) if year else None, number))
    for match in _NUMERIC_MONTH.finditer(text):
        month = int(match[1])
        if 1 <= month <= 12:
            add(match.start(), match.end(), "month", (int(match[2]) if match[2] else None, month))
    for match in _MONTH_YEAR.finditer(text):
        name = match[1] if match[1] in _MONTH_BY_NAME else match[1][1:]
        lead = text[max(0, match.start() - 10):match.start()]
        cued = (match.group(0).startswith(("شهر", "month")) or match[2]
                or re.search(r"(?<![a-z])(in|during|for|of|since|from|between|and|vs|versus|to)\s+$", lead))
        if name in _AMBIGUOUS and not cued:
            continue
        add(match.start(), match.end(), "month", (int(match[2]) if match[2] else None, _MONTH_BY_NAME[name]))
    if any(kind == "month" for _, _, kind, _ in found):
        # Next to another month, a short ambiguous name is a month too: "أيلول مقارنة بآب", "June vs May".
        for match in _MONTH_YEAR.finditer(text):
            name = match[1] if match[1] in _MONTH_BY_NAME else match[1][1:]
            lead = text[max(0, match.start() - 12):match.start()]
            compared = name != match[1] or re.search(r"(vs\.?|versus|and|or|with|than|مقارنه|مع|او)\s*$", lead)
            if name in _AMBIGUOUS and compared:
                add(match.start(), match.end(), "month", (int(match[2]) if match[2] else None, _MONTH_BY_NAME[name]))
    for match in _STANDALONE_YEAR.finditer(text):
        add(match.start(), match.end(), "year", int(match[1]))
    return sorted(found)


def _close(kind: str, value, today: date, year_hint: Optional[int] = None) -> Optional[dict]:
    if kind == "day":
        return _period(value, value + timedelta(days=1), value.isoformat(), "days")
    if kind == "day_open":
        year, month, day = value
        year = year or year_hint or _recent_year(month, today)
        day_date = _safe_date(year, month, day)
        return _period(day_date, day_date + timedelta(days=1), day_date.isoformat(), "days") if day_date else None
    if kind == "month":
        year, month = value
        return _month_period(year or year_hint or _recent_year(month, today), month, today)
    if kind == "quarter":
        year, number = value
        current = (today.month - 1) // 3 + 1
        if number is None:
            return None
        return _quarter_period(year or year_hint or (today.year if number <= current else today.year - 1), number, today)
    if kind == "year":
        return _year_period(value, today)
    return None


def resolve_periods(text: str, today: date) -> List[dict]:
    """Every period `text` (already normalised) names, in the order named:
    relative ones ("last month"), months, quarters, years, single days and
    "from X to Y" ranges. At most 4."""
    periods: List[Tuple[int, dict]] = []
    covered: List[Tuple[int, int]] = []
    for phrases, key in _RELATIVE:
        for phrase in phrases:
            for match in re.finditer(_word(phrase), text):
                if all(match.end() <= s or match.start() >= e for s, e in covered):
                    periods.append((match.start(), _relative(key, today)))
                    covered.append((match.start(), match.end()))
    mentions = [m for m in _mentions(text, today) if all(m[1] <= s or m[0] >= e for s, e in covered)]
    # A year stated once ("between 1 May and 15 June 2026", "March and April 2025") applies to the
    # month and day mentions around it that state none.
    stated_years = [m[3] for m in mentions if m[2] == "year"] + [
        m[3][0] for m in mentions if m[2] in ("day_open", "month", "quarter") and m[3][0]]
    year_hint = stated_years[0] if len(set(stated_years)) == 1 else None
    if year_hint and not any(m[2] in ("day_open", "month", "quarter") for m in mentions):
        year_hint = None
    i = 0
    while i < len(mentions):
        start, end, kind, value = mentions[i]
        # A range: "from 1 May to 15 June", "between May and July 2026", "من 1/5/2026 الى 15/6/2026".
        if i + 1 < len(mentions) and kind in ("day", "day_open", "month") and mentions[i + 1][2] in ("day", "day_open", "month"):
            between = text[end:mentions[i + 1][0]]
            if re.fullmatch(rf"\s*{_RANGE_JOINERS}\s*", between):
                first = _close(kind, value, today, year_hint)
                second = _close(mentions[i + 1][2], mentions[i + 1][3], today, year_hint)
                lead = text[max(0, start - 12):start]
                is_range = re.search(r"(between|from|بين|من)\s*$", lead) or between.strip() not in ("and", "و")
                if first and second and is_range and first["start"] < second["end"]:
                    periods.append((start, _period(date.fromisoformat(first["start"]), date.fromisoformat(second["end"]),
                                                   f"{first['start']} to "
                                                   f"{(date.fromisoformat(second['end']) - timedelta(days=1)).isoformat()}",
                                                   "days")))
                    i += 2
                    continue
        if kind == "year" and year_hint == value and any(m[2] in ("day_open", "month", "quarter") for m in mentions):
            i += 1  # the year qualifies the months around it, it isn't a period of its own
            continue
        period = _close(kind, value, today, year_hint)
        if period:
            periods.append((start, period))
        i += 1
    out, seen = [], set()
    for _, period in sorted(periods, key=lambda item: item[0]):
        key = (period["start"], period["end"])
        if key not in seen:
            seen.add(key)
            out.append(period)
    # A period that hasn't started yet can't have sales; forecasts are asked differently ("next month").
    return [p for p in out if date.fromisoformat(p["start"]) <= today][:4]


def year_earlier(period: dict) -> dict:
    """The same dates one year earlier ("the same period last year")."""
    def back(day: date) -> date:
        return day.replace(year=day.year - 1) if not (day.month == 2 and day.day == 29) else day.replace(
            year=day.year - 1, day=28)
    start, end = back(date.fromisoformat(period["start"])), back(date.fromisoformat(period["end"]))
    kind = period.get("kind")
    if kind in ("month", "quarter", "year"):
        label = period["label"].replace(str(date.fromisoformat(period["start"]).year), str(start.year))
    else:
        label = f"{start.isoformat()} to {(end - timedelta(days=1)).isoformat()}"
    return _period(start, end, label, kind if kind in ("month", "quarter", "year") else "days")


# Periods named relative to the one just discussed, in a follow-up ("and the month before?").
_BEFORE_THAT = re.compile(r"(?<![a-z])(the )?(month|quarter|year|week|period) before(?![a-z])|"
                          r"(?<![a-z])(previous|prior|preceding) (month|quarter|period)(?![a-z])|"
                          r"(الشهر|الربع|الفتره|السنه|الاسبوع) (اللي|الذي|التي) قبل(ه|ها)?|قبلها بشهر|"
                          r"(الشهر|الربع|الفتره) (السابق|الماضي) له")
_YEAR_EARLIER = re.compile(r"same (period|time|month|quarter) (last|the previous|a) year|a year (earlier|before)|"
                           r"year[- ]on[- ]year|نفس الفتره (من|في) (السنه|العام) (الماضي|الماضيه|السابقه)|"
                           r"نفس الشهر (من|في) (السنه|العام) (الماضي|الماضيه)|السنه اللي قبلها")


def relative_to(text: str, earlier: List[dict]) -> List[dict]:
    """The periods a follow-up names relative to `earlier` ones: the period before each, or a year earlier."""
    if not earlier:
        return []
    if _YEAR_EARLIER.search(text):
        return [year_earlier(p) for p in earlier]
    if _BEFORE_THAT.search(text):
        return [previous_period(p) for p in earlier]
    return []
