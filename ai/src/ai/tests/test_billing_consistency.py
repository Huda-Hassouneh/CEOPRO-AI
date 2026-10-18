"""The Billing page (frontend) and the billing API agree on which plan terms
customers see and what they are called, and the Arabic and English screens
name every alert kind the backend can raise."""
import json
import re
from pathlib import Path

from src.ai import notification_prefs
from src.ai.routers import billing

FRONTEND = Path(__file__).resolve().parents[4] / "frontend" / "src"


def _frontend_limit_keys() -> dict:
    source = (FRONTEND / "features" / "billing" / "api" / "billingApi.js").read_text(encoding="utf-8")
    block = re.search(r"export const LIMIT_KEYS = Object\.freeze\(\{(.*?)\}\);", source, re.S).group(1)
    return {code: key for code, key in re.findall(r"(\w+): \['(\w+)'", block)}


def test_frontend_and_backend_show_the_same_plan_terms():
    backend = {code: key for code, (key, _factor) in billing._PAGE_KEYS.items()}
    assert _frontend_limit_keys() == backend


def test_every_shown_term_and_alert_has_both_languages():
    for locale in ("en", "ar"):
        strings = json.loads((FRONTEND / "assets" / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        labels = strings["billing"]["management"]["usageLabels"]
        assert {key for key, _ in billing._PAGE_KEYS.values()} <= set(labels), locale
        alerts = strings["alerts"]
        assert set(notification_prefs.GROUP_OF_KIND) <= set(alerts), locale
