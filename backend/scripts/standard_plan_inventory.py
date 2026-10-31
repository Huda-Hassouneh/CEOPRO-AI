"""Read-only catalog classification. No cleanup/delete or retirement side effects.

Run with an explicitly selected DATABASE_URL. A zero subscriber count is not
permission to reuse/delete a stable identity or its commercial/audit evidence.
"""
import json
import os

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

PROTECTED_TABLES = (
    'usage_plans', 'usage_features', 'usage_plan_limits', 'usage_plan_entitlements',
    'billing_plan_prices', 'billing_subscriptions', 'billing_trials', 'billing_payments',
    'tenant_plan_assignments', 'tenant_entitlement_overrides', 'tenant_credit_balances',
    'provider_cost_schedules', 'billing_cost_policy', 'billing_custom_cost_rates',
    'billing_custom_cost_bindings', 'billing_custom_pricing_policies',
)


def inventory(conn):
    conn.set_session(readonly=True)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT p.plan_key,p.display_name,p.is_active,p.self_serve,p.catalog_version,
            (SELECT count(*) FROM billing_plan_prices b WHERE b.plan_key=p.plan_key) AS price_records,
            (SELECT count(*) FROM billing_plan_prices b WHERE b.plan_key=p.plan_key AND b.stripe_price_id IS NOT NULL) AS stripe_mappings,
            (SELECT count(*) FROM keel_platform_audit a WHERE a.subject='plan:'||p.plan_key OR a.subject LIKE 'plan:'||p.plan_key||':%') AS audit_records
            FROM usage_plans p ORDER BY p.plan_key""")
        plans=cur.fetchall()
        cur.execute("""SELECT DISTINCT kcu.table_name,kcu.column_name FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu USING(constraint_name,constraint_schema)
            JOIN information_schema.constraint_column_usage ccu USING(constraint_name,constraint_schema)
            WHERE tc.constraint_type='FOREIGN KEY' AND ccu.table_name='usage_plans'
            ORDER BY kcu.table_name,kcu.column_name""")
        references=cur.fetchall()
        for p in plans:
            p['references']={}
            for ref in references:
                cur.execute(sql.SQL('SELECT count(*) AS n FROM public.{} WHERE {}=%s').format(
                    sql.Identifier(ref['table_name']),sql.Identifier(ref['column_name'])),(p['plan_key'],))
                p['references'][ref['table_name']+'.'+ref['column_name']]=cur.fetchone()['n']
            key=p['plan_key']
            p['classification']=('desired_current_standard_catalog' if key in {'starter','growth','enterprise'} else
                'required_custom_contract_identity' if key=='custom' else
                'inactive_historical_identity' if key in {'standard','pro'} else
                'owner_created_active_plan' if p['is_active'] else 'owner_created_inactive_plan')
            p['cleanup']='PRESERVE'
        fingerprints={}
        for table in PROTECTED_TABLES:
            cur.execute(sql.SQL("SELECT count(*) AS count,md5(coalesce(string_agg(to_jsonb(r)::text,'' ORDER BY to_jsonb(r)::text),'')) AS fingerprint FROM public.{} r").format(sql.Identifier(table)))
            fingerprints[table]=dict(cur.fetchone())
    return dict(plans=plans,deletion_candidates=[],reason='No synthetic identity is inferred from its name. Preserve commercial/audit history; no destructive cleanup is authorized by zero live references.',fingerprints=fingerprints)


if __name__=='__main__':
    with psycopg2.connect(os.environ['DATABASE_URL']) as connection:
        print(json.dumps(inventory(connection),default=str,indent=2))
