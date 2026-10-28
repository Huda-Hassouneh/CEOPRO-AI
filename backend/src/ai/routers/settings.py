"""
KEEL - Settings: profile, company, team management, security, and
notification preferences.

Real gap this closes: a full audit of this repo found zero /settings,
/team, /company, or /users/me routes anywhere, despite the frontend
already having settings UI expecting them. Every endpoint below requires
an authenticated TenantContext (Depends(get_tenant_context)) - unlike
routers/auth.py, nothing here is a pre-authentication flow, so every
handler opens its connection with db.app_role_connection(tenant_id,
user_id), never db.auth_lookup_connection().

Two RLS policies (Final_schema.sql) do almost all of the real
authorization work here, for free, once the connection is opened with the
caller's own real tenant_id/user_id:
  - users.update_users_self only allows a UPDATE on the row whose user_id
    equals app.current_user_id - since ctx.user_id always comes from a
    verified JWT, "change my own profile/password" already can't touch
    anyone else's row, with no SECURITY DEFINER function needed (unlike
    auth.py's pre-auth password-reset, which genuinely has no user_id
    yet at that point in the flow).
  - tenant_users.isolation_tenant_users (tenant_id = get_current_tenant())
    already scopes every team read/write to the caller's own tenant.

What RLS does NOT do for us: distinguish an owner/admin from a staff
member within the same tenant for the company-wide and team-management
endpoints - _require_role() below is the one small piece of real
authorization logic this router adds on top of RLS.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from src.ai import company_data, db
from src.ai.core import security, usage
from src.ai import notification_prefs
from src.ai.core import auth_throttle, notifications
from src.ai.core.security import (
    TEAM_INVITATION_EXPIRE_MINUTES,
    TenantContext,
    ensure_password_policy,
    generate_url_safe_token,
    get_tenant_context,
    hash_password,
    hash_token,
    verify_password,
)
from src.market_scraper.company_geo_profile import get_tenant_search_scope, set_tenant_search_scope
from src.market_scraper.company_target_markets import get_tenant_target_markets, set_tenant_target_markets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.infrastructure.db_pool import forget_tenant_timezone

import logging
logger = logging.getLogger("APEX_SETTINGS")
router = APIRouter(prefix="/settings", tags=["settings"])

# The real seeded roles (Final_schema.sql's system_roles INSERT) - kept as
# a plain set here rather than a per-request SELECT FROM system_roles,
# since this list is only ever changed by a schema migration, exactly like
# routers/auth.py::AcceptInvitationRequest's own role_key already assumes
# a fixed, known set. tenant_users.role_key also carries a real FK to
# system_roles(role_key), so an invalid value here would fail at the
# database level regardless - this set exists to reject it early, with a
# real error message, instead of a raw psycopg2 FK-violation traceback.
_VALID_ROLE_KEYS = {"owner", "admin", "manager", "accountant", "staff"}
_COMPANY_ADMIN_ROLES = {"owner", "admin"}


def _require_role(conn, tenant_id: str, user_id: str, allowed_roles: set) -> str:
    """
    Looks up the caller's own real role_key in their own tenant and raises
    403 if it isn't one of allowed_roles. Deliberately a plain SELECT, not
    a SECURITY DEFINER function - tenant_users.isolation_tenant_users
    already permits this read on a connection opened with the caller's own
    tenant_id (db.app_role_connection), so no RLS bypass is needed here,
    unlike the pre-auth lookups routers/auth.py genuinely requires.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
            (tenant_id, user_id),
        )
        row = cursor.fetchone()
    if row is None or row[0] not in allowed_roles:
        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
    return row[0]


# --- Profile ----------------------------------------------------------------

