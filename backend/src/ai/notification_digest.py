"""
Email summaries of alerts (Settings -> Notifications -> Email summary).

People who chose a daily or weekly summary get one email per company listing
the alerts (src/ai/alerts.py) that are new since their last summary, in the
groups they picked, in their own language. Sent at 07:00 company time - every
day, or on Mondays for weekly - and only when there is something new. Only to
verified email addresses.

Runs as a daemon thread in the API process, like the discovery refresh. Each
summary is claimed in notification_digests before it is sent, so several API
instances never send it twice; a failed send releases the claim to retry on
the next pass. NOTIFICATION_DIGEST_ENABLED=false turns it off.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from src.ai import alerts as alerts_module
from src.ai import db, notification_prefs
from src.ai.core import notifications

logger = logging.getLogger("KEEL_NOTIFICATION_DIGEST")

SEND_HOUR = int(os.getenv("NOTIFICATION_DIGEST_HOUR", "7"))
CHECK_SECONDS = int(os.getenv("NOTIFICATION_DIGEST_CHECK_SECONDS", "900"))
FIRST_DELAY_SECONDS = int(os.getenv("NOTIFICATION_DIGEST_FIRST_DELAY_SECONDS", "60"))
MAX_ITEMS = 15

_started = False
_lock = threading.Lock()

# Same wording as the bell in the app (frontend locales, "alerts.*").
_TEXT = {
    "en": {
        "competitor_price_down": "{competitor} cut {product} by {pct}% to {price}",
        "competitor_price_up": "{competitor} raised {product} by {pct}% to {price}",
        "restock": "{product} runs out in about {days} days - reorder about {quantity}",
        "price_gap_above": "{product} is {pct}% above the market (cheapest: {competitor})",
        "price_gap_below": "{product} is {pct}% below the market - room to raise it",
        "competitor_comments_negative": "Customers are unhappy with {competitor}: {negative_pct}% of its last {count} comments are negative - a chance to stand out",
        "new_competitors": "The market scan found {count} new competitors ({tracked} now tracked)",
        "import_failed": "An import failed: {name}",
        "trial_ending": "Your trial ends in {days} days - choose a plan to keep access",
        "payment_failed": "Your last payment failed - update your payment method in Billing",
        "credits_low": "You've used {percent}% of this period's {budget} - they renew on {resets_on}",
        "credits_exhausted": "This period's {budget} are used up - they renew on {resets_on}; upgrade in Billing for more",
        "budget_data": "Data Credits",
        "budget_ai": "AI Credits",
        "subject": "KEEL: {count} new for {company}",
        "intro": "Here is what needs your attention at {company}:",
        "open": "Open",
        "footer": "You chose to receive this summary. Change it here: {url}",
    },
    "ar": {
        "competitor_price_down": "خفّض {competitor} سعر {product} بنسبة {pct}٪ إلى {price}",
        "competitor_price_up": "رفع {competitor} سعر {product} بنسبة {pct}٪ إلى {price}",
        "restock": "سينفد {product} خلال {days} يومًا تقريبًا - أعد طلب نحو {quantity}",
        "price_gap_above": "سعر {product} أعلى من السوق بنسبة {pct}٪ (الأرخص: {competitor})",
        "price_gap_below": "سعر {product} أقل من السوق بنسبة {pct}٪ - يمكنك رفعه",
        "competitor_comments_negative": "العملاء غير راضين عن {competitor}: {negative_pct}% من آخر {count} تعليقًا سلبية - فرصة للتميّز",
        "new_competitors": "وجد مسح السوق {count} منافسين جدد ({tracked} قيد المتابعة الآن)",
        "import_failed": "فشل استيراد: {name}",
        "trial_ending": "تنتهي فترتك التجريبية خلال {days} أيام - اختر خطة للاستمرار",
        "payment_failed": "فشلت آخر عملية دفع - حدّث وسيلة الدفع من الفوترة",
        "credits_low": "استخدمت {percent}٪ من {budget} لهذه الفترة - تتجدد في {resets_on}",
        "credits_exhausted": "نفدت {budget} لهذه الفترة - تتجدد في {resets_on}؛ يمكنك الترقية من الفوترة",
        "budget_data": "أرصدة البيانات",
        "budget_ai": "أرصدة الذكاء الاصطناعي",
        "subject": "KEEL: {count} جديد في {company}",
        "intro": "إليك ما يحتاج انتباهك في {company}:",
        "open": "افتح",
        "footer": "اخترت تلقّي هذا الملخص. يمكنك تغييره من هنا: {url}",
    },
}


def _num(value, digits=1) -> str:
    if value is None:
        return "?"
    value = round(float(value), digits)
    return f"{value:g}" if digits else str(int(value))


def alert_line(alert: dict, lang: str) -> str:
    text = _TEXT.get(lang, _TEXT["en"])
    p = alert.get("params") or {}
    kind = alert["kind"]
    if kind == "competitor_price":
        key = "competitor_price_down" if (p.get("change_pct") or 0) < 0 else "competitor_price_up"
        price = f"{_num(p.get('price'), 2)} {p.get('currency') or ''}".strip()
        return text[key].format(competitor=p.get("competitor"), product=p.get("product"), pct=_num(abs(p.get("change_pct") or 0)), price=price)
    if kind == "price_gap":
        key = "price_gap_above" if (p.get("gap_pct") or 0) > 0 else "price_gap_below"
        return text[key].format(product=p.get("product"), pct=_num(abs(p.get("gap_pct") or 0)), competitor=p.get("competitor"))
    if kind == "restock":
        return text["restock"].format(product=p.get("product"), days=_num(p.get("days"), 0), quantity=_num(p.get("quantity"), 1))
    if kind in ("credits_low", "credits_exhausted"):
        budget = text["budget_ai" if p.get("budget") == "ai" else "budget_data"]
        return text[kind].format(budget=budget, percent=_num(p.get("percent"), 0), resets_on=p.get("resets_on") or "?")
    if kind in ("new_competitors", "import_failed", "trial_ending", "payment_failed", "competitor_comments_negative"):
        return text[kind].format(**{k: (v if v is not None else "?") for k, v in p.items()})
    return kind


def compose(alerts: list, lang: str, company: str, base_url: str) -> "tuple[str, str]":
    text = _TEXT.get(lang, _TEXT["en"])
    lines = [text["intro"].format(company=company), ""]
    for alert in alerts[:MAX_ITEMS]:
        lines.append(f"- {alert_line(alert, lang)}")
        lines.append(f"  {text['open']}: {base_url}{alert['link']}")
    lines += ["", text["footer"].format(url=f"{base_url}/settings?tab=notifications")]
    return text["subject"].format(count=len(alerts), company=company), "\n".join(lines)


def period_start(frequency: str, now: datetime, tz_name: str) -> datetime:
    """Start of the current summary period: today's (daily) or this week's
    Monday (weekly) SEND_HOUR in the company's time zone."""
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001 - unknown zone names fall back to UTC
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    start = local.replace(hour=SEND_HOUR, minute=0, second=0, microsecond=0)
    if frequency == "weekly":
        start -= timedelta(days=local.weekday())
        if start > local:
            start -= timedelta(days=7)
    elif start > local:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


