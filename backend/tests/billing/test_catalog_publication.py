"""Approved price publication preserves purchased terms and accounting."""
from decimal import Decimal

import pytest
from psycopg2 import errors

from src.ai.billing import catalog_publication, standard_plan_catalog, store
from src.ai.billing.service import BillingError, _price_or_error


def rows(conn, query, args=()):
    with conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchall() if cur.description else None


def test_launch_templates_have_explicit_undiscounted_terms():
    c = standard_plan_catalog.load_catalog()
    assert c['catalog_version'] == 'standard-plans-launch-v3'
    assert [(p['plan_key'], p['bootstrap_commercial_defaults']['monthly_price']) for p in c['plans']] == [
        ('starter', '29.00'), ('growth', '59.00'), ('enterprise', '99.00')]
    for p in c['plans']:
        terms = p['bootstrap_commercial_defaults']['billing_periods']
        assert terms == [dict(period_code='three-months', discount_percent='0.00'),
                         dict(period_code='six-months', discount_percent='0.00')]


def test_publication_uses_existing_half_up_money_rounding():
    c = standard_plan_catalog.load_catalog()
    defaults = c['plans'][0]['bootstrap_commercial_defaults']
    defaults['monthly_price'] = '0.15'
    defaults['billing_periods'][0]['discount_percent'] = '10.00'
    price = next(p for p in catalog_publication._desired(c)
                 if p['plan_key'] == 'starter' and p['period_code'] == 'three-months')
    assert price['amount'] == '0.41'  # SQL round(0.15 * 3 * 0.9, 2).