def _fetch_profile(conn, user_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT user_id, email, full_name, preferred_language, email_verified_at
            FROM users WHERE user_id = %s;
            """,
            (user_id,),
        )
        row = cursor.fetchone()
    if row is None:
        # Should not happen for a request that already passed JWT auth
        # (the user_id came from a token issued for a real users row), but
        # a row could in principle be deleted between token issuance and
        # this request - a real 404, never a fabricated profile.
        raise HTTPException(status_code=404, detail="User not found.")
    user_id, email, full_name, preferred_language, email_verified_at = row
    return {
        "user_id": str(user_id),
        "email": email,
        "full_name": full_name,
        "preferred_language": preferred_language,
        "email_verified": email_verified_at is not None,
    }


@router.get("/profile")
def get_profile(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        profile = _fetch_profile(conn, ctx.user_id)
        conn.commit()
        return profile
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class UpdateProfileRequest(BaseModel):
    """Deliberately only these two fields - changing email is a bigger,
    separate flow (would need re-verification, uniqueness re-checking,
    likely a confirm-new-address step) that's out of scope here, not an
    oversight."""
    full_name: Optional[str] = None
    preferred_language: Optional[str] = None


@router.patch("/profile")
def update_profile(body: UpdateProfileRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    # exclude_unset (not exclude_none): a caller explicitly sending
    # full_name=null is a real, if unusual, request to clear it; a caller
    # who simply omits the field is not asking to change it at all - these
    # are different requests and must not collapse to the same UPDATE.
    updates = body.model_dump(exclude_unset=True)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        if updates:
            # updates' keys come only from UpdateProfileRequest's own
            # declared fields above (full_name, preferred_language), never
            # from arbitrary caller input, so building the SET clause from
            # them is not a SQL-injection surface.
            set_clause = ", ".join(f"{column} = %s" for column in updates)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE users SET {set_clause} WHERE user_id = %s;",
                    list(updates.values()) + [ctx.user_id],
                )
        profile = _fetch_profile(conn, ctx.user_id)
        conn.commit()
        return profile
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Company ------------------------------------------------------------

_COMPANY_COLUMNS = (
    "business_name", "business_type", "country_code", "operating_countries",
    "primary_currency", "supported_currencies", "timezone",
    "preferred_language", "supported_languages",
    "industry_key", "business_description", "website_url", "onboarding_completed_at", "is_demo",
)


def _fetch_company(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT {', '.join(_COMPANY_COLUMNS)} FROM companies WHERE tenant_id = %s;",
            (tenant_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    return dict(zip(_COMPANY_COLUMNS, row))


@router.get("/company")
def get_company(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        company = _fetch_company(conn, ctx.tenant_id)
        conn.commit()
        return company
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class UpdateCompanyRequest(BaseModel):
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    country_code: Optional[str] = None
    operating_countries: Optional[list] = None
    primary_currency: Optional[str] = None
    supported_currencies: Optional[list] = None
    timezone: Optional[str] = None
    preferred_language: Optional[str] = None
    supported_languages: Optional[list] = None
    # What the business is, for competitor discovery (a key of
    # market_discovery.industries), what it sells, and its own website.
    industry_key: Optional[str] = Field(default=None, max_length=50)
    business_description: Optional[str] = Field(default=None, max_length=1000)
    website_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("industry_key")
    @classmethod
    def _known_industry(cls, value):
        from src.market_scraper.market_discovery import industries

        if value is not None and industries.get(value) is None:
            raise ValueError("unknown industry")
        return value

    @field_validator("website_url")
    @classmethod
    def _web_address(cls, value):
        if not value:
            return None
        value = value.strip()
        if "://" not in value:
            value = f"https://{value}"
        if not value.startswith(("http://", "https://")) or "." not in value.split("://", 1)[1].split("/")[0]:
            raise ValueError("website_url must be a web address such as example.com")
        return value


@router.patch("/company")
def update_company(body: UpdateCompanyRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Owner/admin only - a 'staff' or 'manager' member editing company-wide
    settings (currency, operating countries, timezone...) that every other
    member and every downstream pricing/forecast calculation depends on
    would be a real authorization bug, not just a UX nicety.
    """
    updates = body.model_dump(exclude_unset=True)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        if "timezone" in updates:
            try:
                ZoneInfo(str(updates["timezone"]))
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(status_code=422, detail="Unknown time zone.")
        if updates:
            set_clause = ", ".join(f"{column} = %s" for column in updates)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE companies SET {set_clause} WHERE tenant_id = %s;",
                    list(updates.values()) + [ctx.tenant_id],
                )
        company = _fetch_company(conn, ctx.tenant_id)
        conn.commit()
        if "timezone" in updates:
            forget_tenant_timezone(ctx.tenant_id)  # the next transaction uses the new calendar
        return company
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/company/onboarding/complete")
def complete_onboarding(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Marks guided setup as done (idempotent); the app stops sending
    this company to the setup screens."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE companies SET onboarding_completed_at = COALESCE(onboarding_completed_at, CURRENT_TIMESTAMP) WHERE tenant_id = %s;",
                (ctx.tenant_id,),
            )
        company = _fetch_company(conn, ctx.tenant_id)
        conn.commit()
        return company
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- The company's own data: export and deletion ---

