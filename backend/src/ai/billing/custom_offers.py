"""Custom-offer configuration validation and durable lifecycle adapters."""
from src.ai.billing import admin


class CustomOfferError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_CADENCES = ("hourly", "daily", "weekly")
_MODULE_FEATURES = (
    admin.usage.MARKET_INTELLIGENCE,
    admin.usage.DEMAND_PREDICTION,
    admin.usage.COMPETITOR_MANAGEMENT,
)


def module_catalog() -> list[dict]:
    """Module entitlements are separate from numeric allowance limits."""
    return [{"featureCode": code, "selectionKind": "included_feature"} for code in _MODULE_FEATURES]


def feature_catalog(conn) -> list[dict]:
    """Return the existing canonical feature units supported by private limits."""
    supported = tuple(sorted(admin._NUMERIC_CONTRACT_FEATURES))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT feature_code, unit, aggregation_type, reset_cycle
            FROM usage_features
            WHERE feature_code = ANY(%s)
            ORDER BY feature_code;
            """,
            (list(supported),),
        )
        rows = cursor.fetchall()

    by_code = {
        code: {
            "featureCode": code,
            "unit": unit,
            "aggregationType": aggregation,
            "resetCycle": reset_cycle,
            "quantityKind": "nonnegative_integer",
            # tenant_entitlement_overrides.limit_value is NOT NULL. Missing
            # means no override; it is not an unlimited grant.
            "unlimitedOverrideSupported": False,
        }
        for code, unit, aggregation, reset_cycle in rows
    }
    return [by_code[code] for code in supported if code in by_code]


def validate_configuration(conn, *, limits: dict, refresh_frequency: str | None,
                           enabled_features: list[str] | None = None) -> dict:
    """Validate representation only; do not infer approval or price eligibility."""
    if not isinstance(limits, dict):
        raise CustomOfferError(422, "invalid_configuration", "Feature quantities must be an object.")

    catalog = {item["featureCode"]: item for item in feature_catalog(conn)}
    unsupported = sorted(set(limits) - set(admin._NUMERIC_CONTRACT_FEATURES))
    if unsupported:
        raise CustomOfferError(422, "unsupported_feature", "One or more feature quantities are not supported.")

    missing_catalog = sorted(set(limits) - set(catalog))
    if missing_catalog:
        raise CustomOfferError(409, "feature_unmapped", "A requested feature has no verified Python unit mapping.")

    normalized: dict[str, int] = {}
    for code, value in limits.items():
        # bool is a Python int subclass, but is not a quantity.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CustomOfferError(422, "invalid_quantity", "Feature quantities must be nonnegative integers.")
        normalized[code] = value

    if enabled_features is None:
        enabled_features = []
    if (not isinstance(enabled_features, list)
            or any(not isinstance(code, str) for code in enabled_features)
            or len(enabled_features) != len(set(enabled_features))):
        raise CustomOfferError(422, "invalid_enabled_features", "Included features must be a unique list of feature codes.")
    unsupported_modules = sorted(set(enabled_features) - set(_MODULE_FEATURES))
    if unsupported_modules:
        raise CustomOfferError(422, "unsupported_enabled_feature", "One or more included features are not supported.")
    enabled_features = sorted(enabled_features)
    if not enabled_features and not any(value > 0 for value in normalized.values()):
        raise CustomOfferError(422, "empty_configuration", "Select at least one included feature or positive allowance.")

    if refresh_frequency is not None and refresh_frequency not in _CADENCES:
        raise CustomOfferError(422, "invalid_refresh_frequency", "Refresh frequency is not supported by the existing contract schema.")

    monitoring = admin.usage.COMPETITOR_MANAGEMENT in enabled_features
    tracked = normalized.get("tracked_competitors", 0)
    if monitoring and tracked <= 0:
        raise CustomOfferError(422, "feature_dependency", "Competitor monitoring requires a positive tracked-competitor allowance.")
    if monitoring and refresh_frequency is None:
        raise CustomOfferError(422, "feature_dependency", "Competitor monitoring requires an explicit monitoring frequency.")
    if tracked > 0 and not monitoring:
        raise CustomOfferError(422, "feature_dependency", "A tracked-competitor allowance requires competitor monitoring.")
    if refresh_frequency is not None and not monitoring:
        raise CustomOfferError(422, "feature_dependency", "Monitoring frequency requires competitor monitoring to be enabled.")

    return {
        "version": 1,
        "valid": True,
        "saved": False,
        "priceCalculated": False,
        "rightsChanged": False,
        "operatorReviewRequired": True,
        "configuration": {"limits": normalized, "enabledFeatures": enabled_features,
                           "refreshFrequency": refresh_frequency},
        "limitStates": {
            code: "explicit_zero" if value == 0 else "limited"
            for code, value in normalized.items()
        },
    }

# Durable quote lifecycle. All mutations pass through migration 93's
# SECURITY DEFINER command, which independently validates the connection's
# authenticated principal and tenant/platform authority. No function here
# writes subscriptions, entitlements, usage, payments, or Credits.
import hashlib
import json


def _canonical_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Unsupported quote value type: {type(value).__name__}")


def quote_command(conn, action: str, payload: dict) -> dict:
    """Invoke the narrow database write API with no client-provided actor identity."""
    import psycopg2
    from psycopg2.extras import Json

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT public.billing_custom_quote_command(%s, %s::jsonb);",
                (action, Json(payload, dumps=lambda value: json.dumps(value, default=_json_value))),
            )
            row = cursor.fetchone()
        return row[0]
    except psycopg2.Error as exc:
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise CustomOfferError(403, "quote_forbidden", "This quote operation is not authorized.") from None
        if code == "P0002":
            raise CustomOfferError(404, "quote_not_found", "The quote was not found.") from None
        if code in {"23505", "40001"}:
            raise CustomOfferError(409, "quote_conflict", "The quote changed or this request identity conflicts.") from None
        if code in {"55000", "23503"}:
            raise CustomOfferError(409, "quote_transition_invalid", "The quote cannot make that transition.") from None
        if code == "22023":
            raise CustomOfferError(422, "quote_request_invalid", "The quote request is incomplete or invalid.") from None
        raise


def pricing_admin_command(conn, action: str, payload: dict) -> dict:
    """Owner-only, database-authorized pricing administration operation."""
    import psycopg2
    from psycopg2.extras import Json
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_custom_pricing_admin_command(%s,%s::jsonb);",
                           (action, Json(payload)))
            return cursor.fetchone()[0]
    except psycopg2.Error as exc:
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise CustomOfferError(403, "platform_owner_required", "Platform Owner permission is required.") from None
        if code in {"55000", "23P01"}:
            raise CustomOfferError(409, "pricing_configuration_conflict", "Pricing configuration conflicts with an existing version.") from None
        if code in {"22023", "23503", "23514"}:
            raise CustomOfferError(422, "pricing_configuration_invalid", "Pricing configuration is incomplete or invalid.") from None
        raise


def attach_pricing_snapshot(conn, *, quote_id: str, snapshot: dict) -> dict:
    import psycopg2
    from psycopg2.extras import Json
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_custom_quote_pricing_command(%s::jsonb);",
                           (Json({"quote_id": quote_id, "pricing_snapshot": snapshot}),))
            return cursor.fetchone()[0]
    except psycopg2.Error as exc:
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise CustomOfferError(403, "platform_owner_required", "Platform Owner permission is required.") from None
        if code in {"55000", "23503"}:
            raise CustomOfferError(409, "quote_not_priceable", "The quote revision cannot accept this pricing snapshot.") from None
        if code == "22023":
            raise CustomOfferError(422, "pricing_snapshot_invalid", "A valid calculated pricing snapshot is required.") from None
        raise


def create_draft(conn, *, tenant_id: str, customer_user_id: str | None, idempotency_key: str,
                 configuration: dict, feature_quantities: dict, commercial_terms: dict,
                 economic_inputs: dict, fx_evidence: dict, valid_until=None) -> dict:
    validate_configuration(conn, limits=feature_quantities,
                           enabled_features=configuration.get("enabledFeatures") or [],
                           refresh_frequency=(configuration.get("refreshFrequency") or configuration.get("refresh_frequency")))
    body = {
        "tenant_id": tenant_id, "customer_user_id": customer_user_id,
        "configuration": configuration, "feature_quantities": feature_quantities,
        "commercial_terms": commercial_terms, "economic_inputs": economic_inputs,
        "fx_evidence": fx_evidence, "valid_until": valid_until,
    }
    return quote_command(conn, "create_draft", {
        **body, "idempotency_key": idempotency_key,
        "request_fingerprint": _canonical_fingerprint(body),
    })


def request_quote(conn, *, tenant_id: str, customer_user_id: str, idempotency_key: str,
                  configuration: dict, feature_quantities: dict) -> dict:
    """Persist a tenant-authenticated request for operator review, without price or rights."""
    validate_configuration(conn, limits=feature_quantities,
                           enabled_features=configuration.get("enabledFeatures") or [],
                           refresh_frequency=(configuration.get("refreshFrequency") or configuration.get("refresh_frequency")))
    body = {
        "tenant_id": tenant_id, "customer_user_id": customer_user_id,
        "configuration": configuration, "feature_quantities": feature_quantities,
    }
    return quote_command(conn, "request", {
        **body, "idempotency_key": idempotency_key,
        "request_fingerprint": _canonical_fingerprint(body),
    })


def create_revision(conn, *, quote_id: str, expected_revision: int, idempotency_key: str,
                    configuration: dict, feature_quantities: dict, commercial_terms: dict,
                    economic_inputs: dict, fx_evidence: dict, valid_until=None) -> dict:
    validate_configuration(conn, limits=feature_quantities,
                           enabled_features=configuration.get("enabledFeatures") or [],
                           refresh_frequency=(configuration.get("refreshFrequency") or configuration.get("refresh_frequency")))
    body = {
        "quote_id": quote_id, "expected_revision": expected_revision,
        "configuration": configuration, "feature_quantities": feature_quantities,
        "commercial_terms": commercial_terms, "economic_inputs": economic_inputs,
        "fx_evidence": fx_evidence, "valid_until": valid_until,
    }
    return quote_command(conn, "create_revision", {
        **body, "idempotency_key": idempotency_key,
        "request_fingerprint": _canonical_fingerprint(body),
    })


def transition(conn, action: str, *, tenant_id: str | None, quote_id: str,
               expected_revision: int, idempotency_key: str | None = None,
               approval_reference: str | None = None) -> dict:
    body = {
        "tenant_id": tenant_id, "quote_id": quote_id,
        "expected_revision": expected_revision,
        "idempotency_key": idempotency_key,
        "approval_reference": approval_reference,
    }
    body["request_fingerprint"] = _canonical_fingerprint(body)
    return quote_command(conn, action, body)


def prepare_checkout_attempt(conn, *, tenant_id: str, quote_id: str,
                             idempotency_key: str) -> dict:
    """Persist correlation identity only. This does not contact Stripe."""
    body = {"tenant_id": tenant_id, "quote_id": quote_id}
    return quote_command(conn, "checkout_prepare", {
        **body, "idempotency_key": idempotency_key,
        "request_fingerprint": _canonical_fingerprint(body),
    })


def custom_checkout_prepare(conn, *, quote_id: str, idempotency_key: str) -> dict:
    import psycopg2
    from psycopg2.extras import Json
    body = {"quote_id": quote_id}
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_custom_checkout_prepare(%s::jsonb);", (Json({
                **body, "idempotency_key": idempotency_key,
                "request_fingerprint": _canonical_fingerprint(body),
            }),))
            return cursor.fetchone()[0]
    except psycopg2.Error as exc:
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise CustomOfferError(403, "billing_role_required", "A tenant billing role is required.") from None
        if code == "P0002":
            raise CustomOfferError(404, "quote_not_found", "The quote was not found.") from None
        if code in {"55000", "23505", "40001"}:
            raise CustomOfferError(409, "quote_not_checkoutable", "This Custom Plan offer is no longer eligible for checkout.") from None
        if code == "22023":
            raise CustomOfferError(422, "checkout_request_invalid", "Checkout request is invalid.") from None
        raise


def record_custom_checkout_session(conn, *, attempt_id: str, session_id: str) -> dict:
    import psycopg2
    from psycopg2.extras import Json
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_custom_checkout_record_session(%s::jsonb);",
                           (Json({"attempt_id": attempt_id, "session_id": session_id}),))
            return cursor.fetchone()[0]
    except psycopg2.Error as exc:
        code = getattr(exc, "pgcode", None)
        if code == "42501":
            raise CustomOfferError(403, "billing_role_required", "A tenant billing role is required.") from None
        if code in {"55000", "23505"}:
            raise CustomOfferError(409, "checkout_attempt_conflict", "The quote or Checkout attempt changed; try again.") from None
        if code == "22023":
            raise CustomOfferError(422, "checkout_session_invalid", "The payment provider returned an invalid session.") from None
        raise


def record_verified_checkout_event(conn, *, attempt_id: str, provider_event_id: str) -> dict:
    """Reconcile identity only from a previously verified, processed Stripe event.

    The webhook pipeline owns signature verification and billing reconciliation.
    This helper never calls Stripe and never activates customer access.
    """
    return quote_command(conn, "checkout_identity_update", {
        "attempt_id": attempt_id, "provider_event_id": provider_event_id,
    })


def quote_detail(conn, quote_id: str, *, include_private: bool = False) -> dict | None:
    """Tenant-scoped detail; economic and FX input snapshots are operator-only."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT q.quote_id, q.tenant_id, q.customer_user_id, q.state, q.current_revision_id,
                   q.row_version, q.created_at, q.updated_at,
                   r.revision_number, r.state, r.configuration, r.feature_quantities,
                   r.commercial_terms, r.economic_inputs, r.fx_evidence, r.valid_until,
                   r.approval_reference, r.approved_at, r.accepted_at
              FROM public.billing_custom_quotes q
              LEFT JOIN public.billing_custom_quote_revisions r
                ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id AND r.revision_id=q.current_revision_id
             WHERE q.quote_id=%s;
            """, (quote_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        keys = ("quote_id", "tenant_id", "customer_user_id", "state", "current_revision_id",
                "row_version", "created_at", "updated_at", "revision_number", "revision_state",
                "configuration", "feature_quantities", "commercial_terms", "economic_inputs",
                "fx_evidence", "valid_until", "approval_reference", "approved_at", "accepted_at")
        result = dict(zip(keys, row))
        if not include_private:
            result.pop("economic_inputs", None)
            result.pop("fx_evidence", None)
            result.pop("approval_reference", None)
        cursor.execute(
            "SELECT action, created_at, evidence FROM public.billing_custom_quote_events "
            "WHERE tenant_id=%s AND quote_id=%s ORDER BY created_at,event_id;",
            (result["tenant_id"], quote_id),
        )
        result["events"] = [{"action": action, "created_at": at, "evidence": evidence}
                             for action, at, evidence in cursor.fetchall()]
        if not include_private:
            for event in result["events"]:
                event["evidence"].pop("approval_reference", None)
        if include_private:
            cursor.execute(
                "SELECT attempt_id, revision_id, state, stripe_checkout_session_id, stripe_subscription_id, "
                "stripe_invoice_id, provider_outcome, last_error_code, created_at, updated_at "
                "FROM public.billing_custom_quote_checkout_attempts WHERE tenant_id=%s AND quote_id=%s "
                "ORDER BY created_at,attempt_id;", (result["tenant_id"], quote_id)
            )
            result["checkout_attempts"] = [dict(zip(
                ("attempt_id", "revision_id", "state", "stripe_checkout_session_id", "stripe_subscription_id",
                 "stripe_invoice_id", "provider_outcome", "last_error_code", "created_at", "updated_at"), row
            )) for row in cursor.fetchall()]
        return result


def quote_list(conn, tenant_id: str, *, limit: int = 50) -> list[dict]:
    """List a customer's own tenant quotes; caller must establish tenant RLS context."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise CustomOfferError(422, "invalid_limit", "Quote list limit must be between 1 and 100.")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT quote_id FROM public.billing_custom_quotes WHERE tenant_id=%s "
            "ORDER BY updated_at DESC, quote_id DESC LIMIT %s;", (tenant_id, limit),
        )
        quote_ids = [row[0] for row in cursor.fetchall()]
    return [detail for quote_id in quote_ids
            if (detail := quote_detail(conn, str(quote_id), include_private=False)) is not None]


def admin_quote_list(conn, *, state: str | None = None, quote_id: str | None = None,
                     limit: int = 50) -> list[dict]:
    """Read review queue via a SECURITY DEFINER command that verifies platform ownership."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise CustomOfferError(422, "invalid_limit", "Quote list limit must be between 1 and 100.")
    result = quote_command(conn, "admin_list", {"state": state, "quote_id": quote_id, "limit": limit})
    return result.get("quotes", [])


def admin_quote_detail(conn, quote_id: str) -> dict | None:
    import psycopg2
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT public.billing_custom_quote_admin_detail(%s);", (quote_id,))
            row = cursor.fetchone()
        return row[0] if row else None
    except psycopg2.Error as exc:
        if getattr(exc, "pgcode", None) == "42501":
            raise CustomOfferError(403, "platform_owner_required", "Platform Owner permission is required.") from None
        raise
