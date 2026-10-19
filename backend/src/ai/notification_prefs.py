"""
What each person wants to hear about, stored in users.notification_preferences:

    {"in_app": {group: bool}, "email": {group: bool}, "email_frequency": "off"|"daily"|"weekly"}

Groups bundle the alert kinds from src/ai/alerts.py. Everything shows in the
app by default; the email summary is opt-in (frequency "off").
"""
from typing import Optional

GROUPS = {
    "stock": ("restock",),
    "pricing": ("competitor_price", "price_gap"),
    "market": ("new_competitors", "competitor_comments_negative"),
    "data": ("import_failed",),
    "billing": ("payment_failed", "trial_ending", "credits_low", "credits_exhausted"),
}
GROUP_OF_KIND = {kind: group for group, kinds in GROUPS.items() for kind in kinds}
FREQUENCIES = ("off", "daily", "weekly")


def normalize(raw: Optional[dict]) -> dict:
    """Stored preferences with defaults filled in; unknown or malformed values ignored."""
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for channel in ("in_app", "email"):
        given = raw.get(channel) if isinstance(raw.get(channel), dict) else {}
        result[channel] = {group: given[group] if isinstance(given.get(group), bool) else True for group in GROUPS}
    frequency = raw.get("email_frequency")
    result["email_frequency"] = frequency if frequency in FREQUENCIES else "off"
    return result


def apply_patch(current: Optional[dict], patch: dict) -> dict:
    """New preferences after a change; raises ValueError naming anything invalid."""
    if not isinstance(patch, dict):
        raise ValueError("Expected an object.")
    unknown = set(patch) - {"in_app", "email", "email_frequency"}
    if unknown:
        raise ValueError(f"Unknown setting(s): {sorted(unknown)}")
    result = normalize(current)
    for channel in ("in_app", "email"):
        if channel not in patch:
            continue
        values = patch[channel]
        if not isinstance(values, dict) or set(values) - set(GROUPS) or not all(isinstance(v, bool) for v in values.values()):
            raise ValueError(f"{channel} must map {sorted(GROUPS)} to true/false.")
        result[channel].update(values)
    if "email_frequency" in patch:
        if patch["email_frequency"] not in FREQUENCIES:
            raise ValueError(f"email_frequency must be one of {list(FREQUENCIES)}.")
        result["email_frequency"] = patch["email_frequency"]
    return result


def wanted(alerts: list, preferences: dict, channel: str) -> list:
    """The alerts whose group is switched on for this channel."""
    switched = preferences[channel]
    return [a for a in alerts if switched.get(GROUP_OF_KIND.get(a["kind"], ""), True)]
