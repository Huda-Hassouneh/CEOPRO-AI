"""
Operator actions on prices, spending controls, Custom contracts and credit
adjustments - used by scripts/billing_admin.py, never by a customer API.
Each one writes entitlement_audit_log (who approved it, why, against which
contract) in the same transaction as the change. Callers pass a system
connection and commit.
"""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Optional

from src.ai.billing import credits
from src.ai.core import usage

PER_MILLION_UNITS = ("input_token", "output_token", "cache_read_token", "cache_write_token")
_NUMERIC_CONTRACT_FEATURES = (
    usage.TRACKED_PRODUCTS, usage.MONTHLY_REPORTS, usage.TEAM_SEATS, usage.DATA_CREDITS, usage.AI_CREDITS,
    usage.DOCUMENT_STORAGE_MB, usage.CONNECTED_DATA_SOURCES, usage.IMAGE_GENERATION, usage.SENTIMENT_ANALYSIS,
    usage.DOCUMENT_EXTRACTION, usage.RAG_ASSISTANT, usage.WEB_SEARCHES, usage.TRACKED_COMPETITORS,
)
_CUSTOM_CONTRACT_ENTITLEMENTS = (
    usage.MARKET_INTELLIGENCE, usage.DEMAND_PREDICTION, usage.COMPETITOR_MANAGEMENT,
)


class AdminError(ValueError):
    pass



def set_plan_feature(conn, *, plan_key: str, feature_code: str, included: bool,
                     limit_value: Optional[int], approved_by: str, reason: str) -> dict:
    """Change the latest plan allowance. Existing assignments keep their
    immutable catalog_snapshot; new assignments receive the new catalog terms.
    """
    plan_key, feature_code = _require(plan_key, "plan_key"), _require(feature_code, "feature_code")
    approved_by, reason = _require(approved_by, "approved_by"), _require(reason, "reason")
    if not isinstance(included, bool):
        raise AdminError("included must be boolean")
    if limit_value is not None and (isinstance(limit_value, bool) or not isinstance(limit_value, int) or limit_value < 0):
        raise AdminError("limit_value must be a nonnegative integer or null")

    numeric = set(_NUMERIC_CONTRACT_FEATURES)
    modules = set(_CUSTOM_CONTRACT_ENTITLEMENTS)
    if feature_code not in numeric | modules:
        raise AdminError("feature is not supported by the Python plan entitlement catalog")
    if feature_code in modules and limit_value is not None:
        raise AdminError("module entitlements do not accept a numeric limit")

    with conn.cursor() as cursor:
        cursor.execute("SELECT plan_key FROM public.usage_plans WHERE plan_key=%s FOR UPDATE;", (plan_key,))
        if cursor.fetchone() is None:
            raise AdminError("plan not found")
        cursor.execute("SELECT feature_code FROM public.usage_features WHERE feature_code=%s;", (feature_code,))
        if cursor.fetchone() is None:
            raise AdminError("feature is not present in the canonical feature catalog")

        if feature_code in numeric:
            cursor.execute("SELECT limit_value FROM public.usage_plan_limits WHERE plan_key=%s AND feature_code=%s FOR UPDATE;",
                           (plan_key, feature_code))
            old = cursor.fetchone()
            old_value = {"included": old is not None, "limit_value": old[0] if old else None}
            if included:
                cursor.execute("""
                    INSERT INTO public.usage_plan_limits(plan_key,feature_code,limit_value)
                    VALUES(%s,%s,%s)
                    ON CONFLICT(plan_key,feature_code) DO UPDATE SET limit_value=EXCLUDED.limit_value;
                """, (plan_key, feature_code, limit_value))
                new_value = {"included": True, "limit_value": limit_value}
            else:
                cursor.execute("DELETE FROM public.usage_plan_limits WHERE plan_key=%s AND feature_code=%s;",
                               (plan_key, feature_code))
                new_value = {"included": False, "limit_value": None}
        else:
            cursor.execute("SELECT 1 FROM public.usage_plan_entitlements WHERE plan_key=%s AND feature_code=%s FOR UPDATE;",
                           (plan_key, feature_code))
            old_value = {"included": cursor.fetchone() is not None, "limit_value": None}
            if included:
                cursor.execute("""
                    INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(%s,%s)
                    ON CONFLICT(plan_key,feature_code) DO NOTHING;
                """, (plan_key, feature_code))
            else:
                cursor.execute("DELETE FROM public.usage_plan_entitlements WHERE plan_key=%s AND feature_code=%s;",
                               (plan_key, feature_code))
            new_value = {"included": included, "limit_value": None}

        cursor.execute("""
            INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
            VALUES(%s,'owner','plan_feature_update',%s,%s::jsonb,%s::jsonb,%s,'succeeded');
        """, (approved_by, f"plan:{plan_key}:{feature_code}", json.dumps(old_value), json.dumps(new_value), reason))
    return {"plan_key": plan_key, "feature_code": feature_code, **new_value,
            "catalog_versioned": True, "existing_assignments_preserved": True}