@router.get("/company/export")
def export_company_data(ctx: TenantContext = Depends(get_tenant_context)) -> Response:
    """Everything the company has stored, as a zip of JSON-lines files."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        payload = company_data.export_company(conn, ctx.tenant_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(content=payload, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="keel-company-export-{stamp}.zip"'})


class DeleteCompanyRequest(BaseModel):
    # The company's name, typed by the owner to confirm.
    confirm_name: str = Field(max_length=200)


@router.delete("/company")
def delete_company(body: DeleteCompanyRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Permanently deletes the company and all its data. Owner only, with
    the company name typed to confirm; refused while a paid subscription
    is still running (cancel it in Billing first)."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, {"owner"})
        name = _fetch_company(conn, ctx.tenant_id)["business_name"]
        conn.commit()
    finally:
        conn.close()
    if " ".join(body.confirm_name.split()).casefold() != " ".join((name or "").split()).casefold():
        raise HTTPException(status_code=422, detail="Type the company name exactly to confirm.")
    sys_conn = db.system_connection()
    try:
        result = company_data.delete_company(sys_conn, ctx.tenant_id)
        sys_conn.commit()
    except company_data.DeletionBlocked as blocked:
        sys_conn.rollback()
        if blocked.reason == "subscription_active":
            raise HTTPException(status_code=409, detail={"code": "SUBSCRIPTION_ACTIVE",
                                                         "message": "Cancel the paid subscription in Billing before deleting the company."})
        raise HTTPException(status_code=404, detail="Company not found.")
    except Exception:
        sys_conn.rollback()
        raise
    finally:
        sys_conn.close()
    removed = 0
    try:
        removed = company_data.remove_stored_files(db.minio_client(), ctx.tenant_id, result["rag_objects"])
    except Exception:  # noqa: BLE001 - storage unreachable: records are already gone
        logger.exception("stored files for deleted company %s were not removed", ctx.tenant_id)
    security.revoke_token(getattr(ctx, "token_id", None), getattr(ctx, "token_expires_at", None))
    logger.info("company %s deleted by its owner (%d stored files removed)", ctx.tenant_id, removed)
    return {"deleted": True}


# --- Competitor search scope ---------------------------------------------
#
# The user-facing control this closes: company_geo_profile.py::
# set_tenant_search_scope()/get_tenant_search_scope() already had all the
# real validation/preset-resolution logic (CITY/PROVINCE auto-resolve a
# real radius_km, COUNTRY/GLOBAL clear it, CUSTOM takes an explicit one)
# but was never reachable from any API route - a tenant had no way to
# actually tell competitor discovery/classification (src/ai/pricing/
# competitor_classification.py) what "my target market" means, so it
# always fell back to the DB default (PROVINCE, ~150km). Thin wrapper
# only - no new business logic, all of it already exists and is already
# tested (src/market_scraper/tests/test_company_geo_profile.py,
# test_data_access_proximity_integration_db.py).

class UpdateSearchScopeRequest(BaseModel):
    operating_countries: Optional[list] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    search_scope_level: Optional[str] = None
    custom_radius_km: Optional[int] = None


@router.get("/company/search-scope")
def get_search_scope(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        scope = get_tenant_search_scope(conn, ctx.tenant_id)
        conn.commit()
        return scope
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch("/company/search-scope")
def update_search_scope(body: UpdateSearchScopeRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Owner/admin only - same reasoning as update_company() above: this
    determines what "a real competitor" means for every member's
    Market Intelligence view, not a personal preference."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        scope = set_tenant_search_scope(
            conn, ctx.tenant_id,
            operating_countries=body.operating_countries, latitude=body.latitude, longitude=body.longitude,
            city=body.city, search_scope_level=body.search_scope_level, custom_radius_km=body.custom_radius_km,
        )
        return scope
    except HTTPException:
        conn.rollback()
        raise
    except ValueError as err:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(err))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Target Markets --------------------------------------------------------
#
# Explicit commercial target markets - a third, independent geography fact
# from the search-scope block above (see company_target_markets.py's own
# docstring for the full reasoning: country_code/operating_countries is
# where the business operates FROM, search_scope_level/radius is HOW FAR
# discovery searches AROUND the tenant, and this is which countries the
# tenant has explicitly said it wants to COMPETE IN). Same thin-wrapper
# shape as the search-scope endpoints above - PUT (not PATCH) because the
# real operation is always "replace the whole declared list with this
# one", matching set_tenant_target_markets()'s own replace semantics.

class TargetMarketEntry(BaseModel):
    market_type: str
    country_code: Optional[str] = None
    region_name: Optional[str] = None


class UpdateTargetMarketsRequest(BaseModel):
    target_markets: list[TargetMarketEntry] = []


@router.get("/company/target-markets")
def get_target_markets(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        target_markets = get_tenant_target_markets(conn, ctx.tenant_id)
        conn.commit()
        return {"target_markets": target_markets}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.put("/company/target-markets")
def update_target_markets(body: UpdateTargetMarketsRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Owner/admin only - same reasoning as update_search_scope() above:
    this feeds competitor discovery/classification for every member's
    Market Intelligence view, not a personal preference."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        target_markets = set_tenant_target_markets(
            conn, ctx.tenant_id, [entry.model_dump() for entry in body.target_markets],
        )
        return {"target_markets": target_markets}
    except HTTPException:
        conn.rollback()
        raise
    except ValueError as err:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(err))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Team ---------------------------------------------------------------

@router.get("/team/members")
def list_team_members(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tu.tenant_user_id, tu.user_id, u.email, u.full_name, tu.role_key, tu.joined_at
                FROM tenant_users tu
                JOIN users u ON u.user_id = tu.user_id
                WHERE tu.tenant_id = %s AND tu.removed_at IS NULL
                ORDER BY tu.joined_at ASC;
                """,
                (ctx.tenant_id,),
            )
            rows = cursor.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "members": [
            {
                "tenant_user_id": str(tenant_user_id),
                "user_id": str(user_id),
                "email": email,
                "full_name": full_name,
                "role_key": role_key,
                "joined_at": joined_at.isoformat() if joined_at else None,
            }
            for tenant_user_id, user_id, email, full_name, role_key, joined_at in rows
        ]
    }


