"""Managed promotion eligibility and redemption state.

Stripe remains the only monetary discount authority. Managed promotions are
off by default; this module never creates a Stripe coupon or publishes a
campaign. Local redemption state is coordination/audit state, not a payment
or credit ledger.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from psycopg2.extras import Json

from src.ai.billing import store, stripe_api

TERMS_REQUIRED = frozenset({
    "discount_type", "discount_value", "currency", "starts_at", "expires_at",
    "max_uses", "max_uses_per_tenant", "invoice_scope", "stripe_coupon_id",
    "stripe_promotion_code_id",
})
TERMS_ALLOWED = TERMS_REQUIRED


class PromotionError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def enabled() -> bool:
    return os.getenv("KEEL_MANAGED_PROMOTIONS_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def normalize_code(value: str) -> str:
    code = (value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,99}", code):
        raise PromotionError(422, "invalid_promotion_code", "Enter a valid promotion code.")
    return code


def _term_value(value: Any):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PromotionError(422, "invalid_promotion_terms", "Promotion dates must include a timezone.")
        return value.astimezone(timezone.utc).isoformat()
    return value


def _validate_terms(terms: dict) -> tuple[dict, list[str]]:
    if not isinstance(terms, dict) or set(terms) - TERMS_ALLOWED:
        raise PromotionError(422, "invalid_promotion_terms", "Promotion terms contain unsupported fields.")
    out = {key: _term_value(value) for key, value in terms.items()}
    if "discount_type" in out and out["discount_type"] not in {"percent", "fixed_amount"}:
        raise PromotionError(422, "invalid_promotion_terms", "Unsupported discount type.")
    if "discount_value" in out:
        try:
            value = Decimal(str(out["discount_value"]))
        except (InvalidOperation, ValueError):
            raise PromotionError(422, "invalid_promotion_terms", "Discount value must be numeric.") from None
        if not value.is_finite() or value <= 0 or (out.get("discount_type") == "percent" and value > 100):
            raise PromotionError(422, "invalid_promotion_terms", "Discount value is outside the supported range.")
        out["discount_value"] = str(value)
    if "currency" in out and (not isinstance(out["currency"], str) or not re.fullmatch(r"[A-Za-z]{3}", out["currency"])):
        raise PromotionError(422, "invalid_promotion_terms", "Currency must be a three-letter code.")
    if "currency" in out:
        out["currency"] = out["currency"].upper()
    for key in ("starts_at", "expires_at"):
        if key in out and out[key] is not None:
            try:
                parsed = datetime.fromisoformat(out[key])
                if parsed.tzinfo is None:
                    raise ValueError("timezone required")
                out[key] = parsed.astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                raise PromotionError(422, "invalid_promotion_terms", "Promotion dates must include a valid timezone.") from None
    if out.get("invoice_scope") not in (None, "initial_subscription") and "invoice_scope" in out:
        raise PromotionError(422, "invalid_promotion_terms", "Only initial subscription invoices are supported.")
    for key in ("max_uses", "max_uses_per_tenant"):
        if key in out and out[key] is not None:
            if isinstance(out[key], bool) or not isinstance(out[key], int) or out[key] <= 0:
                raise PromotionError(422, "invalid_promotion_terms", f"{key} must be a positive integer or explicit null.")
    for key in ("stripe_coupon_id", "stripe_promotion_code_id"):
        if key in out and out[key] is not None and (not isinstance(out[key], str) or not out[key].strip()):
            raise PromotionError(422, "invalid_promotion_terms", f"{key} must be a non-empty provider reference or omitted.")
    missing = sorted(TERMS_REQUIRED - out.keys())
    if not missing:
        start, end = out["starts_at"], out["expires_at"]
        try:
            if start is not None and end is not None and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
                raise PromotionError(422, "invalid_promotion_terms", "The start date must precede the expiry date.")
        except (TypeError, ValueError):
            raise PromotionError(422, "invalid_promotion_terms", "Promotion dates must be valid ISO timestamps or explicit null.") from None
        if out["invoice_scope"] != "initial_subscription":
            raise PromotionError(422, "invalid_promotion_terms", "Invoice scope must be initial_subscription.")
        if not out["stripe_coupon_id"] or not out["stripe_promotion_code_id"]:
            missing.extend(key for key in ("stripe_coupon_id", "stripe_promotion_code_id") if not out[key])
    return out, sorted(set(missing))


def _promotion_dict(row) -> dict:
    (promotion_id, code, name, description, status, terms, coupon_id, promotion_code_id,
     approval_reference, created_at, updated_at) = row
    if isinstance(terms, str):
        terms = json.loads(terms)
    return {
        "promotion_id": str(promotion_id), "code": code, "name": name,
        "description": description, "status": status, "terms": terms or {},
        "stripe_coupon_id": coupon_id, "stripe_promotion_code_id": promotion_code_id,
        "approval_reference": approval_reference,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _operator_lock(conn, actor_user_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));")
        cur.execute(
            "SELECT m.role_key FROM public.keel_platform_members m JOIN public.users u USING(user_id) "
            "WHERE m.user_id=%s AND m.status='active' AND u.platform_disabled_at IS NULL FOR UPDATE OF m;",
            (actor_user_id,),
        )
        row = cur.fetchone()
    if not row or row[0] != "owner":
        raise PromotionError(403, "platform_owner_required", "Only the Platform Owner may manage promotion definitions.")
    return row[0]


def _platform_audit(conn, actor_user_id: str, role: str, action: str, subject: str,
                    old_value, new_value, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,'succeeded');",
            (actor_user_id, role, action, subject, Json(old_value) if old_value is not None else None,
             Json(new_value) if new_value is not None else None, reason),
        )


def list_definitions(conn, actor_user_id: str) -> list[dict]:
    _operator_lock(conn, actor_user_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT promotion_id,code,name,description,status,terms,stripe_coupon_id,stripe_promotion_code_id,"
            "approval_reference,created_at,updated_at FROM public.billing_promotions ORDER BY created_at DESC,promotion_id;"
        )
        rows = cur.fetchall()
        result = [_promotion_dict(row) for row in rows]
        for item in result:
            cur.execute("SELECT plan_key FROM public.billing_promotion_plans WHERE promotion_id=%s ORDER BY plan_key;",
                        (item["promotion_id"],))
            item["plan_keys"] = [r[0] for r in cur.fetchall()]
            item["missing_terms"] = sorted(TERMS_REQUIRED - item["terms"].keys())
    return result


def save_draft(conn, *, actor_user_id: str, code: str, name: str, description: str,
               terms: dict, plan_keys: list[str], reason: str, promotion_id: str | None = None) -> dict:
    role = _operator_lock(conn, actor_user_id)
    code = normalize_code(code)
    terms, missing = _validate_terms(terms)
    plan_keys = sorted(set(plan_keys or []))
    if not plan_keys:
        missing.append("plan_keys")
    with conn.cursor() as cur:
        if plan_keys:
            cur.execute("SELECT plan_key FROM public.usage_plans WHERE plan_key=ANY(%s) AND is_active ORDER BY plan_key;",
                        (plan_keys,))
            found = [row[0] for row in cur.fetchall()]
            if found != plan_keys:
                raise PromotionError(422, "unknown_promotion_plan", "All associated plans must be existing active catalog plans.")
        if promotion_id:
            cur.execute("SELECT status,code,name,description,terms,stripe_coupon_id,stripe_promotion_code_id "
                        "FROM public.billing_promotions WHERE promotion_id=%s FOR UPDATE;", (promotion_id,))
            old = cur.fetchone()
            if not old:
                raise PromotionError(404, "promotion_not_found", "Promotion definition not found.")
            if old[0] != "draft":
                raise PromotionError(409, "promotion_not_editable", "Only draft promotion definitions can be edited.")
            old_terms = old[4] if isinstance(old[4], dict) else json.loads(old[4] or "{}")
            merged_terms = {**old_terms, **terms}
            merged_terms, missing = _validate_terms(merged_terms)
            new = {"code": code, "name": name.strip(), "description": description,
                   "terms": merged_terms, "plan_keys": plan_keys}
            cur.execute(
                "UPDATE public.billing_promotions SET code=%s,name=%s,description=%s,terms=%s::jsonb,"
                "stripe_coupon_id=%s,stripe_promotion_code_id=%s,updated_by=%s,updated_at=NOW() "
                "WHERE promotion_id=%s AND status='draft' RETURNING promotion_id,code,name,description,status,terms,"
                "stripe_coupon_id,stripe_promotion_code_id,approval_reference,created_at,updated_at;",
                (code, name.strip(), description, json.dumps(merged_terms), merged_terms.get("stripe_coupon_id"),
                 merged_terms.get("stripe_promotion_code_id"), actor_user_id, promotion_id),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM public.billing_promotion_plans WHERE promotion_id=%s;", (promotion_id,))
            if plan_keys:
                cur.executemany("INSERT INTO public.billing_promotion_plans(promotion_id,plan_key) VALUES(%s,%s);",
                                [(promotion_id, plan_key) for plan_key in plan_keys])
            _platform_audit(conn, actor_user_id, role, "promotion_draft_update", promotion_id,
                            {"status": old[0], "code": old[1], "name": old[2], "terms": old_terms}, new, reason)
        else:
            cur.execute(
                "INSERT INTO public.billing_promotions(code,name,description,status,terms,stripe_coupon_id,"
                "stripe_promotion_code_id,created_by,updated_by) VALUES(%s,%s,%s,'draft',%s::jsonb,%s,%s,%s,%s) "
                "RETURNING promotion_id,code,name,description,status,terms,stripe_coupon_id,stripe_promotion_code_id,"
                "approval_reference,created_at,updated_at;",
                (code, name.strip(), description, json.dumps(terms), terms.get("stripe_coupon_id"),
                 terms.get("stripe_promotion_code_id"), actor_user_id, actor_user_id),
            )
            row = cur.fetchone()
            if plan_keys:
                cur.executemany("INSERT INTO public.billing_promotion_plans(promotion_id,plan_key) VALUES(%s,%s);",
                                [(row[0], plan_key) for plan_key in plan_keys])
            _platform_audit(conn, actor_user_id, role, "promotion_draft_create", str(row[0]), None,
                            {"code": code, "name": name.strip(), "terms": terms, "plan_keys": plan_keys}, reason)
    result = _promotion_dict(row)
    result["plan_keys"] = plan_keys
    result["missing_terms"] = sorted(set(missing))
    result["eligible"] = False
    return result


def disable(conn, *, actor_user_id: str, promotion_id: str, reason: str) -> dict:
    role = _operator_lock(conn, actor_user_id)
    with conn.cursor() as cur:
        cur.execute("SELECT status,code FROM public.billing_promotions WHERE promotion_id=%s FOR UPDATE;", (promotion_id,))
        old = cur.fetchone()
        if not old:
            raise PromotionError(404, "promotion_not_found", "Promotion definition not found.")
        if old[0] == "disabled":
            return {"promotion_id": promotion_id, "status": "disabled"}
        cur.execute("UPDATE public.billing_promotions SET status='disabled',updated_by=%s,updated_at=NOW() "
                    "WHERE promotion_id=%s RETURNING status;", (actor_user_id, promotion_id))
        status = cur.fetchone()[0]
        _platform_audit(conn, actor_user_id, role, "promotion_disable", promotion_id,
                        {"status": old[0]}, {"status": status}, reason)
    return {"promotion_id": promotion_id, "status": status}


def _load_active(conn, code: str):
    normalized = normalize_code(code)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT p.promotion_id,p.code,p.status,p.terms,p.stripe_coupon_id,p.stripe_promotion_code_id "
            "FROM public.billing_promotions p WHERE p.code=%s AND p.status='active';", (normalized,)
        )
        return cur.fetchone()


def _eligibility(conn, tenant_id: str, code: str, plan_key: str, period_code: str,
                 *, check_custom_contract: bool = True) -> tuple[dict | None, str | None]:
    row = _load_active(conn, code)
    if not row:
        return None, "not_available"
    promo_id, normalized, _status, terms, coupon_id, promotion_code_id = row
    if isinstance(terms, str):
        terms = json.loads(terms)
    terms, missing = _validate_terms(terms or {})
    if missing:
        return None, "not_available"
    now = datetime.now(timezone.utc)
    starts = datetime.fromisoformat(terms["starts_at"]) if terms["starts_at"] else None
    expires = datetime.fromisoformat(terms["expires_at"]) if terms["expires_at"] else None
    if starts and now < starts:
        return None, "not_eligible"
    if expires and now >= expires:
        return None, "not_eligible"
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM public.billing_promotion_plans WHERE promotion_id=%s AND plan_key=%s;",
                    (promo_id, plan_key))
        if not cur.fetchone():
            return None, "not_eligible"
    price = store.current_price(conn, plan_key, period_code)
    if not price or not price["is_active"] or not price.get("self_serve") or price["currency"].upper() != terms["currency"]:
        return None, "not_eligible"
    if check_custom_contract and store.has_custom_contract(conn, tenant_id):
        # Existing private-contract rows do not classify a contract as discounted.
        # Block only the new managed-promotion operation, leaving legacy billing untouched.
        return None, "custom_contract_review"
    return {
        "promotion_id": str(promo_id), "code": normalized, "terms": terms,
        "stripe_coupon_id": coupon_id, "stripe_promotion_code_id": promotion_code_id,
        "plan_key": plan_key, "period_code": period_code,
    }, None


def validate(conn, tenant_id: str, code: str, plan_key: str, period_code: str) -> dict:
    if not enabled():
        return {"valid": False, "reason": "promotions_unavailable"}
    try:
        promo, reason = _eligibility(conn, tenant_id, code, plan_key, period_code)
    except PromotionError:
        return {"valid": False, "reason": "not_available"}
    return {"valid": bool(promo), "reason": reason,
            "promotion": ({"code": promo["code"], "discount_type": promo["terms"]["discount_type"],
                           "discount_value": promo["terms"]["discount_value"], "currency": promo["terms"]["currency"]}
                          if promo else None)}


def require_checkout_eligibility(conn, tenant_id: str, code: str, plan_key: str, period_code: str) -> dict:
    if not enabled():
        raise PromotionError(503, "promotions_unavailable", "Managed promotions are not enabled.")
    try:
        promo, reason = _eligibility(conn, tenant_id, code, plan_key, period_code)
    except PromotionError:
        raise
    if not promo:
        error = "custom_contract_review" if reason == "custom_contract_review" else "promotion_not_available"
        raise PromotionError(409, error, "This promotion is not available for this checkout.")
    return promo


def reserve(conn, *, tenant_id: str, actor_user_id: str, code: str, plan_key: str, period_code: str,
            request_key: str) -> dict:
    if not enabled():
        raise PromotionError(503, "promotions_unavailable", "Managed promotions are not enabled.")
    request_key = str(request_key)
    if not actor_user_id:
        raise PromotionError(401, "principal_required", "An authenticated billing principal is required.")
    if not 1 <= len(request_key) <= 200:
        raise PromotionError(422, "invalid_idempotency_key", "Checkout identity is invalid.")
    normalized = normalize_code(code)
    with conn.cursor() as cur:
        promo = _load_active(conn, normalized)
        if not promo:
            raise PromotionError(409, "promotion_not_available", "This promotion is not available.")
        promo_id = promo[0]
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0));", ("keel_promotion:" + str(promo_id),))
        # The row lock serializes validation, cap checks and reservation creation.
        cur.execute("SELECT promotion_id FROM public.billing_promotions WHERE promotion_id=%s AND status='active' FOR UPDATE;",
                    (promo_id,))
        if not cur.fetchone():
            raise PromotionError(409, "promotion_not_available", "This promotion is not available.")
        fingerprint = hashlib.sha256(f"{tenant_id}:{promo_id}:{plan_key}:{period_code}:{normalized}".encode()).hexdigest()
        cur.execute("SELECT redemption_id,state,request_fingerprint,stripe_checkout_session_id FROM public.billing_promotion_redemptions "
                    "WHERE tenant_id=%s AND promotion_id=%s AND request_key=%s FOR UPDATE;",
                    (tenant_id, promo_id, request_key))
        prior = cur.fetchone()
        if prior:
            if prior[2].strip() != fingerprint:
                raise PromotionError(409, "idempotency_conflict", "The checkout key was already used for different promotion terms.")
            if prior[1] == "reconciliation_required":
                raise PromotionError(409, "promotion_reconciliation_required", "This checkout needs reconciliation before retry.")
            if prior[1] == "rejected":
                raise PromotionError(409, "promotion_reservation_closed", "This checkout reservation is no longer eligible.")
            row, reason = _eligibility(conn, tenant_id, normalized, plan_key, period_code)
            if not row:
                raise PromotionError(409, "promotion_not_available", "This promotion is not available.")
            return {"redemption_id": str(prior[0]), "session_id": prior[3], "promotion": row, "reused": True}
        # A retry in a later time bucket must not create a second reservation
        # while an earlier checkout is still open or its provider outcome is
        # uncertain. Reuse the same durable operation identity instead.
        cur.execute(
            "SELECT redemption_id,state,request_fingerprint,stripe_checkout_session_id "
            "FROM public.billing_promotion_redemptions WHERE tenant_id=%s AND promotion_id=%s "
            "AND state IN ('pending','reconciliation_required') ORDER BY created_at DESC LIMIT 1 FOR UPDATE;",
            (tenant_id, promo_id),
        )
        open_redemption = cur.fetchone()
        if open_redemption:
            if open_redemption[2].strip() != fingerprint:
                raise PromotionError(409, "promotion_checkout_in_progress", "An earlier checkout for this promotion needs to finish first.")
            if open_redemption[1] == "reconciliation_required":
                raise PromotionError(409, "promotion_reconciliation_required", "This checkout needs reconciliation before retry.")
            row, reason = _eligibility(conn, tenant_id, normalized, plan_key, period_code)
            if not row:
                raise PromotionError(409, "promotion_not_available", "This promotion is not available.")
            return {"redemption_id": str(open_redemption[0]), "session_id": open_redemption[3],
                    "promotion": row, "reused": True}
        details, reason = _eligibility(conn, tenant_id, normalized, plan_key, period_code)
        if not details:
            raise PromotionError(409, "promotion_not_available", "This promotion is not available.")
        terms = details["terms"]
        # Pending and reconciliation-required reservations hold a slot; only
        # verified rejection releases it. NULL is accepted only when the
        # corresponding term key is explicitly present and approved on active rows.
        cur.execute("SELECT count(*) FROM public.billing_promotion_redemptions WHERE promotion_id=%s "
                    "AND state IN ('pending','settled','reconciliation_required');", (promo_id,))
        global_uses = cur.fetchone()[0]
        if terms["max_uses"] is not None and global_uses >= terms["max_uses"]:
            raise PromotionError(409, "promotion_exhausted", "This promotion is no longer available.")
        cur.execute("SELECT count(*) FROM public.billing_promotion_redemptions WHERE tenant_id=%s AND promotion_id=%s "
                    "AND state IN ('pending','settled','reconciliation_required');", (tenant_id, promo_id))
        tenant_uses = cur.fetchone()[0]
        if terms["max_uses_per_tenant"] is not None and tenant_uses >= terms["max_uses_per_tenant"]:
            raise PromotionError(409, "promotion_tenant_limit", "This promotion is no longer available.")
        cur.execute(
            "INSERT INTO public.billing_promotion_redemptions(tenant_id,promotion_id,state,request_key,request_fingerprint,plan_key,period_code) "
            "VALUES(%s,%s,'pending',%s,%s,%s,%s) RETURNING redemption_id;",
            (tenant_id, promo_id, request_key, fingerprint, plan_key, period_code),
        )
        redemption_id = cur.fetchone()[0]
        _redemption_event(conn, tenant_id, redemption_id, actor_user_id, "reserved", None, "pending", None, None)
    return {"redemption_id": str(redemption_id), "session_id": None, "promotion": details, "reused": False}


def begin_checkout_request(conn, *, tenant_id: str, redemption_id: str) -> None:
    """Durably claim the one permitted Stripe checkout-create attempt.

    If the process dies after this commit, retries fail closed rather than
    issuing a second provider request with an uncertain prior outcome.
    Stripe webhook delivery can still bind the resulting session by receipt
    metadata and reconcile it.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state,stripe_checkout_session_id,checkout_request_started_at "
            "FROM public.billing_promotion_redemptions WHERE tenant_id=%s AND redemption_id=%s FOR UPDATE;",
            (tenant_id, redemption_id),
        )
        row = cur.fetchone()
        if not row or row[0] != "pending":
            raise PromotionError(409, "promotion_reconciliation_required", "This checkout needs reconciliation before retry.")
        if row[1]:
            return
        if row[2]:
            raise PromotionError(409, "promotion_reconciliation_required", "This checkout needs reconciliation before retry.")
        cur.execute(
            "UPDATE public.billing_promotion_redemptions SET checkout_request_started_at=NOW(),updated_at=NOW() "
            "WHERE tenant_id=%s AND redemption_id=%s AND checkout_request_started_at IS NULL;",
            (tenant_id, redemption_id),
        )
        if cur.rowcount != 1:
            raise PromotionError(409, "promotion_reconciliation_required", "This checkout needs reconciliation before retry.")
        _redemption_event(conn, tenant_id, redemption_id, None, "checkout_request_started", "pending", "pending", None, None)