def _require(value: Optional[str], name: str) -> str:
    if not value or not str(value).strip():
        raise AdminError(f"{name} is required")
    return str(value).strip()


def _audit(cursor, tenant_id: Optional[str], action: str, subject: str, old, new, approved_by: str, reason: str,
           contract_ref: Optional[str] = None) -> None:
    cursor.execute(
        """
        INSERT INTO entitlement_audit_log (tenant_id, action, subject, old_value, new_value, contract_ref, approved_by, reason)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s);
        """,
        (tenant_id, action, subject, json.dumps(old, default=str), json.dumps(new, default=str), contract_ref,
         approved_by, reason),
    )


def set_price(conn, *, budget_kind: str, provider: str, operation: str, unit: str, unit_cost_usd: Decimal,
              source: str, verified_on: date, approved_by: str, reason: str,
              safety_margin: Optional[Decimal] = None, charged_on_failure: bool = True, cost_is_final: bool = True,
              if_missing: bool = False) -> bool:
    """Records a provider's confirmed price (per unit, in USD). With
    if_missing, a price already recorded is kept unchanged. Returns whether
    the price was written."""
    approved_by, reason, source = _require(approved_by, "approved_by"), _require(reason, "reason"), _require(source, "source")
    if budget_kind not in (credits.DATA, credits.AI):
        raise AdminError("budget must be data or ai")
    if Decimal(unit_cost_usd) < 0:
        raise AdminError("a price can't be negative")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT unit_cost_usd, safety_margin, source FROM provider_cost_schedules "
            "WHERE budget_kind = %s AND provider = %s AND operation = %s AND unit = %s;",
            (budget_kind, provider, operation, unit),
        )
        old = cursor.fetchone()
        if if_missing and old and old[0] is not None:
            return False
        cursor.execute(
            """
            INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin,
                                                 charged_on_failure, cost_is_final, source, verified_at, configured_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (budget_kind, provider, operation, unit) DO UPDATE SET
                unit_cost_usd = EXCLUDED.unit_cost_usd, safety_margin = EXCLUDED.safety_margin,
                charged_on_failure = EXCLUDED.charged_on_failure, cost_is_final = EXCLUDED.cost_is_final,
                source = EXCLUDED.source, verified_at = EXCLUDED.verified_at, configured_by = EXCLUDED.configured_by,
                updated_at = NOW();
            """,
            (budget_kind, provider, operation, unit, Decimal(unit_cost_usd), safety_margin, charged_on_failure,
             cost_is_final, source, verified_on, approved_by),
        )
        _audit(cursor, None, "set_price", f"{budget_kind}:{provider}:{operation}:{unit}",
               None if not old else {"unit_cost_usd": old[0], "safety_margin": old[1], "source": old[2]},
               {"unit_cost_usd": Decimal(unit_cost_usd), "safety_margin": safety_margin, "source": source,
                "verified_on": verified_on}, approved_by, reason)
    return True


