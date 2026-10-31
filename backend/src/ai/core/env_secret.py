"""
KEEL - reading provider keys from the environment.

A key pasted into Render, Codespaces secrets or .env often carries a trailing
space or line break, surrounding quotes, or a "Bearer " prefix copied from a
provider's example. Sent as-is, the provider answers "invalid API key" even
though the key itself is right. secret() returns the key without them, and
shape_problem() lets the configuration check say which setting had them.
Never returns or logs anything about a value except its shape.
"""
import os
from typing import Optional

_QUOTES = ('"', "'", "`")


def clean(value: Optional[str]) -> str:
    text = (value or "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in _QUOTES:
        text = text[1:-1].strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return text


def secret(*names: str) -> str:
    """The first of `names` that is set, cleaned; "" when none is."""
    for name in names:
        value = clean(os.getenv(name))
        if value:
            return value
    return ""


def shape_problem(name: str) -> Optional[str]:
    """What is wrong with how the setting was pasted, in words; None when nothing is (or it is unset)."""
    raw = os.getenv(name)
    if not raw:
        return None
    value = clean(raw)
    if not value:
        return "contains only spaces or quotes"
    if any(ch.isspace() for ch in value):
        return "contains a space or line break inside it - the provider will refuse it; paste the key again as one line"
    if value != raw:
        return "has spaces, a line break, quotes or a 'Bearer ' prefix around it (KEEL ignores them)"
    return None