def _redemption_event(conn, tenant_id, redemption_id, actor_user_id, event_type, old_state, new_state,
                      stripe_event_id, reason_code):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.billing_promotion_events(tenant_id,redemption_id,actor_user_id,event_type,old_state,new_state,stripe_event_id,reason_code) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;",
            (tenant_id, redemption_id, actor_user_id, event_type, old_state, new_state, stripe_event_id, reason_code),
        )


def _set_state(conn, redemption_id, tenant_id, state, *, event_type, stripe_event_id=None,
               invoice_id=None, subscription_id=None, reason_code=None):
    with conn.cursor() as cur:
        cur.execute("SELECT state,stripe_subscription_id,stripe_initial_invoice_id FROM public.billing_promotion_redemptions "
                    "WHERE redemption_id=%s AND tenant_id=%s FOR UPDATE;", (redemption_id, tenant_id))
        row = cur.fetchone()
        if not row:
            return False
        old, existing_sub, existing_invoice = row
        if old == "settled":
            return existing_sub == subscription_id and existing_invoice == invoice_id
        if old == "rejected" and state != "rejected":
            return False
        if subscription_id and existing_sub and str(existing_sub) != str(subscription_id):
            state, reason_code = "reconciliation_required", "subscription_identity_mismatch"
        if invoice_id and existing_invoice and str(existing_invoice) != str(invoice_id):
            state, reason_code = "reconciliation_required", "invoice_identity_mismatch"
        cur.execute(
            "UPDATE public.billing_promotion_redemptions SET state=%s,"
            "stripe_subscription_id=coalesce(stripe_subscription_id,%s),"
            "stripe_initial_invoice_id=coalesce(stripe_initial_invoice_id,%s),"
            "settled_at=CASE WHEN %s='settled' THEN coalesce(settled_at,NOW()) ELSE NULL END,"
            "last_error_code=%s,updated_at=NOW() WHERE redemption_id=%s AND tenant_id=%s;",
            (state, subscription_id, invoice_id, state, reason_code, redemption_id, tenant_id),
        )
        _redemption_event(conn, tenant_id, redemption_id, None, event_type, old, state, stripe_event_id, reason_code)
        return True


