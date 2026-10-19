"""
Alerts: what needs the owner's attention now, derived from live data -
competitor price moves, newly found competitors, products about to run out,
prices far from the market, failed imports or syncs, and billing issues.
Nothing is stored except when each person last read their alerts.

Each alert carries a stable id, a kind and the facts to word it (the
screen words it in the interface language), a severity and a link.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from src.ai.dashboard import command_center

PRICE_MOVE_PCT = 3.0
PRICE_GAP_PCT = 10.0
RECENT_DAYS = 14


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _credit_alerts(conn, tenant_id: str, today) -> list:
    """Data or AI Credits past a warning threshold (billing_cost_policy, e.g.
    70/85/100%) this period. One alert per budget and threshold reached."""
    from src.ai.billing import credits

    try:
        budgets = credits.summary(conn, tenant_id)
    except Exception:  # noqa: BLE001 - alerts never fail over billing
        return []
    out = []
    for kind in (credits.DATA, credits.AI):
        budget = budgets[kind]
        if budget["warning"] is None:
            continue
        exhausted = budget["exhausted"]
        out.append({"id": _id("credits", kind, budget["period_start"], budget["warning"]),
                    "kind": "credits_exhausted" if exhausted else "credits_low",
                    "severity": "danger" if exhausted else "warning", "at": today.isoformat(), "link": "/billing",
                    "params": {"budget": kind, "percent": round(budget["percent_used"] or 0), "resets_on": budget["resets_on"]}})
    return out


def build_alerts(conn, tenant_id: str, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = now - timedelta(days=RECENT_DAYS)
    alerts = []
    cc = command_center.get_command_center(conn, tenant_id)

    for move in cc["competitor_moves"]:
        if move.get("change_pct") is None or abs(move["change_pct"]) < PRICE_MOVE_PCT:
            continue
        alerts.append({"id": _id("price", move["competitor_id"], move["product_id"], move["observed_at"]),
                       "kind": "competitor_price", "severity": "warning" if move["change_pct"] < 0 else "info",
                       "at": move["observed_at"], "link": f"/market/competitors/{move['competitor_id']}",
                       "params": {k: move[k] for k in ("competitor", "product", "price", "previous_price", "change_pct", "currency")}})
    # Prices on a competitor's own menu / site / posts that moved and are not one of your products' matches.
    try:
        from src.ai.market_inputs import price_history

        for change in price_history.alert_changes(conn, tenant_id, RECENT_DAYS, PRICE_MOVE_PCT, now=now):
            alerts.append({"id": _id("item", change["competitor_id"], change["item_key"], change["changed_at"]),
                           "kind": "competitor_item_price", "severity": "warning" if change["direction"] == "down" else "info",
                           "at": change["changed_at"], "link": f"/market/competitors/{change['competitor_id']}",
                           "params": {"competitor": change["competitor"], "product": change["item"], "price": change["new_price"],
                                      "previous_price": change["old_price"], "change_pct": change["change_pct"], "currency": change["currency"]}})
    except Exception:  # noqa: BLE001 - alerts never fail over one source
        conn.rollback()
    for item in cc["restock"]:
        if item.get("priority") != "high":
            continue
        alerts.append({"id": _id("restock", item["product_id"], today.date()), "kind": "restock", "severity": "danger",
                       "at": today.isoformat(), "link": f"/products/{item['product_id']}",
                       "params": {"product": item["name"], "days": item.get("days_of_cover"), "quantity": item.get("suggested_qty")}})
    for gap in cc["price_opportunities"]:
        if abs(gap["gap_pct"]) < PRICE_GAP_PCT:
            continue
        alerts.append({"id": _id("gap", gap["product_id"], today.date()), "kind": "price_gap", "severity": "warning",
                       "at": today.isoformat(), "link": f"/products/{gap['product_id']}",
                       "params": {"product": gap["name"], "gap_pct": gap["gap_pct"], "competitor": gap["cheapest_competitor"]}})

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*), MAX(first_seen_at), COUNT(*) FILTER (WHERE is_tracked)
            FROM tenant_competitors
            WHERE tenant_id = %s AND discovery_method IS NOT NULL AND first_seen_at >= %s;
            """,
            (tenant_id, since),
        )
        found, latest, tracked = cursor.fetchone()
        if found:
            alerts.append({"id": _id("found", latest), "kind": "new_competitors", "severity": "info", "at": _iso(latest),
                           "link": "/market", "params": {"count": found, "tracked": tracked}})

        cursor.execute(
            """
            SELECT job_id, file_name, ended_at FROM ingestion_jobs
            WHERE tenant_id = %s AND job_status = 'FAILED' AND COALESCE(ended_at, created_at) >= %s
            ORDER BY created_at DESC LIMIT 5;
            """,
            (tenant_id, since),
        )
        for job_id, file_name, ended_at in cursor.fetchall():
            alerts.append({"id": _id("job", job_id), "kind": "import_failed", "severity": "danger", "at": _iso(ended_at or now),
                           "link": "/connect-data", "params": {"name": file_name}})

        cursor.execute("SELECT ends_at FROM billing_trials WHERE tenant_id = %s;", (tenant_id,))
        trial = cursor.fetchone()
        cursor.execute(
            "SELECT status FROM billing_subscriptions WHERE tenant_id = %s ORDER BY updated_at DESC NULLS LAST LIMIT 1;",
            (tenant_id,),
        )
        subscription = cursor.fetchone()
    if subscription and subscription[0] in ("past_due", "payment_failed"):
        alerts.append({"id": _id("billing", subscription[0], today.date()), "kind": "payment_failed", "severity": "danger",
                       "at": today.isoformat(), "link": "/billing", "params": {}})
    elif trial and trial[0] and not subscription and now <= trial[0] <= now + timedelta(days=3):
        alerts.append({"id": _id("trial", trial[0]), "kind": "trial_ending", "severity": "warning", "at": _iso(trial[0] - timedelta(days=3)),
                       "link": "/billing", "params": {"days": max(0, (trial[0] - now).days)}})
    alerts.extend(_credit_alerts(conn, tenant_id, today))

    order = {"danger": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (a["at"] or ""), reverse=True)
    alerts.sort(key=lambda a: order[a["severity"]])
    return alerts[:30]


def last_read(conn, tenant_id: str, user_id: str):
    with conn.cursor() as cursor:
        cursor.execute("SELECT last_read_at FROM notification_reads WHERE tenant_id = %s AND user_id = %s;", (tenant_id, user_id))
        row = cursor.fetchone()
    return row[0] if row else None


def mark_read(conn, tenant_id: str, user_id: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO notification_reads (tenant_id, user_id, last_read_at) VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET last_read_at = CURRENT_TIMESTAMP;
            """,
            (tenant_id, user_id),
        )