class InviteTeamMemberRequest(BaseModel):
    email: str = Field(max_length=254)
    role_key: str


def _ensure_seat_for_invitation(conn, tenant_id: str, email: str) -> None:
    """Seats in use = active members + invitations still open (unused,
    unexpired; re-inviting the same address doesn't take a second seat). A new invitation needs a
    free seat; 402 otherwise. Locked per company until this transaction
    ends, so two invitations can't both take the last seat. Accepting checks
    the seat again (auth_join_tenant), in case the plan changed since."""
    plan = usage.get_plan(conn, tenant_id)
    if plan["status"] not in usage.ACCESS_GRANTING_STATUSES:
        raise usage.PlanLimitReached("SUBSCRIPTION_INACTIVE", usage.TEAM_SEATS).as_http()
    feature = plan["features"].get(usage.TEAM_SEATS)
    limit = feature["limit"] if feature else 0
    if limit is None:
        return
    usage.lock_feature(conn, tenant_id, usage.TEAM_SEATS)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT (SELECT COUNT(*) FROM tenant_users WHERE tenant_id = %(t)s AND removed_at IS NULL)
                 + (SELECT COUNT(DISTINCT lower(a.email)) FROM auth_tokens a
                    WHERE a.token_type = 'TEAM_INVITATION' AND a.tenant_id = %(t)s AND a.used_at IS NULL
                      AND a.expires_at > NOW() AND lower(a.email) <> lower(%(e)s));
            """,
            {"t": tenant_id, "e": email},
        )
        in_use = int(cursor.fetchone()[0])
    if in_use + 1 > limit:
        raise usage.PlanLimitReached("CAPACITY_REACHED", usage.TEAM_SEATS, in_use, limit, "lifetime").as_http()


@router.post("/team/invitations")
def invite_team_member(body: InviteTeamMemberRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Owner/admin only. Creates a real TEAM_INVITATION row in the same
    auth_tokens table routers/auth.py's GET/POST /auth/invitations/{token}
    endpoints already read from and consume - this is the other, tenant-
    scoped half of that same flow (see auth.py's own module docstring for
    why creating the invitation lives here and accepting it lives there).
    The raw token is only ever handed to notifications.
    send_team_invitation_email() - never returned in this response, the
    same convention routers/auth.py's own password-reset code follows.
    """
    if body.role_key not in _VALID_ROLE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role_key. Must be one of: {', '.join(sorted(_VALID_ROLE_KEYS))}.",
        )

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        caller_role = _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)
        _require_owner_to_touch_owners(caller_role, body.role_key)
        _ensure_seat_for_invitation(conn, ctx.tenant_id, body.email)

        with conn.cursor() as cursor:
            cursor.execute("SELECT business_name FROM companies WHERE tenant_id = %s;", (ctx.tenant_id,))
            company_row = cursor.fetchone()
        business_name = company_row[0] if company_row else "your workspace"

        raw_token = generate_url_safe_token()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=TEAM_INVITATION_EXPIRE_MINUTES)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auth_tokens
                    (token_type, token_hash, email, tenant_id, role_key, invited_by_user_id, expires_at)
                VALUES ('TEAM_INVITATION', %s, %s, %s, %s, %s, %s);
                """,
                (hash_token(raw_token), body.email, ctx.tenant_id, body.role_key, ctx.user_id, expires_at),
            )
        conn.commit()

        # The invitation is saved either way; say whether the email went out
        # (no email service configured, or the send failed) so the screen
        # never reports "sent" for an invitation nobody received.
        email_sent = notifications.send_team_invitation_email(body.email, business_name, raw_token)
        return {"ok": True, "email_sent": bool(email_sent)}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _require_owner_to_touch_owners(caller_role: str, *roles: str) -> None:
    """Only an owner may hand out, change or remove the owner role: otherwise an admin could
    promote themselves (or a friend) and then do the owner-only things, such as deleting the company."""
    if caller_role != "owner" and "owner" in roles:
        raise HTTPException(status_code=403, detail="Only an owner can grant, change or remove the owner role.")


def _fetch_active_member(conn, tenant_id: str, tenant_user_id: str):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT tenant_user_id, user_id, role_key FROM tenant_users
            WHERE tenant_id = %s AND tenant_user_id = %s AND removed_at IS NULL;
            """,
            (tenant_id, tenant_user_id),
        )
        return cursor.fetchone()