def test_publication_versions_prices_and_preserves_subscriptions_snapshots_and_limits(owner_db, platform_owner_context, tenant):
    owner = platform_owner_context[1]
    rows(owner_db, 'BEGIN')
    try:
        # Represent an installed, commercially used pre-launch catalog.
        for key, monthly in [('starter', 55), ('growth', 140), ('enterprise', 350)]:
            rows(owner_db, "UPDATE usage_plans SET monthly_price=%s,catalog_version='historical' WHERE plan_key=%s", (monthly, key))
            rows(owner_db, "UPDATE billing_plan_prices SET amount=%s*interval_months, stripe_price_id='price_old_'||plan_key||'_'||period_code WHERE plan_key=%s AND retired_at IS NULL", (monthly, key))
        old = rows(owner_db, "SELECT price_id,stripe_price_id,amount FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL")[0]
        rows(owner_db, "INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,plan_key,period_code,status) VALUES(%s,'sub_publication','cus_publication',%s,'growth','monthly','active')", (tenant[0], old[1]))
        rows(owner_db, "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source) VALUES(%s,'growth','active','manual')", (tenant[0],))
        protected = ['billing_subscriptions', 'tenant_plan_assignments', 'usage_plan_limits', 'usage_plan_entitlements',
                     'billing_cost_policy', 'provider_cost_schedules', 'billing_custom_cost_rates', 'tenant_credit_balances']
        before = {t: rows(owner_db, f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in protected}
        count = rows(owner_db, 'SELECT count(*) FROM billing_plan_prices')[0][0]
        kwargs = dict(approved_by=owner, reason='Synthetic approved acquisition decision', evidence={'policy_version': 4})
        preview = catalog_publication.publish_prices(owner_db, **kwargs)
        assert not preview['published']
        assert rows(owner_db, 'SELECT count(*) FROM billing_plan_prices')[0][0] == count
        result = catalog_publication.publish_prices(owner_db, **kwargs, apply=True, expected_state=preview['state_hash'])
        assert result['published']
        assert before == {t: rows(owner_db, f'SELECT to_jsonb(r) FROM {t} r ORDER BY to_jsonb(r)::text') for t in protected}
        assert rows(owner_db, 'SELECT stripe_price_id,amount,retired_at IS NOT NULL FROM billing_plan_prices WHERE price_id=%s', (old[0],)) == [(old[1], old[2], True)]
        assert store.resolve_price(owner_db, old[1]) == ('growth', 'monthly')
        assert store.subscription_price_snapshot(owner_db, tenant[0])['amount'] == Decimal('140')
        assert rows(owner_db, "SELECT plan_key,amount FROM billing_plan_prices WHERE retired_at IS NULL AND period_code='monthly' AND plan_key IN ('starter','growth','enterprise') ORDER BY amount") == [('starter', Decimal(29)), ('growth', Decimal(59)), ('enterprise', Decimal(99))]
        assert rows(owner_db, 'SELECT count(*) FROM billing_plan_prices')[0][0] == count + 9
        with pytest.raises(BillingError) as missing:
            _price_or_error(owner_db, 'growth', 'monthly')
        assert missing.value.code == 'price_not_synced'
        # Offline bindings model the existing reconciler's successful outcome.
        # Every new checkout selects a new row; historical provider IDs survive.
        for price in result['desired_prices']:
            provider_id = 'price_launch_' + price['plan_key'] + '_' + price['period_code']
            rows(owner_db, "UPDATE billing_plan_prices SET stripe_price_id=%s WHERE plan_key=%s AND period_code=%s AND retired_at IS NULL",
                 (provider_id, price['plan_key'], price['period_code']))
            selected = _price_or_error(owner_db, price['plan_key'], price['period_code'])
            assert selected['stripe_price_id'] == provider_id
            assert selected['amount'] == float(price['amount'])
        assert catalog_publication.publish_prices(owner_db, **kwargs, apply=True, expected_state=preview['state_hash'])['already_current']
        assert rows(owner_db, 'SELECT count(*) FROM billing_plan_prices')[0][0] == count + 9
        assert rows(owner_db, "SELECT count(*) FROM keel_platform_audit WHERE action='standard_catalog_price_publish'") == [(1,)]
        # Re-running setup cannot reset current commercial terms or owner allowances.
        standard_plan_catalog.install_catalog(owner_db)
        assert rows(owner_db, "SELECT monthly_price FROM usage_plans WHERE plan_key='growth'") == [(Decimal(59),)]
        rows(owner_db, "UPDATE billing_plan_prices SET amount=60 WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL")
        with pytest.raises(catalog_publication.PublicationError, match='subsequently changed'):
            catalog_publication.publish_prices(owner_db, **kwargs, apply=True, expected_state=preview['state_hash'])
    finally:
        rows(owner_db, 'ROLLBACK')


def test_publication_requires_active_platform_owner_and_reviewed_state(owner_db, platform_owner_context, tenant):
    rows(owner_db, 'BEGIN')
    try:
        kwargs = dict(reason='Synthetic decision', evidence={'policy_version': 4})
        with pytest.raises(catalog_publication.PublicationError, match='Platform Owner'):
            catalog_publication.publish_prices(owner_db, approved_by=tenant[1], **kwargs)
        rows(owner_db, "UPDATE usage_plans SET monthly_price=55,catalog_version='historical' WHERE plan_key='starter'")
        with pytest.raises(catalog_publication.PublicationError, match='preview hash'):
            catalog_publication.publish_prices(owner_db, approved_by=platform_owner_context[1], apply=True, expected_state='stale', **kwargs)
        assert rows(owner_db, "SELECT monthly_price FROM usage_plans WHERE plan_key='starter'") == [(Decimal(55),)]
        rows(owner_db, 'SAVEPOINT restricted')
        rows(owner_db, 'SET LOCAL ROLE ceopro_app')
        with pytest.raises(errors.InsufficientPrivilege):
            catalog_publication.publish_prices(owner_db, approved_by=platform_owner_context[1], **kwargs)
        rows(owner_db, 'ROLLBACK TO SAVEPOINT restricted')
    finally:
        rows(owner_db, 'ROLLBACK')
