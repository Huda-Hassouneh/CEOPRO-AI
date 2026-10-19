"""
Marketing ideas grounded in what is actually known:

1. The calendar - upcoming occasions in the company's country (religious
   holidays use their published expected dates, which can shift by a day
   with the moon sighting; that caveat is returned with them).
2. The product's own history - how it sold during past occasions compared
   with its normal pace, from the company's invoices.
3. Its current signals - forecast trend, stock cover and price position.

Live social-media or search-trend data is not connected, and the response
says so (`external_trends.available = false`) rather than inventing trends.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from src.ai.core.business_time import business_today

# Expected (published) dates. Islamic dates follow moon sighting and can move
# by about a day.
RAMADAN = {2025: (date(2025, 3, 1), date(2025, 3, 29)), 2026: (date(2026, 2, 18), date(2026, 3, 19)),
           2027: (date(2027, 2, 8), date(2027, 3, 9)), 2028: (date(2028, 1, 28), date(2028, 2, 26))}
EID_AL_FITR = {2025: date(2025, 3, 30), 2026: date(2026, 3, 20), 2027: date(2027, 3, 10), 2028: date(2028, 2, 27)}
EID_AL_ADHA = {2025: date(2025, 6, 6), 2026: date(2026, 5, 27), 2027: date(2027, 5, 16), 2028: date(2028, 5, 5)}
NATIONAL_DAY = {"JO": (5, 25), "AE": (12, 2), "SA": (9, 23), "MA": (7, 30), "EG": (7, 23), "FR": (7, 14),
                "KW": (2, 25), "QA": (12, 18), "BH": (12, 16), "OM": (11, 18), "LB": (11, 22), "TN": (3, 20)}
ARAB_MOTHERS_DAY = {"JO", "AE", "SA", "EG", "KW", "QA", "BH", "OM", "LB", "SY", "IQ", "PS"}
OLIVE_HARVEST = {"JO", "PS", "LB", "SY", "TN", "MA"}

LOOKAHEAD_DAYS = 90
# Recommended creative direction per occasion (KEEL theme / strategy keys).
OCCASION_STYLE = {
    "ramadan": ("SEASONAL", "STORYTELLING"), "eid_fitr": ("SEASONAL", "SALES_DRIVEN"),
    "eid_adha": ("SEASONAL", "SALES_DRIVEN"), "national_day": ("BOLD_PROMOTIONAL", "BRAND_AWARENESS"),
    "mothers_day": ("LIFESTYLE", "STORYTELLING"), "black_friday": ("BOLD_PROMOTIONAL", "URGENCY"),
    "back_to_school": ("LIFESTYLE", "SALES_DRIVEN"), "summer": ("LIFESTYLE", "SALES_DRIVEN"),
    "winter": ("LIFESTYLE", "STORYTELLING"), "olive_harvest": ("SEASONAL", "STORYTELLING"),
    "new_year": ("BOLD_PROMOTIONAL", "BRAND_AWARENESS"), "valentines": ("LUXURY_PREMIUM", "STORYTELLING"),
}


def _black_friday(year: int) -> date:
    november_first = date(year, 11, 1)
    first_thursday = november_first + timedelta(days=(3 - november_first.weekday()) % 7)
    return first_thursday + timedelta(days=22)


def occasions_between(country: Optional[str], start: date, end: date) -> list:
    """(key, first_day, last_day, moon_dependent) overlapping [start, end]."""
    found = []
    for year in range(start.year - 1, end.year + 1):
        windows = []
        if year in RAMADAN:
            windows.append(("ramadan", *RAMADAN[year], True))
        if year in EID_AL_FITR:
            windows.append(("eid_fitr", EID_AL_FITR[year], EID_AL_FITR[year] + timedelta(days=2), True))
        if year in EID_AL_ADHA:
            windows.append(("eid_adha", EID_AL_ADHA[year], EID_AL_ADHA[year] + timedelta(days=3), True))
        if country in NATIONAL_DAY:
            month, day = NATIONAL_DAY[country]
            windows.append(("national_day", date(year, month, day), date(year, month, day), False))
        if country in ARAB_MOTHERS_DAY:
            windows.append(("mothers_day", date(year, 3, 21), date(year, 3, 21), False))
        if country in OLIVE_HARVEST:
            windows.append(("olive_harvest", date(year, 10, 15), date(year, 11, 30), False))
        windows += [
            ("black_friday", _black_friday(year), _black_friday(year) + timedelta(days=3), False),
            ("back_to_school", date(year, 8, 20), date(year, 9, 15), False),
            ("summer", date(year, 6, 15), date(year, 8, 31), False),
            ("winter", date(year, 12, 1), date(year + 1, 2, 28), False),
            ("new_year", date(year, 12, 28), date(year + 1, 1, 1), False),
            ("valentines", date(year, 2, 14), date(year, 2, 14), False),
        ]
        for key, first, last, moon in windows:
            if last >= start and first <= end:
                found.append((key, first, last, moon))
    return sorted(set(found), key=lambda w: w[1])


def _product_lift(conn, tenant_id: str, product_id: str, country: Optional[str], today: date) -> dict:
    """Average units per day during each past occasion vs the product's
    average over the whole year before today. Only occasions the product
    actually sold through are reported."""
    start = today - timedelta(days=550)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.issue_date::date, SUM(ii.quantity)
            FROM invoice_items ii JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %s AND ii.product_id = %s AND i.issue_date >= %s
            GROUP BY 1;
            """,
            (tenant_id, product_id, start),
        )
        daily = {d: float(units) for d, units in cursor.fetchall()}
    if not daily:
        return {}
    first_sale = min(daily)
    total_days = max((today - first_sale).days, 1)
    baseline = sum(daily.values()) / total_days
    if baseline <= 0:
        return {}
    lifts = {}
    for key, first, last, _moon in occasions_between(country, first_sale, today - timedelta(days=1)):
        first, last = max(first, first_sale), min(last, today - timedelta(days=1))
        days = (last - first).days + 1
        if days < 1 or key in ("summer", "winter") and days < 14:
            continue
        units = sum(daily.get(first + timedelta(days=n), 0.0) for n in range(days))
        lift = (units / days) / baseline
        previous = lifts.get(key)
        if previous is None or first > previous["from"]:
            lifts[key] = {"lift": round(lift, 2), "from": first, "to": last}
    return {k: {**v, "from": v["from"].isoformat(), "to": v["to"].isoformat()} for k, v in lifts.items()}


