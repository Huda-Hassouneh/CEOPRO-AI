"""Explicit owner-approved publication; bootstrap never synchronizes owner prices.

Installation credentials stay in the operator CLI. Existing price rows retain
their amounts and Stripe IDs; only availability changes. Callers own commits.
"""
import hashlib
import json
from decimal import Decimal

from psycopg2.extras import Json
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from src.ai.billing import standard_plan_catalog
from src.ai.billing.pricing_math import money


class PublicationError(ValueError):
    pass


def _state(cursor, keys):
    cursor.execute("""SELECT jsonb_build_object(
        'plans', (SELECT jsonb_agg(to_jsonb(p) ORDER BY p.plan_key) FROM
          (SELECT plan_key,monthly_price,currency,catalog_version,self_serve
           FROM usage_plans WHERE plan_key=ANY(%s)) p),
        'prices', (SELECT jsonb_agg(to_jsonb(p) ORDER BY p.plan_key,p.interval_months) FROM
          (SELECT price_id,plan_key,period_code,interval_months,discount_percent,amount,currency,stripe_price_id
           FROM billing_plan_prices WHERE plan_key=ANY(%s) AND retired_at IS NULL) p))::text""", (keys, keys))
    return json.loads(cursor.fetchone()[0], parse_float=str)


def _desired(catalog):
    prices = []
    for plan in catalog['plans']:
        defaults = plan['bootstrap_commercial_defaults']
        monthly = Decimal(defaults['monthly_price'])
        terms = [('monthly', 1, Decimal(0))] + [
            (p['period_code'], {'three-months': 3, 'six-months': 6, 'yearly': 12}[p['period_code']],
             Decimal(p['discount_percent'])) for p in defaults['billing_periods']]
        for period, months, discount in terms:
            prices.append(dict(plan_key=plan['plan_key'], period_code=period, interval_months=months,
                discount_percent=str(discount), amount=str(money(monthly * months * (1-discount/100))),
                currency=defaults['currency']))
    return prices


def _matches(state, desired, version):
    def terms(rows):
        return sorted((r['plan_key'], r['period_code'], r['interval_months'],
                       Decimal(r['discount_percent']), Decimal(r['amount']), r['currency']) for r in rows)
    monthly = {r['plan_key']: Decimal(r['amount']) for r in desired if r['period_code'] == 'monthly'}
    return (terms(state['prices'] or []) == terms(desired)
        and all(p['catalog_version'] == version and Decimal(p['monthly_price']) == monthly[p['plan_key']]
                for p in state['plans']))


def publish_prices(conn, *, approved_by, reason, evidence, apply=False, expected_state=None):
    """Preview by default; explicit apply appends prices under an authenticated owner.

    expected_state comes from a reviewed preview, protecting against concurrent
    commercial edits. No HTTP, subscription, entitlement or accounting writes.
    """
    if conn.autocommit and conn.get_transaction_status() == TRANSACTION_STATUS_IDLE:
        raise PublicationError('Publication requires a caller-owned transaction')
    if not reason.strip() or not isinstance(evidence, dict) or not evidence:
        raise PublicationError('Owner reason and commercial-decision evidence are required')
    catalog = standard_plan_catalog.load_catalog()
    version = catalog['catalog_version']
    keys = [p['plan_key'] for p in catalog['plans']]
    desired = _desired(catalog)
    with conn.cursor() as cur:
        # Same lock as Stripe catalog reconciliation: never bind a retired row.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('keel_stripe_catalog_sync',0))")
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0))")
        cur.execute("""SELECT 1 FROM keel_platform_members m CROSS JOIN keel_platform_workspace w
            WHERE m.user_id=%s AND m.role_key='owner' AND m.status='active'
              AND public.keel_active_principal(m.user_id,w.tenant_id)
              AND NOT EXISTS(SELECT FROM users u WHERE u.user_id=m.user_id AND u.platform_disabled_at IS NOT NULL)""",
            (approved_by,))
        if not cur.fetchone():
            raise PublicationError('Active Platform Owner approval is required')
        state = _state(cur, keys)
        if len(state['plans'] or []) != 3 or any(not p['self_serve'] or p['currency'] != 'USD' for p in state['plans']):
            raise PublicationError('All three canonical USD Standard plans must already exist')
        catalog_digest = standard_plan_catalog.fingerprint(catalog)
        digest = hashlib.sha256(json.dumps(dict(current=state, catalog_digest=catalog_digest),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result = dict(catalog_version=version, state_hash=digest, desired_prices=desired,
                      existing_assignments_preserved=True, stripe_sync_required=True)
        if _matches(state, desired, version):
            return dict(result, already_current=True, published=False)
        cur.execute("SELECT 1 FROM keel_platform_audit WHERE action='standard_catalog_price_publish' AND subject=%s",
                    ('standard_catalog:' + version,))
        if cur.fetchone():
            raise PublicationError('Published catalog subsequently changed; review a new version instead of overwriting owner edits')
        if not apply:
            return dict(result, published=False)
        if expected_state != digest:
            raise PublicationError('Commercial state changed or preview hash missing; review a fresh preview')
        current_periods = {(r['plan_key'], r['period_code']) for r in state['prices'] or []}
        if current_periods - {(r['plan_key'], r['period_code']) for r in desired}:
            raise PublicationError('Unexpected active billing periods; review before retiring any price')
        standard_plan_catalog.install_catalog(conn)
        cur.execute('SELECT digest FROM billing_standard_catalog_versions WHERE catalog_version=%s', (version,))
        if cur.fetchone() != (catalog_digest,):
            raise PublicationError('Catalog source changed during publication; review a fresh preview')
        cur.execute("UPDATE billing_plan_prices SET retired_at=clock_timestamp() WHERE plan_key=ANY(%s) AND retired_at IS NULL", (keys,))
        for row in desired:
            cur.execute("""INSERT INTO billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
                VALUES(%(plan_key)s,%(period_code)s,%(interval_months)s,%(discount_percent)s,%(amount)s,%(currency)s)""", row)
        for plan in catalog['plans']:
            cur.execute("UPDATE usage_plans SET monthly_price=%s,catalog_version=%s WHERE plan_key=%s",
                        (plan['bootstrap_commercial_defaults']['monthly_price'], version, plan['plan_key']))
        new = _state(cur, keys)
        cur.execute("""INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
            VALUES(%s,'owner','standard_catalog_price_publish',%s,%s,%s,%s,'succeeded')""",
            (approved_by, 'standard_catalog:' + version, Json(state),
             Json(dict(new, catalog_digest=catalog_digest, evidence=evidence)), reason))
    return dict(result, published=True, already_current=False)