def attach_checkout(conn, *, tenant_id: str, redemption_id: str, session_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT state,stripe_checkout_session_id FROM public.billing_promotion_redemptions "
                    "WHERE tenant_id=%s AND redemption_id=%s FOR UPDATE;", (tenant_id, redemption_id))
        row = cur.fetchone()
        if not row:
            raise PromotionError(409, "promotion_reservation_changed", "Promotion reservation needs reconciliation.")
        if row[0] == "settled" and row[1] == session_id:
            # A fast signed webhook can bind and settle before the checkout
            # request thread persists its response. Treat that exact late
            # attach as idempotent.
            return
        if row[0] != "pending":
            raise PromotionError(409, "promotion_reservation_changed", "Promotion reservation needs reconciliation.")
        if row[1] == session_id:
            return
        if row[1] and row[1] != session_id:
            _set_state(conn, redemption_id, tenant_id, "reconciliation_required", event_type="checkout_identity_conflict",
                       reason_code="checkout_session_mismatch")
            raise PromotionError(409, "promotion_reconciliation_required", "Promotion checkout needs reconciliation.")
        cur.execute("UPDATE public.billing_promotion_redemptions SET stripe_checkout_session_id=%s,updated_at=NOW() "
                    "WHERE tenant_id=%s AND redemption_id=%s;", (session_id, tenant_id, redemption_id))
        _redemption_event(conn, tenant_id, redemption_id, None, "checkout_attached", "pending", "pending", None, None)