def candidates(system_conn) -> list:
    """(tenant, user, email, language, preferences, company, timezone, last_sent) for
    everyone who chose an email summary, with a verified address, in an active company."""
    with system_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT tu.tenant_id, u.user_id, u.email, u.preferred_language, u.notification_preferences,
                   c.business_name, c.timezone, d.last_sent_at
            FROM tenant_users tu
            JOIN users u ON u.user_id = tu.user_id
            JOIN companies c ON c.tenant_id = tu.tenant_id
            LEFT JOIN notification_digests d ON d.tenant_id = tu.tenant_id AND d.user_id = tu.user_id
            WHERE tu.removed_at IS NULL AND c.deleted_at IS NULL
              AND u.email_verified_at IS NOT NULL
              AND u.notification_preferences->>'email_frequency' IN ('daily', 'weekly');
            """
        )
        return cursor.fetchall()


def _claim(conn, tenant_id, user_id, now, start) -> bool:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO notification_digests (tenant_id, user_id, last_sent_at) VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET last_sent_at = EXCLUDED.last_sent_at
            WHERE notification_digests.last_sent_at < %s
            RETURNING 1;
            """,
            (tenant_id, user_id, now, start),
        )
        return cursor.fetchone() is not None


def _release(conn, tenant_id, user_id, previous) -> None:
    with conn.cursor() as cursor:
        if previous is None:
            cursor.execute("DELETE FROM notification_digests WHERE tenant_id = %s AND user_id = %s;", (tenant_id, user_id))
        else:
            cursor.execute("UPDATE notification_digests SET last_sent_at = %s WHERE tenant_id = %s AND user_id = %s;",
                           (previous, tenant_id, user_id))