def build_suggestions(conn, tenant_id: str, product_id: Optional[str] = None, today: Optional[date] = None) -> dict:
    today = today or business_today(conn)
    with conn.cursor() as cursor:
        cursor.execute("SELECT country_code FROM companies WHERE tenant_id = %s;", (tenant_id,))
        row = cursor.fetchone()
    country = row[0] if row else None

    lifts = _product_lift(conn, tenant_id, product_id, country, today) if product_id else {}
    upcoming = []
    for key, first, last, moon in occasions_between(country, today, today + timedelta(days=LOOKAHEAD_DAYS)):
        theme, strategy = OCCASION_STYLE.get(key, ("SEASONAL", "SALES_DRIVEN"))
        lift = lifts.get(key)
        upcoming.append({
            "key": key, "starts": first.isoformat(), "ends": last.isoformat(),
            "days_away": max(0, (first - today).days), "ongoing": first <= today <= last,
            "date_may_shift": moon, "theme": theme, "strategy": strategy,
            "product_lift": lift["lift"] if lift else None,
        })
    # Occasions this product sold unusually well (or badly) in, ranked first.
    upcoming.sort(key=lambda o: (-(o["product_lift"] or 0) if (o["product_lift"] or 0) >= 1.2 else 0, o["days_away"]))

    signals = []
    if product_id:
        from src.ai.forecasting import overview as forecast_overview

        demand = forecast_overview.build_overview(conn, tenant_id, product_id, today=today)
        row = next((p for p in demand["products"] if p["product_id"] == product_id), None)
        if row:
            if row["trend"] == "increasing" and row["forecast_next_30"]:
                signals.append({"kind": "rising_demand", "pct": row["trend_change_pct"], "theme": "SOCIAL_TRENDY", "strategy": "SALES_DRIVEN"})
            if row["stock_action"] == "reduce":
                signals.append({"kind": "overstock", "days": row["stock_days_of_cover"], "theme": "BOLD_PROMOTIONAL", "strategy": "URGENCY"})
            if row["stock_action"] == "restock" and row["stock_priority"] == "high":
                signals.append({"kind": "low_stock", "days": row["stock_days_of_cover"], "theme": None, "strategy": None})
            if row["trend"] == "decreasing":
                signals.append({"kind": "falling_demand", "pct": row["trend_change_pct"], "theme": "LIFESTYLE", "strategy": "STORYTELLING"})
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.current_price, AVG(latest.scraped_price)
                FROM products p
                JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id AND cpm.is_active
                JOIN LATERAL (SELECT scraped_price, currency FROM competitor_prices cp WHERE cp.tenant_id = cpm.tenant_id AND cp.mapping_id = cpm.mapping_id ORDER BY observed_at DESC LIMIT 1) latest ON latest.currency = p.currency
                WHERE p.tenant_id = %s AND p.product_id = %s GROUP BY p.current_price;
                """,
                (tenant_id, product_id),
            )
            price_row = cursor.fetchone()
        if price_row and price_row[1]:
            gap = (float(price_row[0]) - float(price_row[1])) / float(price_row[1]) * 100
            if gap <= -5:
                signals.append({"kind": "priced_below_market", "pct": round(gap, 1), "theme": "BOLD_PROMOTIONAL", "strategy": "SALES_DRIVEN"})
            elif gap >= 5:
                signals.append({"kind": "priced_above_market", "pct": round(gap, 1), "theme": "LUXURY_PREMIUM", "strategy": "BRAND_AWARENESS"})

    # Occasions this product historically sold much better in, with when
    # each comes next - even when that's more than LOOKAHEAD_DAYS away
    # (dates in Ramadan), so it can be planned early.
    highlights = []
    later = occasions_between(country, today, today + timedelta(days=400))
    for key, past in lifts.items():
        # One-day occasions are too noisy to call a pattern.
        if past["lift"] < 1.3 or (date.fromisoformat(past["to"]) - date.fromisoformat(past["from"])).days < 2:
            continue
        nxt = next((w for w in later if w[0] == key and w[2] >= today), None)
        highlights.append({"key": key, "lift": past["lift"], "last_from": past["from"], "last_to": past["to"],
                           "next_starts": nxt[1].isoformat() if nxt else None,
                           "days_away": max(0, (nxt[1] - today).days) if nxt else None})
    highlights.sort(key=lambda h: -h["lift"])

    return {
        "as_of": today.isoformat(),
        "country": country,
        "occasions": upcoming[:6],
        "sales_highlights": highlights[:3],
        "product_signals": signals,
        "external_trends": {"available": False},
    }
