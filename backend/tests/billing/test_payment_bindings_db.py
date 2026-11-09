"""Real password logins and native FORCE RLS; never provider acceptance."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import os
import uuid

import psycopg2
import pytest
from psycopg2.extras import Json

from src.ai import db
from src.ai.billing import payment_bindings, trial_checkouts
from src.ai.billing.payment_contracts import ProviderReference
from .test_reconciliation_roles import restricted_runtime  # noqa: F401


@pytest.fixture
def parties(owner_db, restricted_runtime):
    # Retained only in the disposable test DB; no deletions of immutable evidence.
    result=[]
    with owner_db.cursor() as cur:
        for _ in range(2):
            tenant, user = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic reservation','US','USD')", (tenant,))
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'not-a-login-password')", (user, user+'@example.test'))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant,user))
            result.append((tenant,user))
        cur.execute("UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled")
        binding='binding-'+uuid.uuid4().hex
        cur.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'stripe','test',%s,true,'native synthetic fixture')", (binding,binding))
        cur.execute("SELECT price_id,stripe_price_id,amount FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL")
        price,old_provider_price,old_amount=cur.fetchone()
        cur.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) VALUES(%s,%s,%s,'synthetic reviewed mapping')",(binding,price,'price_synthetic_'+str(price)))
    yield result
    with owner_db.cursor() as cur:
        cur.execute('UPDATE billing_plan_prices SET stripe_price_id=%s,amount=%s WHERE price_id=%s',(old_provider_price,old_amount,price))
        cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE binding_id=%s',(binding,))


def setup(party):
    return db.billing_setup_connection(*party)


def reserve(party, attempt=None, terms=None):
    with closing(setup(party)) as conn:
        approved=terms or trial_checkouts.approved_terms(conn,'growth','monthly')
        row=trial_checkouts.reserve(conn,attempt or uuid.uuid4(),approved)
        conn.commit()
        return row


def fingerprint(conn):
    tables=('billing_trials','tenant_plan_assignments','billing_subscriptions','tenant_credit_balances','usage_ledger')
    with conn.cursor() as cur:
        result=[]
        for table in tables:
            cur.execute(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM {table} t")
            result.append(cur.fetchone()[0])
        return result


def test_password_login_atomic_replay_and_no_billing_effects(owner_db,parties):
    before=fingerprint(owner_db)
    row=reserve(parties[0]); again=reserve(parties[0],row['attempt_id'],row['approved_terms'])
    assert row==again and row['state']=='pending'
    assert fingerprint(owner_db)==before
    with closing(setup(parties[0])) as conn, conn.cursor() as cur:
        cur.execute('SELECT session_user,current_user')
        assert cur.fetchone()==('ceopro_billing_setup','ceopro_billing_setup')
        cur.execute('SELECT gateway_binding_id,provider_idempotency_key,stripe_session_id FROM billing_checkout_attempts WHERE attempt_id=%s',(row['attempt_id'],))
        assert cur.fetchone()==(row['binding_id'],'keel-trial-checkout-'+row['attempt_id'],None)


@pytest.mark.parametrize('field,value', [('tenant_id','00000000-0000-0000-0000-000000000001'),('started_by_user_id','00000000-0000-0000-0000-000000000001'),('currency','JOD'),('trial_duration_days',999),('approved_amount',0),('provider_price_id','different'),('catalog_revision_id','different'),('interval_months',12),('binding',{})])
def test_conflicting_replay_rejected(owner_db,parties,field,value):
    row=reserve(parties[0]); changed=deepcopy(row['approved_terms']);changed[field]=value
    with closing(setup(parties[0])) as conn, pytest.raises(psycopg2.Error):
        trial_checkouts.reserve(conn,row['attempt_id'],changed)


@pytest.mark.parametrize('same_person',[False,True])
def test_concurrent_reservations_global_person_and_tenant(owner_db,parties,same_person):
    a,b=parties
    if same_person:
        b=(b[0],a[1])
        with owner_db.cursor() as cur:cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",b)
    else:b=a
    def submit(party):
        try:return reserve(party)['state']
        except psycopg2.Error:return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(submit,[a,b]))
    assert sorted(results)==['denied','pending']


def test_full_transaction_rollback_and_frozen_catalog(owner_db,parties):
    attempt=uuid.uuid4()
    with closing(setup(parties[0])) as conn:
        terms=trial_checkouts.approved_terms(conn,'growth','monthly')
        trial_checkouts.reserve(conn,attempt,terms);conn.rollback()
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_checkout_attempts WHERE attempt_id=%s',(str(attempt),));assert cur.fetchone()[0]==0
    row=reserve(parties[0])
    with owner_db.cursor() as cur:
        cur.execute('UPDATE billing_plan_prices SET amount=amount+1 WHERE price_id=%s',(row['price_id'],))
    assert reserve(parties[0],row['attempt_id'],row['approved_terms'])==row
    with closing(setup(parties[0])) as conn:
        assert trial_checkouts.approved_terms(conn,'growth','monthly')['catalog_revision_id']!=row['catalog_revision_id']
        with pytest.raises(psycopg2.Error):
            trial_checkouts.reserve(conn,row['attempt_id'],trial_checkouts.approved_terms(conn,'growth','monthly'))


def test_failed_reservation_rolls_back_checkout_insert(owner_db,parties):
    # Synthetic test-only trigger fails after the attempt insert, before reservation persistence.
    with owner_db.cursor() as cur:
        cur.execute("CREATE FUNCTION c2b_injected_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$")
        cur.execute('CREATE TRIGGER c2b_injected_failure BEFORE INSERT ON billing_trial_checkouts FOR EACH ROW EXECUTE FUNCTION c2b_injected_failure()')
    attempt=str(uuid.uuid4())
    try:
        with pytest.raises(psycopg2.Error):reserve(parties[0],attempt)
    finally:
        with owner_db.cursor() as cur:
            cur.execute('DROP TRIGGER c2b_injected_failure ON billing_trial_checkouts');cur.execute('DROP FUNCTION c2b_injected_failure()')
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_checkout_attempts WHERE attempt_id=%s',(attempt,));assert cur.fetchone()[0]==0


def test_uncertain_submission_retains_reservation_and_session_identity(parties):
    row=reserve(parties[0]);attempt=row['attempt_id']
    with closing(setup(parties[0])) as conn:
        trial_checkouts.operation(conn,attempt,'prepare',payload={'synthetic':'frozen'},replay_window_seconds=60)
        first=trial_checkouts.operation(conn,attempt,'submitted');conn.commit()
        again=trial_checkouts.operation(conn,attempt,'submitted');conn.commit()
        assert first['first_submitted_at']==again['first_submitted_at']
        with pytest.raises(psycopg2.Error):trial_checkouts.operation(conn,attempt,'release')
        conn.rollback()
        trial_checkouts.operation(conn,attempt,'session',session='same-session');conn.commit()
        with pytest.raises(psycopg2.Error):trial_checkouts.operation(conn,attempt,'session',session='different')
    assert reserve(parties[0],attempt,row['approved_terms'])['state']=='pending'


def test_only_unsubmitted_release_is_supported(parties):
    row=reserve(parties[0])
    with closing(setup(parties[0])) as conn:
        result=trial_checkouts.operation(conn,row['attempt_id'],'release');conn.commit()
        assert result['state']=='expired'
    assert reserve(parties[0])['state']=='pending'


@pytest.mark.parametrize('provider,environment,merchant', [('stripe','test','other'),('stripe','live','other'),('other','test','other')])
def test_same_customer_ids_are_binding_qualified(owner_db,parties,provider,environment,merchant):
    with closing(setup(parties[0])) as conn:
        binding=payment_bindings.selected(conn)
        first=payment_bindings.record_customer_reference(conn,ProviderReference(binding.provider,'same-object',binding=binding));conn.commit()
    next_id='binding-'+uuid.uuid4().hex
    with owner_db.cursor() as cur:
        cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        cur.execute('INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,%s,%s,%s,true,%s)',(next_id,provider,environment,merchant+next_id,'synthetic'))
    with closing(setup(parties[0])) as conn:
        binding=payment_bindings.selected(conn)
        second=payment_bindings.record_customer_reference(conn,ProviderReference(binding.provider,'same-object',binding=binding));conn.commit()
        assert first['reference_id']!=second['reference_id']
    with closing(setup(parties[1])) as conn,pytest.raises(psycopg2.Error):
        payment_bindings.record_customer_reference(conn,ProviderReference(binding.provider,'same-object',binding=binding))


def test_customer_reassignment_and_tenant_binding_selection_denied(parties):
    with closing(setup(parties[0])) as conn:
        binding=payment_bindings.selected(conn)
        ref=ProviderReference('stripe','customer-1',binding=binding)
        first=payment_bindings.record_customer_reference(conn,ref);conn.commit()
        assert payment_bindings.record_customer_reference(conn,ref)==first
        with pytest.raises(psycopg2.Error):payment_bindings.record_customer_reference(conn,ProviderReference('stripe','customer-2',binding=binding))
        conn.rollback()
        with pytest.raises(ValueError):payment_bindings.record_customer_reference(conn,ProviderReference('stripe','unscoped'))


def test_rls_privileges_ownership_and_no_admin_fallback(owner_db,parties):
    row=reserve(parties[0])
    with closing(setup(parties[1])) as conn,conn.cursor() as cur:
        cur.execute('SELECT attempt_id FROM billing_trial_checkouts WHERE attempt_id=%s',(row['attempt_id'],));assert cur.fetchall()==[]
        for query in ["UPDATE billing_gateway_bindings SET reservation_enabled=true",'SET ROLE ceopro_trial_issuer',
                      "INSERT INTO billing_trials(tenant_id,plan_key,ends_at) VALUES(gen_random_uuid(),'growth',now())",
                      "UPDATE billing_trial_checkouts SET state='activated'",'CREATE TABLE public.c2b_forbidden(id int)']:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute(query)
            conn.rollback()
    with pytest.raises(ValueError):trial_checkouts.approved_terms(owner_db,'growth','monthly')
    with owner_db.cursor() as cur:
        cur.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s)",(['billing_gateway_bindings','billing_customer_references','billing_price_references','billing_trial_checkouts'],))
        assert len(rows:=cur.fetchall())==4 and all(a and b for _,a,b in rows)
        cur.execute("SELECT p.proname,r.rolname,p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.proname=ANY(%s)",(['billing_reserve_trial_checkout','billing_trial_operation','billing_trial_checkout_terms'],))
        assert len(rows:=cur.fetchall())==3
        assert all(owner=='ceopro_trial_issuer' and sec and 'search_path=pg_catalog, public, pg_temp' in config for _,owner,sec,config in rows)
        cur.execute("SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolinherit FROM pg_roles WHERE rolname='ceopro_billing_setup'")
        assert cur.fetchone()==(False,False,False,False,False)
        cur.execute("SELECT has_schema_privilege('ceopro_trial_issuer','public','CREATE')")
        assert cur.fetchone()==(False,)


@pytest.mark.parametrize('change',["removed_at=now()","platform_suspended_at=now()"])
def test_revoked_principal_rejected(owner_db,parties,change):
    with owner_db.cursor() as cur:cur.execute(f'UPDATE tenant_users SET {change} WHERE tenant_id=%s AND user_id=%s',parties[0])
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):reserve(parties[0])


@pytest.mark.parametrize('column,value', [('merchant_account_id','changed'),('environment','live'),('provider','other')])
def test_binding_identity_is_immutable(owner_db,parties,column,value):
    with owner_db.cursor() as cur,pytest.raises(psycopg2.errors.InvalidParameterValue):
        cur.execute(f'UPDATE billing_gateway_bindings SET {column}=%s WHERE reservation_enabled',(value,))


def test_missing_binding_and_frozen_reservation_updates_rejected(owner_db,parties):
    row=reserve(parties[0])
    with owner_db.cursor() as cur,pytest.raises(psycopg2.errors.InvalidParameterValue):
        cur.execute("UPDATE billing_trial_checkouts SET currency='JOD' WHERE attempt_id=%s",(row['attempt_id'],))
    with owner_db.cursor() as cur:cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
    with closing(setup(parties[1])) as conn,pytest.raises(psycopg2.errors.InvalidParameterValue):
        trial_checkouts.approved_terms(conn,'growth','monthly')


def test_person_pending_guard_survives_provider_and_environment_change(owner_db,parties):
    a,b=parties; b=(b[0],a[1]);row=reserve(a)
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",b)
        cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        binding='other-'+uuid.uuid4().hex
        cur.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'other','live',%s,true,'synthetic unsupported provider')",(binding,binding))
    changed=deepcopy(row['approved_terms']);changed['tenant_id']=b[0];changed['binding']['binding_id']=binding
    with closing(setup(b)) as conn,pytest.raises(psycopg2.errors.InvalidParameterValue,match='Trial eligibility unavailable'):
        trial_checkouts.reserve(conn,uuid.uuid4(),changed)


def test_new_commands_are_not_public_and_do_not_have_activation_paths(owner_db,parties):
    with owner_db.cursor() as cur:
        for function in ('billing_reserve_trial_checkout(uuid,jsonb)','billing_trial_operation(uuid,text,jsonb,integer,text)',
                         'billing_record_customer_reference(text,text)'):
            cur.execute("SELECT has_function_privilege('ceopro_app',%s,'EXECUTE'),has_function_privilege('ceopro_billing_webhook',%s,'EXECUTE')",(function,function))
            assert cur.fetchone()==(False,False)
        cur.execute("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_billing_setup')")
        assert cur.fetchone()==(0,)
    row=reserve(parties[0])
    with closing(setup(parties[0])) as conn,pytest.raises(psycopg2.errors.InvalidParameterValue):
        trial_checkouts.operation(conn,row['attempt_id'],'activate')


def test_legacy_price_does_not_supply_unproven_binding_provenance(owner_db,parties):
    with owner_db.cursor() as cur:
        cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        binding='unmapped-'+uuid.uuid4().hex
        cur.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'stripe','test',%s,true,'no price mapping')",(binding,binding))
    with closing(setup(parties[0])) as conn,pytest.raises(psycopg2.errors.InvalidParameterValue,match='Approved trial price required'):
        trial_checkouts.approved_terms(conn,'growth','monthly')


def test_actual_app_read_scope_and_composite_foreign_keys(owner_db,parties):
    row=reserve(parties[0])
    for party,expected in [(parties[0],1),(parties[1],0)]:
        with closing(db.app_role_connection(*party)) as conn,conn.cursor() as cur:
            cur.execute('SELECT session_user');assert cur.fetchone()==('ceopro_app',)
            cur.execute('SELECT count(*) FROM billing_trial_checkouts WHERE attempt_id=%s',(row['attempt_id'],))
            assert cur.fetchone()==(expected,)
    with owner_db.cursor() as cur:
        cur.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='billing_trial_checkouts'::regclass AND contype='f'")
        definitions=[d for (d,) in cur.fetchall()]
        assert any('FOREIGN KEY (attempt_id, tenant_id, binding_id)' in d for d in definitions)
        assert any('FOREIGN KEY (price_id, binding_id, provider_price_id)' in d for d in definitions)
