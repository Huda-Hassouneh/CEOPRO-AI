"""Explicit platform permission vocabulary, independent of tenant owner/admin roles."""
from fastapi import HTTPException

ORDINARY_ACTIONS = frozenset({"me", "overview", "companies", "company", "company_metadata", "company_status",
    "users", "user", "user_status", "membership_status", "team", "invite", "invitation_resend", "invitation_cancel", "audit",
    "settings", "settings_update"})
OWNER_ACTIONS = frozenset({"member_update", "owner_transfer", "financial_approval"})


def require_platform_permission(role, action):
    if role not in {"owner", "admin"} or action not in ORDINARY_ACTIONS | OWNER_ACTIONS:
        raise HTTPException(403, "Platform permission required.")
    if action in OWNER_ACTIONS and role != "owner":
        raise HTTPException(403, "Only the Platform Owner may authorize this operation.")
