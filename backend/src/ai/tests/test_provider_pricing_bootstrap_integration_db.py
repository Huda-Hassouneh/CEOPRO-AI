"""Native catalog installation tests. Only explicitly disposable DBs are allowed.

Run through dev.ps1 test --suite backend --pytest-args <this module> -q.
Additional fresh databases are retained and named in pytest output.
No provider requests, tenant subscriptions or normal database writes.
"""
import os
from contextlib import closing
import shutil
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from scripts import apply_migrations as runner
from src.ai.billing import credits

MIGRATION = runner.MIGRATIONS_DIR / '20261115000000_approved_ai_provider_pricing_v1.sql'
VERSION = 'ai-provider-pricing-v1'
MODEL = 'openai/gpt-oss-20b'


def new_database():
    dsn = os.getenv('AI_TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('AI_TEST_DATABASE_URL required for native installation tests')
    params = parse_dsn(dsn)
    if not params.get('dbname', '').startswith('keel_billing_test_') and not params.get('dbname', '').startswith('keel_billing_test_dev'):
        pytest.fail('Refusing catalog tests outside the disposable database namespace')
    name = 'keel_billing_test_provider_catalog_' + uuid4().hex[:12]
    with closing(psycopg2.connect(dsn)) as admin:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    print('Retained catalog test database:', name)
    return make_dsn(dsn, dbname=name)


@pytest.fixture(scope='module')
def before_catalog(tmp_path_factory):
    dsn = new_database()
    prior = tmp_path_factory.mktemp('prior_catalog_migrations')
    for path in runner.MIGRATIONS_DIR.glob('*.sql'):
        if path.name < MIGRATION.name:
            shutil.copyfile(path, prior / path.name)
    # Rehearse the actual pre-upgrade schema, not a hand-written table mock.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, 'MIGRATIONS_DIR', prior)
        with psycopg2.connect(dsn) as conn:
            assert len(runner.run(conn)) == len(list(prior.glob('*.sql')))
    return dsn


@pytest.fixture
def conn(before_catalog):
    connection = psycopg2.connect(before_catalog)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def execute(conn, command, args=None):
    with conn.cursor() as cur:
        cur.execute(command, args)
        return cur.fetchall() if cur.description else None


def schedules(conn):
    return execute(conn, "SELECT row_to_json(p)::jsonb FROM public.provider_cost_schedules p ORDER BY budget_kind,provider,operation,unit")


def audits(conn):
    return execute(conn, "SELECT subject,old_value,new_value,approved_by,reason FROM public.entitlement_audit_log WHERE contract_ref=%s ORDER BY subject", (VERSION,))


def install(conn, source=None):
    execute(conn, source or MIGRATION.read_text(encoding='utf-8'))


def test_fresh_supported_runner_and_repeated_startup():
    from decimal import Decimal
    dsn = new_database()
    with psycopg2.connect(dsn) as conn:
        assert len(runner.run(conn)) == len(list(runner.MIGRATIONS_DIR.glob('*.sql')))
        prices = credits.schedule(conn, 'ai', 'groq', MODEL)
        assert prices['input_token']['cost'] == Decimal('0.000000075')
        assert prices['output_token']['cost'] == Decimal('0.00000030')
        assert credits._cost(prices, {'input_token': 1000000, 'output_token': 1000000}, 'ai', 'groq', MODEL) == Decimal('0.375')
        before = schedules(conn), audits(conn)
        assert len(before[1]) == 2
        assert all(row[2]['outcome'] == 'filled_placeholder' for row in before[1])
        assert runner.run(conn) == []
        install(conn)  # Direct replay is also idempotent.
        assert (schedules(conn), audits(conn)) == before


def test_missing_rows_are_inserted_with_fixed_approval(conn):
    execute(conn, "DELETE FROM provider_cost_schedules WHERE provider='groq' AND operation=%s", (MODEL,))
    install(conn)
    assert len(audits(conn)) == 2
    assert all(row[1] is None and row[2]['outcome'] == 'inserted' for row in audits(conn))
    assert execute(conn, "SELECT verified_at::text,configured_by FROM provider_cost_schedules WHERE provider='groq' ORDER BY unit") == [('2026-10-28', VERSION)] * 2


def test_owner_rates_history_and_financial_facts_are_preserved(conn):
    execute(conn, "UPDATE provider_cost_schedules SET unit_cost_usd=0.123456789012,safety_margin=0.42,charged_on_failure=false,cost_is_final=false,source='SYNTHETIC owner rate',verified_at=DATE '2026-10-01',configured_by='synthetic-owner' WHERE provider='groq'")
    execute(conn, "INSERT INTO entitlement_audit_log(action,subject,approved_by,reason,new_value) VALUES('set_price','synthetic prior rate','synthetic-owner','SYNTHETIC history','{\"unit_cost_usd\":0.123456789012}')")
    tenant = str(uuid4())
    execute(conn, "INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'SYNTHETIC catalog preservation','JO','JOD')", (tenant,))
    execute(conn, """INSERT INTO usage_ledger(tenant_id,plan_key,plan_status,budget_kind,period_start,
        operation_id,operation_type,provider,provider_operation,idempotency_key,status,
        estimated_cost_usd,actual_cost_usd,reserved_credits,consumed_credits)
        VALUES(%s,'growth','trialing','ai',DATE '2026-10-01',%s,'synthetic_test','groq',%s,
        'synthetic-historical-cost','consumed',0.001,0.001,0,0.1)""", (tenant, str(uuid4()), MODEL))
    tables = ('usage_ledger', 'tenant_credit_balances', 'billing_cost_policy', 'usage_features',
              'usage_plans', 'usage_plan_limits', 'billing_plan_prices', 'billing_subscriptions',
              'billing_trials', 'tenant_plan_assignments', 'billing_custom_cost_rates')
    def financial_snapshot():
        return [execute(conn, sql.SQL('SELECT row_to_json(t)::text FROM public.{} t ORDER BY row_to_json(t)::text').format(sql.Identifier(t))) for t in tables]
    old_schedules, financial = schedules(conn), financial_snapshot()
    old_audit = execute(conn, "SELECT row_to_json(a)::text FROM entitlement_audit_log a ORDER BY audit_id")
    install(conn)
    assert schedules(conn) == old_schedules
    assert financial_snapshot() == financial
    assert execute(conn, "SELECT row_to_json(a)::text FROM entitlement_audit_log a WHERE contract_ref IS NULL ORDER BY audit_id") == old_audit
    assert all(row[2]['outcome'] == 'preserved' for row in audits(conn))
    # Later approved versions remain historical evidence, not automatic repricing.
    later = MIGRATION.read_text(encoding='utf-8').replace(VERSION, 'ai-provider-pricing-v2-test').replace('0.075::numeric', '0.15::numeric')
    install(conn, later)
    assert schedules(conn) == old_schedules
    assert execute(conn, "SELECT count(*) FROM entitlement_audit_log WHERE contract_ref='ai-provider-pricing-v2-test'") == [(2,)]
    assert len(audits(conn)) == 2


@pytest.mark.parametrize('change', [
    "configured_by='synthetic-owner'", "source='SYNTHETIC owner-disabled price'",
    "safety_margin=0.7", "charged_on_failure=false", "cost_is_final=false",
    "verified_at=DATE '2026-10-01'", "unit_cost_usd=0",
])
def test_configured_or_deliberately_unpriced_rows_are_never_filled(conn, change):
    execute(conn, 'UPDATE provider_cost_schedules SET ' + change + " WHERE provider='groq'")
    before = schedules(conn)
    install(conn)
    assert schedules(conn) == before
    assert all(row[2]['outcome'] == 'preserved' for row in audits(conn))


def test_half_configured_model_and_owner_edit_after_bootstrap(conn):
    execute(conn, "UPDATE provider_cost_schedules SET unit_cost_usd=0.42,configured_by='synthetic-owner' WHERE provider='groq' AND unit='input_token'")
    install(conn)
    assert [row[2]['outcome'] for row in audits(conn)] == ['preserved', 'filled_placeholder']
    execute(conn, "UPDATE provider_cost_schedules SET unit_cost_usd=NULL,source='SYNTHETIC owner disabled' WHERE provider='groq'")
    before = schedules(conn), audits(conn)
    install(conn)
    assert (schedules(conn), audits(conn)) == before


def test_unapproved_model_still_fails_closed(conn):
    install(conn)
    with pytest.raises(credits.BudgetError) as exc:
        credits._cost(credits.schedule(conn, 'ai', 'groq', 'synthetic-unapproved-model'), {'input_token': 1}, 'ai', 'groq', 'synthetic-unapproved-model')
    assert exc.value.reason == 'COST_NOT_CONFIGURED'


@pytest.mark.parametrize('role', ['ceopro_app', 'ceopro_billing_setup', 'ceopro_billing_webhook', 'ceopro_credit_accounting'])
def test_restricted_roles_cannot_bootstrap_or_write_rates(conn, role):
    execute(conn, sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
    execute(conn, 'SAVEPOINT denied_bootstrap')
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        install(conn)
    execute(conn, 'ROLLBACK TO SAVEPOINT denied_bootstrap')
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        execute(conn, "UPDATE provider_cost_schedules SET unit_cost_usd=0 WHERE provider='groq'")


def test_migration_adds_no_runtime_privileges_or_rls_changes(conn):
    query = """SELECT relname,relrowsecurity,relforcerowsecurity,relacl::text
        FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname"""
    before = execute(conn, query)
    install(conn)
    assert execute(conn, query) == before
    execute(conn, 'SET LOCAL ROLE ceopro_credit_accounting')
    assert credits.schedule(conn, 'ai', 'groq', MODEL)['input_token']['cost'] is not None