def set_control(conn, *, provider: str, approved_by: str, reason: str, monthly_cap_usd: Optional[Decimal] = None,
                clear_cap: bool = False, kill_switch: Optional[bool] = None) -> None:
    """A platform spending cap and/or kill switch for a provider ('*' = all,
    'provider:model' = one AI model)."""
    approved_by, reason = _require(approved_by, "approved_by"), _require(reason, "reason")
    with conn.cursor() as cursor:
        cursor.execute("SELECT monthly_cap_usd, kill_switch FROM provider_spend_controls WHERE provider = %s;", (provider,))
        old = cursor.fetchone()
        cap = None if clear_cap else (monthly_cap_usd if monthly_cap_usd is not None else (old[0] if old else None))
        kill = kill_switch if kill_switch is not None else (old[1] if old else False)
        cursor.execute(
            """
            INSERT INTO provider_spend_controls (provider, monthly_cap_usd, kill_switch, reason, updated_by)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (provider) DO UPDATE SET monthly_cap_usd = EXCLUDED.monthly_cap_usd,
                kill_switch = EXCLUDED.kill_switch, reason = EXCLUDED.reason, updated_by = EXCLUDED.updated_by,
                updated_at = NOW();
            """,
            (provider, cap, kill, reason, approved_by),
        )
        _audit(cursor, None, "set_spend_control", provider,
               None if not old else {"monthly_cap_usd": old[0], "kill_switch": old[1]},
               {"monthly_cap_usd": cap, "kill_switch": kill}, approved_by, reason)

def set_custom_contract(conn, *, tenant_id: str, contract_ref: str, approved_by: str, reason: str,
                        limits: Dict[str, int], monthly_price: Optional[Decimal] = None, currency: str = "USD",
                        trial_days: int = 0, data_sources: Optional[list] = None,
                        included_features: Optional[list[str]] = None,
                        refresh_frequency: Optional[str] = None, support_level: Optional[str] = None,
                        period_months: int = 1, today: Optional[date] = None) -> None:
    """Puts a company on an approved Custom contract: its terms, its own
    limits (replacing the plan's), and the Custom plan for the contract
    period. Only what is listed changes; everything is audited."""
    contract_ref = _require(contract_ref, "contract_ref")
    approved_by, reason = _require(approved_by, "approved_by"), _require(reason, "reason")
    unknown = [f for f in limits if f not in _NUMERIC_CONTRACT_FEATURES]
    if unknown:
        raise AdminError(f"unknown contract limits: {', '.join(unknown)}")
    if included_features is not None:
        unknown_features = sorted(set(included_features) - set(_CUSTOM_CONTRACT_ENTITLEMENTS))
        if unknown_features:
            raise AdminError(f"unknown custom contract entitlements: {', '.join(unknown_features)}")
    if any(int(v) < 0 for v in limits.values()):
        raise AdminError("contract limits can't be negative")
    if not 0 <= int(trial_days) <= 90:
        raise AdminError("trial_days must be 0-90")
    today = today or datetime.now(timezone.utc).date()
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM companies WHERE tenant_id = %s;", (tenant_id,))
        if not cursor.fetchone():
            raise AdminError("no company with that id")
        cursor.execute(
            "SELECT contract_ref, monthly_price, trial_days, refresh_frequency, support_level, included_features FROM tenant_custom_contracts "
            "WHERE tenant_id = %s;", (tenant_id,),
        )
        old_contract = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO tenant_custom_contracts (tenant_id, contract_ref, monthly_price, currency, trial_days, data_sources,
                                                 included_features, refresh_frequency, support_level, approved_by, reason)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET contract_ref = EXCLUDED.contract_ref, monthly_price = EXCLUDED.monthly_price,
                currency = EXCLUDED.currency, trial_days = EXCLUDED.trial_days, data_sources = EXCLUDED.data_sources,
                included_features = COALESCE(EXCLUDED.included_features, tenant_custom_contracts.included_features),
                refresh_frequency = EXCLUDED.refresh_frequency, support_level = EXCLUDED.support_level,
                approved_by = EXCLUDED.approved_by, reason = EXCLUDED.reason, approved_at = NOW();
            """,
            (tenant_id, contract_ref, monthly_price, currency, int(trial_days), json.dumps(data_sources or []),
             None if included_features is None else json.dumps(sorted(set(included_features))),
             refresh_frequency, support_level, approved_by, reason),
        )
        _audit(cursor, tenant_id, "set_contract", contract_ref,
               None if not old_contract else dict(zip(("contract_ref", "monthly_price", "trial_days", "refresh_frequency",
                                                         "support_level", "included_features"), old_contract)),
               {"monthly_price": monthly_price, "currency": currency, "trial_days": trial_days,
                "data_sources": data_sources or [],
                "included_features": None if included_features is None else sorted(set(included_features)),
                "refresh_frequency": refresh_frequency, "support_level": support_level},
               approved_by, reason, contract_ref)
        for feature, value in sorted(limits.items()):
            cursor.execute("SELECT limit_value FROM tenant_entitlement_overrides WHERE tenant_id = %s AND feature_code = %s;",
                           (tenant_id, feature))
            old = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO tenant_entitlement_overrides (tenant_id, feature_code, limit_value, contract_ref, approved_by, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, feature_code) DO UPDATE SET limit_value = EXCLUDED.limit_value,
                    contract_ref = EXCLUDED.contract_ref, approved_by = EXCLUDED.approved_by, reason = EXCLUDED.reason,
                    approved_at = NOW();
                """,
                (tenant_id, feature, int(value), contract_ref, approved_by, reason),
            )
            _audit(cursor, tenant_id, "set_limit", feature, None if not old else {"limit": old[0]}, {"limit": int(value)},
                   approved_by, reason, contract_ref)
        # A contract trial lasts trial_days; otherwise the contract period.
        start = today
        if trial_days:
            end = today + timedelta(days=int(trial_days) - 1)
        else:
            end = date(today.year + (today.month - 1 + period_months) // 12, (today.month - 1 + period_months) % 12 + 1,
                       1) - timedelta(days=1)
        cursor.execute(
            """
            INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source)
            VALUES (%s, 'custom', %s, %s, %s, 'contract')
            ON CONFLICT (tenant_id) DO UPDATE SET plan_key = 'custom', status = EXCLUDED.status,
                current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end,
                source = 'contract', updated_at = CURRENT_TIMESTAMP;
            """,
            (tenant_id, "trialing" if trial_days else "active", start, end),
        )