def provider_outcome_unknown(conn, *, tenant_id: str, redemption_id: str) -> None:
    _set_state(conn, redemption_id, tenant_id, "reconciliation_required", event_type="provider_outcome_unknown",
               reason_code="provider_outcome_unknown")


def _metadata_redemption(obj: dict):
    metadata = obj.get("metadata") or {}
    if not metadata:
        parent = (obj.get("parent") or {}).get("subscription_details") or {}
        metadata = parent.get("metadata") or (obj.get("subscription_details") or {}).get("metadata") or {}
    return metadata.get("keel_promotion_redemption_id")


def checkout_completed(conn, *, session: dict, tenant_id: str, stripe_event_id: str) -> None:
    redemption_id = _metadata_redemption(session)
    subscription_id = session.get("subscription")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    if not redemption_id:
        return
    session_id = session.get("id")
    with conn.cursor() as cur:
        cur.execute("SELECT tenant_id,state,stripe_checkout_session_id,stripe_subscription_id FROM public.billing_promotion_redemptions "
                    "WHERE redemption_id=%s FOR UPDATE;", (redemption_id,))
        row = cur.fetchone()
        if not row:
            return
        stored_tenant, state, stored_session, stored_sub = row
        if str(stored_tenant) != str(tenant_id) or (stored_session and stored_session != session_id) or (stored_sub and subscription_id and stored_sub != subscription_id):
            _set_state(conn, redemption_id, stored_tenant, "reconciliation_required", event_type="checkout_identity_conflict",
                       stripe_event_id=stripe_event_id, reason_code="checkout_identity_mismatch")
            return
        if state == "rejected":
            return
        cur.execute("UPDATE public.billing_promotion_redemptions SET stripe_checkout_session_id=coalesce(stripe_checkout_session_id,%s),"
                    "stripe_subscription_id=coalesce(stripe_subscription_id,%s),updated_at=NOW() "
                    "WHERE redemption_id=%s AND tenant_id=%s;", (session_id, subscription_id, redemption_id, tenant_id))
        _redemption_event(conn, tenant_id, redemption_id, None, "checkout_completed", state, state, stripe_event_id, None)
    # Checkout and invoice events can arrive out of order. If Stripe includes
    # the initial invoice on the completed session, reconcile it through the
    # same settled-invoice predicate used by invoice webhooks.
    invoice_id = session.get("invoice")
    if isinstance(invoice_id, dict):
        invoice_id = invoice_id.get("id")
    if invoice_id and subscription_id:
        invoice = stripe_api.retrieve_invoice(invoice_id)
        if invoice.get("id") != invoice_id:
            raise RuntimeError("checkout initial invoice identity mismatch")
        invoice_event(
            conn, tenant_id=tenant_id, invoice=invoice, subscription_id=subscription_id,
            stripe_event_id=stripe_event_id, payment_succeeded=(invoice.get("status") == "paid" or invoice.get("paid") is True),
        )


