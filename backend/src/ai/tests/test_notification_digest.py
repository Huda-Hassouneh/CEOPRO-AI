"""Alert preferences and the email summary (notification_prefs.py, notification_digest.py)."""
from datetime import datetime, timezone
from unittest.mock import patch

from src.ai import notification_digest as digest
from src.ai import notification_prefs as prefs

NOW = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)   # a Monday, 12:30 in Amman


def test_every_alert_kind_belongs_to_a_group():
    kinds = {"competitor_price", "restock", "price_gap", "new_competitors", "import_failed", "payment_failed", "trial_ending",
             "credits_low", "credits_exhausted", "competitor_comments_negative"}
    assert kinds == set(prefs.GROUP_OF_KIND)


def test_wanted_filters_by_group_per_channel():
    alerts = [{"kind": "restock"}, {"kind": "price_gap"}, {"kind": "payment_failed"}]
    p = prefs.apply_patch({}, {"in_app": {"pricing": False}, "email": {"stock": False, "billing": False}})
    assert [a["kind"] for a in prefs.wanted(alerts, p, "in_app")] == ["restock", "payment_failed"]
    assert [a["kind"] for a in prefs.wanted(alerts, p, "email")] == ["price_gap"]


def test_period_start_daily_and_weekly_in_company_time():
    # 07:00 Amman (UTC+3) = 04:00 UTC.
    assert digest.period_start("daily", NOW, "Asia/Amman") == datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    early = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)   # 05:00 in Amman - before today's send time
    assert digest.period_start("daily", early, "Asia/Amman") == datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
    friday = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    assert digest.period_start("weekly", friday, "Asia/Amman") == datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    assert digest.period_start("daily", NOW, "Not/AZone").tzinfo is not None


def test_summary_is_worded_in_the_users_language_with_links():
    alerts = [
        {"kind": "competitor_price", "link": "/market/competitors/c1",
         "params": {"competitor": "Rival", "product": "Dates 1kg", "price": 7.5, "previous_price": 8, "change_pct": -6.25, "currency": "JOD"}},
        {"kind": "restock", "link": "/products/p1", "params": {"product": "Freekeh", "days": 3.4, "quantity": 12.0}},
    ]
    subject, body = digest.compose(alerts, "en", "Zaytouna", "https://app.example")
    assert subject == "KEEL: 2 new for Zaytouna"
    assert "Rival cut Dates 1kg by 6.2% to 7.5 JOD" in body
    assert "Freekeh runs out in about 3 days - reorder about 12" in body
    assert "https://app.example/products/p1" in body and "https://app.example/settings?tab=notifications" in body
    subject_ar, body_ar = digest.compose(alerts, "ar", "زيتونة", "https://app.example")
    assert "خفّض Rival سعر Dates 1kg" in body_ar and "زيتونة" in subject_ar


class _Conn:
    """Stands in for both connections; records SQL and answers the claim."""
    def __init__(self, rows=None, claim=True):
        self.rows, self.claim, self.sql, self.closed = rows or [], claim, [], False

    def cursor(self):
        conn = self

        class C:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params=None): conn.sql.append(sql); self._sql = sql
            def fetchall(self): return conn.rows
            def fetchone(self): return (1,) if conn.claim and "RETURNING" in self._sql else None
        return C()

    def commit(self): pass
    def rollback(self): pass
    def close(self): self.closed = True


def _row(frequency="daily", last_sent=None, lang="en", email_prefs=None):
    p = {"email_frequency": frequency, "email": email_prefs or {}}
    return ("t1", "u1", "owner@example.com", lang, p, "Zaytouna", "Asia/Amman", last_sent)


ALERTS = [{"kind": "restock", "at": "2026-10-12T00:00:00+00:00", "link": "/products/p1", "params": {"product": "Freekeh", "days": 3, "quantity": 5}},
          {"kind": "payment_failed", "at": "2026-10-12T00:00:00+00:00", "link": "/billing", "params": {}}]


def _run(row, claim=True, alerts=ALERTS, send=None):
    sent = []
    tenant = _Conn(claim=claim)
    with patch("src.ai.notification_digest.alerts_module.build_alerts", return_value=[dict(a) for a in alerts]):
        result = digest.send_due(now=NOW, system_connection=lambda: _Conn(rows=[row]), tenant_connection=lambda t, u: tenant,
                                 send=send or (lambda to, subject, body: sent.append((to, subject, body))))
    return result, sent, tenant


def test_a_due_summary_is_claimed_then_sent_with_only_the_chosen_groups():
    result, sent, tenant = _run(_row(email_prefs={"billing": False}))
    assert result["sent"] == 1 and len(sent) == 1
    to, subject, body = sent[0]
    assert to == "owner@example.com" and "Freekeh" in body and "payment" not in body
    assert any("INSERT INTO notification_digests" in sql for sql in tenant.sql)


def test_already_sent_this_period_is_skipped():
    result, sent, _ = _run(_row(last_sent=datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)))
    assert result["due"] == 0 and sent == []


def test_another_instance_holding_the_claim_means_no_second_email():
    result, sent, _ = _run(_row(), claim=False)
    assert sent == [] and result["sent"] == 0


def test_nothing_new_sends_nothing():
    result, sent, _ = _run(_row(last_sent=datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)))
    assert sent == [] and result["nothing_new"] == 1


def test_a_failed_send_releases_the_claim_for_a_retry():
    def boom(*args):
        raise OSError("smtp down")
    result, _, tenant = _run(_row(), send=boom)
    assert result["failed"] == 1
    assert any(sql.startswith("DELETE FROM notification_digests") for sql in tenant.sql)