def _count_active_owners(conn, tenant_id: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM tenant_users WHERE tenant_id = %s AND role_key = 'owner' AND removed_at IS NULL;",
            (tenant_id,),
        )
        return cursor.fetchone()[0]


class UpdateTeamMemberRoleRequest(BaseModel):
    role_key: str


@router.patch("/team/members/{tenant_user_id}")
def update_team_member_role(
    tenant_user_id: str, body: UpdateTeamMemberRoleRequest, ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    """
    Owner/admin only. Real guard against a tenant ending up with zero
    owners: if the target row is currently the tenant's LAST active owner,
    demoting it to any other role is rejected - without this, an
    admin (or a mistaken owner) could lock the whole tenant out of any
    owner-only action with no way back in, since nothing else in this
    schema can promote someone to owner except an existing owner/admin.
    """
    if body.role_key not in _VALID_ROLE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role_key. Must be one of: {', '.join(sorted(_VALID_ROLE_KEYS))}.",
        )

    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        caller_role = _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)

        member = _fetch_active_member(conn, ctx.tenant_id, tenant_user_id)
        if member is None:
            raise HTTPException(status_code=404, detail="Team member not found.")
        _, _, current_role = member
        _require_owner_to_touch_owners(caller_role, current_role, body.role_key)

        if current_role == "owner" and body.role_key != "owner" and _count_active_owners(conn, ctx.tenant_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot change the role of the last remaining owner.")

        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_users SET role_key = %s WHERE tenant_id = %s AND tenant_user_id = %s;",
                (body.role_key, ctx.tenant_id, tenant_user_id),
            )
        conn.commit()
        return {"ok": True, "tenant_user_id": tenant_user_id, "role_key": body.role_key}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/team/members/{tenant_user_id}")