def checkout_expired(conn, *, session: dict, stripe_event_id: str) -> None:
    redemption_id = _metadata_redemption(session)
    if not redemption_id:
        return
    session_id = session.get("id")
    with conn.cursor() as cur:
        cur.execute("SELECT tenant_id,state,stripe_checkout_session_id,stripe_subscription_id,stripe_initial_invoice_id "
                    "FROM public.billing_promotion_redemptions WHERE redemption_id=%s FOR UPDATE;", (redemption_id,))
        row = cur.fetchone()
        if not row:
            return
        tenant_id, state, stored_session, subscription_id, invoice_id = row
        if stored_session and stored_session != session_id:
            _set_state(conn, redemption_id, tenant_id, "reconciliation_required", event_type="checkout_identity_conflict",
                       stripe_event_id=stripe_event_id, reason_code="checkout_session_mismatch")
            return
        if not stored_session:
            cur.execute("UPDATE public.billing_promotion_redemptions SET stripe_checkout_session_id=%s,updated_at=NOW() "
                        "WHERE redemption_id=%s AND tenant_id=%s;", (session_id, redemption_id, tenant_id))
        if state == "pending" and not subscription_id and not invoice_id:
            _set_state(conn, redemption_id, tenant_id, "rejected", event_type="checkout_expired",
                       stripe_event_id=stripe_event_id, reason_code="checkout_expired")


