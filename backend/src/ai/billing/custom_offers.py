"""Read-only custom-offer configuration compatibility.

This module exposes only feature quantities the existing Python custom
contract writer can represent. It does not persist quotes, calculate prices,
approve terms, activate contracts, or grant rights.
"""
from src.ai.billing import admin


class CustomOfferError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_CADENCES = ("hourly", "daily", "weekly")


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


def validate_configuration(conn, *, limits: dict, refresh_frequency: str | None) -> dict:
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

    if refresh_frequency is not None and refresh_frequency not in _CADENCES:
        raise CustomOfferError(422, "invalid_refresh_frequency", "Refresh frequency is not supported by the existing contract schema.")

    return {
        "version": 1,
        "valid": True,
        "saved": False,
        "priceCalculated": False,
        "rightsChanged": False,
        "operatorReviewRequired": True,
        "configuration": {"limits": normalized, "refreshFrequency": refresh_frequency},
        "limitStates": {
            code: "explicit_zero" if value == 0 else "limited"
            for code, value in normalized.items()
        },
    }
