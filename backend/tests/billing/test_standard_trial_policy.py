"""Owner-approved future trial duration; never rewrite existing trial rights."""
from pathlib import Path
from uuid import uuid4

from src.ai.billing import standard_plan_catalog, store

MIGRATION = Path(__file__).resolve().parents[2] / 'src/infrastructure/database/migrations/20261213000000_standard_trial_fourteen_days.sql'


def rows(conn, query, args=()):
    with conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchall() if cur.description else None


def test_all_canonical_standard_templates_have_fourteen_days():
    catalog = standard_plan_catalog.load_catalog()
    assert [(p['plan_key'], p['trial_days']) for p in catalog['plans']] == [
        ('starter', 14), ('growth', 14), ('enterprise', 14)]


def test_trial_migration_preserves_history_prices_limits_and_effective_authority(owner_db):
    rows(owner_db, 'BEGIN')
    try:
        # Populated legacy state: no provider calls or real tenant records.
        tid, uid = str(uuid4()), str(uuid4())
        rows(owner_db, "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Trial policy fixture','JO','USD')", (tid,))
        rows(owner_db, "INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'synthetic')", (uid, uid+'@example.test'))
        rows(owner_db, "INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tid,uid))
        rows(owner_db, "INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(%s,'enterprise',now()-interval '1 day',now()+interval '6 days',%s)", (tid,uid))
        rows(owner_db, "INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,plan_key,period_code,status) VALUES(%s,%s,%s,'price_historical','enterprise','monthly','trialing')", (tid,'sub_'+uid,'cus_'+uid))
        rows(owner_db, "UPDATE usage_plans SET trial_days=7 WHERE plan_key='enterprise'")
        protected = ['billing_trials','billing_subscriptions','tenant_plan_assignments','tenant_credit_balances',
                     'billing_plan_prices','usage_plan_limits','usage_plan_entitlements',
                     'billing_trial_checkouts']
        def snapshot():
            return {t: rows(owner_db, f'SELECT to_jsonb(r) FROM public.{t} r ORDER BY to_jsonb(r)::text') for t in protected}
        def authority():
            return rows(owner_db, "SELECT r.rolname,p.oid,has_function_privilege(r.oid,p.oid,'EXECUTE') FROM pg_roles r CROSS JOIN pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE starts_with(r.rolname,'ceopro_') AND n.nspname='public' ORDER BY 1,2")
        before, acl = snapshot(), authority()
        audit = rows(owner_db, "SELECT count(*) FROM keel_platform_audit WHERE action='standard_trial_policy_update'")[0][0]
        rows(owner_db, MIGRATION.read_text(encoding='utf-8'))
        assert rows(owner_db, "SELECT plan_key,trial_days FROM usage_plans WHERE plan_key IN ('starter','growth','enterprise') ORDER BY plan_key") == [('enterprise',14),('growth',14),('starter',14)]
        assert before == snapshot()
        assert acl == authority()
        assert rows(owner_db, "SELECT old_value->>'trial_days',new_value->>'trial_days' FROM keel_platform_audit WHERE action='standard_trial_policy_update' ORDER BY audit_id DESC LIMIT 1") == [('7','14')]
        rows(owner_db, MIGRATION.read_text(encoding='utf-8'))
        assert rows(owner_db, "SELECT count(*) FROM keel_platform_audit WHERE action='standard_trial_policy_update'")[0][0] == audit+1
        assert before == snapshot()
        plans = {p['plan_key']:p for p in store.catalog(owner_db)}
        assert all(plans[k]['trial_days']==14 for k in ('starter','growth','enterprise'))
        assert plans['enterprise']['monthly_price']==99
    finally:
        rows(owner_db, 'ROLLBACK')