def _as_datetime(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def send_due(now: Optional[datetime] = None, system_connection=None, tenant_connection=None, send=None) -> dict:
    """One pass over everyone whose summary is due. Connections and the sender are injectable for tests."""
    now = now or datetime.now(timezone.utc)
    system_connection = system_connection or db.system_connection
    tenant_connection = tenant_connection or db.dedicated_tenant_connection
    send = send or notifications.send_email
    base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    conn = system_connection()
    try:
        rows = candidates(conn)
    finally:
        conn.close()
    result = {"due": 0, "sent": 0, "nothing_new": 0, "failed": 0}
    for tenant_id, user_id, email, language, raw_prefs, company, tz_name, last_sent in rows:
        prefs = notification_prefs.normalize(raw_prefs)
        start = period_start(prefs["email_frequency"], now, tz_name)
        if last_sent is not None and last_sent >= start:
            continue
        result["due"] += 1
        conn = tenant_connection(str(tenant_id), str(user_id))
        try:
            if not _claim(conn, str(tenant_id), str(user_id), now, start):
                conn.rollback()
                continue
            conn.commit()
            since = last_sent or now - timedelta(days=7 if prefs["email_frequency"] == "weekly" else 1)
            items = [a for a in notification_prefs.wanted(alerts_module.build_alerts(conn, str(tenant_id), now=now), prefs, "email")
                     if (_as_datetime(a.get("at")) or now) > since]
            conn.commit()
            if not items:
                # The claim is only a concurrency fence while we build/send
                # the digest. No email was delivered, so do not consume this
                # period: alerts created later must still be eligible.
                _release(conn, str(tenant_id), str(user_id), last_sent)
                conn.commit()
                result["nothing_new"] += 1
                continue
            subject, body = compose(items, language if language in _TEXT else "en", company, base_url)
            try:
                delivered = send(email, subject, body)
                if delivered is False:
                    # The configured sender explicitly reports that no send
                    # was attempted (for example SMTP is not configured).
                    # Release the claim so a later pass can retry, and never
                    # report this as delivered.
                    _release(conn, str(tenant_id), str(user_id), last_sent)
                    conn.commit()
                    result["failed"] += 1
                else:
                    result["sent"] += 1
            except Exception:  # noqa: BLE001 - release the claim so the next pass retries
                logger.exception("sending an alert summary failed")
                _release(conn, str(tenant_id), str(user_id), last_sent)
                conn.commit()
                result["failed"] += 1
        except Exception:  # noqa: BLE001 - one person's failure never stops the others
            conn.rollback()
            logger.exception("building an alert summary failed")
            result["failed"] += 1
        finally:
            conn.close()
    return result


def _loop() -> None:
    time.sleep(FIRST_DELAY_SECONDS)
    while True:
        try:
            outcome = send_due()
            if outcome["due"]:
                logger.info("alert summaries: %s", outcome)
        except Exception:  # noqa: BLE001 - e.g. database briefly unreachable; try next pass
            logger.exception("alert summary pass failed")
        time.sleep(CHECK_SECONDS)


def start_background() -> bool:
    """Starts the summary thread once per process, unless disabled."""
    global _started
    if os.getenv("NOTIFICATION_DIGEST_ENABLED", "true").lower() in ("0", "false", "no"):
        return False
    with _lock:
        if _started:
            return False
        threading.Thread(target=_loop, name="alert-summaries", daemon=True).start()
        _started = True
    return True