def remove_team_member(tenant_user_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Owner/admin only. Soft-delete (removed_at = NOW()), matching tenant_
    users' existing soft-delete convention - get_current_tenant() and
    auth_lookup_user_memberships() (auth.py) both already filter
    removed_at IS NULL, so a removed member immediately loses tenant
    access (their JWT still decodes, but their NEXT request's
    get_current_tenant() resolves to NULL, and every RLS policy then sees
    zero rows for them) without deleting their user account or history.
    Same last-owner guard as PATCH above.
    """
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        caller_role = _require_role(conn, ctx.tenant_id, ctx.user_id, _COMPANY_ADMIN_ROLES)

        member = _fetch_active_member(conn, ctx.tenant_id, tenant_user_id)
        if member is None:
            raise HTTPException(status_code=404, detail="Team member not found.")
        _, _, current_role = member
        _require_owner_to_touch_owners(caller_role, current_role)

        if current_role == "owner" and _count_active_owners(conn, ctx.tenant_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last remaining owner.")

        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE tenant_users SET removed_at = NOW() WHERE tenant_id = %s AND tenant_user_id = %s;",
                (ctx.tenant_id, tenant_user_id),
            )
        conn.commit()
        return {"ok": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Security -------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/security/change-password")
def change_password(body: ChangePasswordRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Real bcrypt verification of the CALLER's own current password before
    accepting a new one - never a blind overwrite. Reads password_hash via
    a plain SELECT scoped by ctx.user_id (select_users_perimeter's own
    "user_id = app.current_user_id" clause allows this), then the UPDATE
    itself passes update_users_self's identical "own row only" check - no
    SECURITY DEFINER function needed, unlike auth.py's pre-auth password-
    reset, which genuinely has no authenticated user_id yet at that point.
    """
    # A stolen session must not be a way to guess the password: same limit as signing in.
    throttle_key = f"user:{ctx.user_id}"
    auth_throttle.ensure_allowed("login", throttle_key)
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users WHERE user_id = %s;", (ctx.user_id,))
            row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found.")

        if not verify_password(body.current_password, row[0]):
            auth_throttle.record_failure("login", throttle_key)
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        auth_throttle.reset("login", throttle_key)

        ensure_password_policy(body.new_password)
        new_hash = hash_password(body.new_password)
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET password_hash = %s WHERE user_id = %s;", (new_hash, ctx.user_id))
        conn.commit()
        # Every other session (a stolen one included) is signed out; this one continues on a fresh token.
        security.invalidate_sessions(ctx.user_id)
        security.revoke_token(getattr(ctx, "token_id", None), getattr(ctx, "token_expires_at", None))
        token, expires_in = security.create_access_token(
            ctx.tenant_id, ctx.user_id, email_verified=getattr(ctx, "email_verified", False))
        return {"ok": True, "access_token": token, "token_type": "bearer", "expires_in": expires_in}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/security/sessions")
def list_sessions(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """
    Honest, not fabricated: this service issues stateless JWTs with no
    server-side session table (see routers/auth.py::logout()'s own
    docstring - "logging out" already can't invalidate a token server-
    side for the identical reason). There is nothing real to list here -
    returning an invented session list (e.g. one row guessed from the
    current request's own IP/user-agent) would be worse than an honest
    empty result, since it would look like real tracked session state
    that doesn't actually exist.
    """
    return {
        "sessions": [],
        "note": (
            "This service does not track sessions server-side; each issued access "
            "token is independent and stays valid until its own expiry."
        ),
    }


# --- Notification preferences ---------------------------------------------

@router.get("/notifications")
def get_notification_preferences(ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """This person's alert choices (src/ai/notification_prefs.py), with defaults
    filled in, and whether the server can send email at all."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT notification_preferences, email_verified_at IS NOT NULL FROM users WHERE user_id = %s;",
                           (ctx.user_id,))
            row = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    # Summaries only go to verified addresses (notification_digest.py).
    return {"notification_preferences": notification_prefs.normalize(row[0]),
            "email_delivery_available": notifications.is_configured(), "email_verified": bool(row[1])}


@router.patch("/notifications")
def update_notification_preferences(body: dict, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    """Changes some of this person's alert choices: in_app / email (group ->
    true/false) and email_frequency (off, daily, weekly). Anything else is
    refused with 422."""
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT notification_preferences, email_verified_at IS NOT NULL FROM users WHERE user_id = %s FOR UPDATE;",
                           (ctx.user_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="User not found.")
            try:
                updated = notification_prefs.apply_patch(row[0], body)
            except ValueError as err:
                raise HTTPException(status_code=422, detail=str(err))
            cursor.execute("UPDATE users SET notification_preferences = %s::jsonb WHERE user_id = %s;",
                           (json.dumps(updated), ctx.user_id))
        conn.commit()
        return {"notification_preferences": updated, "email_delivery_available": notifications.is_configured(),
                "email_verified": bool(row[1])}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