def adjust_credits(conn, *, tenant_id: str, budget_kind: str, credits_delta: Decimal, reference: str,
                   approved_by: str, reason: str) -> None:
    """A manual credit (negative delta: gives credits back) or debit for this
    period, as an append-only adjustment. Never automatic."""
    reference, approved_by, reason = (_require(reference, "reference"), _require(approved_by, "approved_by"),
                                      _require(reason, "reason"))
    plan = usage.get_plan(conn, tenant_id)
    delta = Decimal(str(credits_delta))
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO usage_ledger_adjustments (tenant_id, budget_kind, period_start, credits_delta, kind, reference, reason, actor)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, reference) DO NOTHING RETURNING adjustment_id;
            """,
            (tenant_id, budget_kind, plan["period_start"], delta, "admin_debit" if delta > 0 else "admin_credit",
             reference, reason, approved_by),
        )
        if cursor.fetchone() is None:
            raise AdminError("an adjustment with this reference already exists")
        cursor.execute(
            """
            INSERT INTO tenant_credit_balances (tenant_id, budget_kind, period_start, period_end, consumed_credits)
            VALUES (%s, %s, %s, %s, GREATEST(0, %s))
            ON CONFLICT (tenant_id, budget_kind, period_start) DO UPDATE
                SET consumed_credits = GREATEST(0, tenant_credit_balances.consumed_credits + %s), updated_at = NOW();
            """,
            (tenant_id, budget_kind, plan["period_start"], plan["period_end"], delta, delta),
        )
        _audit(cursor, tenant_id, "adjust_credits", budget_kind, None, {"credits_delta": delta, "reference": reference},
               approved_by, reason)