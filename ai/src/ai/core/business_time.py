"""The company's own calendar.

Tenant transactions run in the company's time zone (see
src/infrastructure/db_pool.py), so Postgres' CURRENT_DATE is the company's
local date. Python code that needs "today" asks the database rather than
assuming UTC; a test double that cannot answer falls back to the UTC date.
"""

from datetime import date, datetime, timezone


def business_today(conn) -> date:
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT CURRENT_DATE;")
            row = cursor.fetchone()
        value = row[0] if row else None
        if isinstance(value, date):
            return value
    except Exception:  # noqa: BLE001 - unit-test doubles
        pass
    return datetime.now(timezone.utc).date()


def window_start(conn, days: int, periods: int = 1, today: date = None) -> date:
    """First day of "the last N days" (periods=1) or of the N days before
    that (periods=2), as calendar days in the company's time zone, today
    included. Compared with a timestamptz column, Postgres reads the date as
    local midnight, so `issue_date >= window_start(...)` is exact."""
    from datetime import timedelta

    today = today or business_today(conn)
    return today - timedelta(days=periods * int(days) - 1)
