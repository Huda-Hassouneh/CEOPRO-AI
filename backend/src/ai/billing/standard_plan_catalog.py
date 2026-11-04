"""Validated bootstrap/templates; never an entitlement or pricing evaluator.

Setup installs immutable catalog versions. Runtime authoring consumes the installed
version through the owner SQL command; changing this file cannot rewrite a plan.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from src.ai.core import feature_contracts as usage

CATALOG_PATH = Path(__file__).resolve().parents[3] / "config/billing/standard_plan_catalog.json"


class CatalogInvalid(ValueError):
    pass


def _unique(rows, key):
    keys = [r[key] for r in rows]
    if len(keys) != len(set(keys)):
        raise CatalogInvalid(f"Duplicate {key}")
    return set(keys)


def _integer(value):
    return type(value) is int and 0 <= value <= 9223372036854775807


def _fields(row, fields):
    if set(row) != set(fields.split()):
        raise CatalogInvalid("Unknown or missing catalog fields")


def validate_catalog(data, usage_features=None):
    """Reject ambiguous identities/units and omitted vs unlimited allowances."""
    try:
        _fields(data, 'schema_version catalog_version purpose categories features plans unsupported_quantitative_configuration')
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or not data["catalog_version"] or len(data["catalog_version"]) > 30:
            raise CatalogInvalid("Unsupported catalog version")
        categories = _unique(data["categories"], "key")
        keys = _unique(data["features"], "key")
        expected = set(usage.COMMERCIAL_QUANTITATIVE_FEATURES + usage.MODULE_FEATURES + usage.BASELINE_ENTITLEMENTS)
        if keys != expected:
            raise CatalogInvalid(f"Unknown, platform-only or missing canonical features: {sorted(keys ^ expected)}")
        for row in data["categories"] + data["features"]:
            if not row["label_en"] or not row["label_ar"] or not _integer(row["display_order"]):
                raise CatalogInvalid("Localized labels and display order required")
        for category in data['categories']:
            _fields(category, 'key label_en label_ar display_order')
        for f in data["features"]:
            _fields(f, 'key category label_en label_ar description_en description_ar display_order entitlement_type usage_feature unit aggregation_type reset_cycle')
            if f["category"] not in categories:
                raise CatalogInvalid("Unknown category")
            numeric = f["key"] in usage.COMMERCIAL_QUANTITATIVE_FEATURES
            kind = f["entitlement_type"]
            if (numeric and kind not in {"max", "consumable", "credits", "storage"}) or (not numeric and kind != "boolean"):
                raise CatalogInvalid("Invalid entitlement type")
            if numeric and ((kind == 'credits') != (f['key'] in usage.CREDIT_FEATURES)
                or (kind == 'storage') != (f['key'] == usage.DOCUMENT_STORAGE_MB)):
                raise CatalogInvalid("Invalid canonical credit/storage allowance type")
            if f["usage_feature"] != (f["key"] if f["key"] not in usage.BASELINE_ENTITLEMENTS else None):
                raise CatalogInvalid("Invalid canonical usage reference")
            if f["usage_feature"]:
                if f["aggregation_type"] not in {"sum", "max"} or f["reset_cycle"] not in {"billing_period", "lifetime"} or not f["unit"]:
                    raise CatalogInvalid("Invalid usage definition")
                if numeric and ((kind in {"max", "storage"}) != (f["aggregation_type"] == "max")):
                    raise CatalogInvalid("Entitlement type contradicts usage aggregation")
                if usage_features is not None and usage_features.get(f["key"]) != (f["unit"], f["aggregation_type"], f["reset_cycle"]):
                    raise CatalogInvalid(f"Executable usage definition differs: {f['key']}")
        if _unique(data["plans"], "plan_key") != {"starter", "growth", "enterprise"}:
            raise CatalogInvalid("Only the stable Standard/Plus/Pro template identities are supported")
        for p in data["plans"]:
            _fields(p, 'plan_key display_name display_name_ar tier_level trial_days bootstrap_active features allowances bootstrap_commercial_defaults allowance_source')
            if type(p['bootstrap_active']) is not bool or not p['display_name'] or not p['display_name_ar']:
                raise CatalogInvalid('Invalid plan presentation/state')
            if len(p["features"]) != len(set(p["features"])) or set(p["features"]) != keys:
                raise CatalogInvalid("Duplicate, unknown or missing all-features assignment")
            if not _integer(p["tier_level"]) or not 1 <= p["tier_level"] or not _integer(p["trial_days"]) or p["trial_days"] > 365:
                raise CatalogInvalid("Invalid plan terms")
            if _unique(p["allowances"], "feature_key") != set(usage.COMMERCIAL_QUANTITATIVE_FEATURES):
                raise CatalogInvalid("Invalid allowance reference or missing allowance state")
            for a in p["allowances"]:
                _fields(a, 'feature_key state value trial_value')
                if a["state"] not in {"limited", "unlimited", "owner_required"}:
                    raise CatalogInvalid("Invalid allowance state")
                if (a["state"] == "limited" and not _integer(a["value"])) or (a["state"] != "limited" and a["value"] is not None):
                    raise CatalogInvalid("Invalid numeric allowance; missing is not unlimited")
                if a["trial_value"] is not None and not _integer(a["trial_value"]):
                    raise CatalogInvalid("Invalid trial allowance")
            price = p["bootstrap_commercial_defaults"]
            _fields(price, 'source currency monthly_price billing_periods')
            monthly = Decimal(price["monthly_price"])
            if price["currency"] != "USD" or not monthly.is_finite() or monthly < 0 or monthly != monthly.quantize(Decimal('.01')):
                raise CatalogInvalid("Invalid bootstrap commercial terms")
            periods = price["billing_periods"]
            _unique(periods, "period_code")
            for period in periods:
                _fields(period, 'period_code discount_percent')
                discount = Decimal(period["discount_percent"])
                if period["period_code"] not in {"three-months", "six-months", "yearly"} or not discount.is_finite() or not 0 <= discount < 100:
                    raise CatalogInvalid("Invalid billing period")
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise CatalogInvalid(f"Malformed Standard Plan catalog: {exc}") from exc
    return data


def load_catalog(path=CATALOG_PATH):
    return validate_catalog(json.loads(Path(path).read_text(encoding="utf-8")))


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def install_catalog(conn, *, fresh=False):
    """Installation authority only, caller commits. Existing plans are never patched.

    On a brand-new schema the immutable historical migrations already create the
    old defaults. Only then may setup replace those three seed definitions. On
    subsequent setup even a missing allowance is an owner decision, not drift.
    """
    from psycopg2.extras import Json

    data = load_catalog()
    with conn.cursor() as cur:
        cur.execute("SELECT feature_code,unit,aggregation_type,reset_cycle FROM public.usage_features")
        validate_catalog(data, {r[0]: tuple(r[1:]) for r in cur.fetchall()})
        cur.execute("SELECT public.billing_standard_catalog_install(%s,%s,%s)",
                    (Json(data), fingerprint(data), fresh))
        return cur.fetchone()[0]


def installed_catalog(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT catalog FROM public.billing_standard_catalog_versions ORDER BY installed_at DESC,catalog_version DESC LIMIT 1")
        row = cur.fetchone()
    if not row:
        raise CatalogInvalid("Standard Plan templates have not been installed by setup")
    return row[0]


def presentation(data):
    """Public display metadata only. Owner feature labels take precedence."""
    categories = {r['key']: r for r in data['categories']}
    return {f['key']: dict(name=f['label_en'], name_ar=f['label_ar'],
                          description=f['description_en'], description_ar=f['description_ar'],
                          category=categories[f['category']], display_order=f['display_order'])
            for f in data['features']}