def invoice_event(conn, *, tenant_id: str, invoice: dict, subscription_id: str | None,
                  stripe_event_id: str, payment_succeeded: bool) -> None:
    redemption_id = _metadata_redemption(invoice)
    with conn.cursor() as cur:
        if redemption_id:
            cur.execute("SELECT redemption_id FROM public.billing_promotion_redemptions WHERE redemption_id=%s AND tenant_id=%s FOR UPDATE;",
                        (redemption_id, tenant_id))
            ids = [r[0] for r in cur.fetchall()]
        elif subscription_id:
            cur.execute("SELECT redemption_id FROM public.billing_promotion_redemptions "
                        "WHERE tenant_id=%s AND stripe_subscription_id=%s AND state IN ('pending','reconciliation_required') FOR UPDATE;",
                        (tenant_id, subscription_id))
            ids = [r[0] for r in cur.fetchall()]
        else:
            ids = []
    if len(ids) > 1:
        for rid in ids:
            _set_state(conn, rid, tenant_id, "reconciliation_required", event_type="invoice_identity_conflict",
                       stripe_event_id=stripe_event_id, reason_code="multiple_redemption_candidates")
        return
    if not ids:
        return
    rid = ids[0]
    with conn.cursor() as cur:
        cur.execute("SELECT state,stripe_subscription_id FROM public.billing_promotion_redemptions "
                    "WHERE redemption_id=%s AND tenant_id=%s FOR UPDATE;", (rid, tenant_id))
        prior = cur.fetchone()
        if not prior or prior[0] == "rejected":
            return
        stored_sub = prior[1]
        billing_reason = invoice.get("billing_reason")
        invoice_id = invoice.get("id")
        if not payment_succeeded:
            # A payment failure or open invoice is not a final redemption and
            # may later settle; keep its reservation pending.
            return
        if billing_reason is None:
            _set_state(conn, rid, tenant_id, "reconciliation_required", event_type="invoice_identity_conflict",
                       stripe_event_id=stripe_event_id, subscription_id=subscription_id, invoice_id=invoice_id,
                       reason_code="billing_reason_missing")
            return
        if billing_reason != "subscription_create":
            # Renewal/other invoices are unrelated to the qualifying initial
            # redemption. They cannot settle it or permanently consume it.
            return
        if not invoice_id or not subscription_id:
            _set_state(conn, rid, tenant_id, "reconciliation_required", event_type="invoice_not_qualifying",
                       stripe_event_id=stripe_event_id, subscription_id=subscription_id, invoice_id=invoice_id,
                       reason_code="initial_invoice_identity_missing")
            return
        if stored_sub and str(stored_sub) != str(subscription_id):
            _set_state(conn, rid, tenant_id, "reconciliation_required", event_type="invoice_identity_conflict",
                       stripe_event_id=stripe_event_id, subscription_id=subscription_id, invoice_id=invoice_id,
                       reason_code="subscription_identity_mismatch")
            return
        paid = invoice.get("status") == "paid" or invoice.get("paid") is True
        # A valid zero-total invoice is paid with amount_paid == 0. Amount is
        # deliberately not used as the settlement test.
        if not paid:
            return
        cur.execute("SELECT 1 FROM public.billing_payments WHERE tenant_id=%s AND stripe_invoice_id=%s "
                    "AND stripe_subscription_id=%s AND status='succeeded';",
                    (tenant_id, invoice_id, subscription_id))
        if not cur.fetchone():
            _set_state(conn, rid, tenant_id, "reconciliation_required", event_type="payment_record_missing",
                       stripe_event_id=stripe_event_id, subscription_id=subscription_id, invoice_id=invoice_id,
                       reason_code="settled_payment_record_unverified")
            return
        _set_state(conn, rid, tenant_id, "settled", event_type="initial_invoice_settled",
                   stripe_event_id=stripe_event_id, subscription_id=subscription_id, invoice_id=invoice_id)
