"""A1 native PG17. ALL policies/acceptances/provider identities are synthetic.

Dedicated service LOGIN is enabled only by the guarded disposable installer.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
import time
import uuid

import psycopg2
import pytest

from src.ai import db
from src.ai.billing import recurring_consent as R, verification_observations as V, trial_checkouts
from .test_verification_observations_db import ContextConnection, connection
from .test_payment_bindings_db import parties, reserve, fingerprint
from .test_customer_operations_db import scenario as customer_scenario, run as resolve_customer
from .test_reconciliation_roles import restricted_runtime


def service(party, role='ceopro_consent_service'):
    values = psycopg2.extensions.parse_dsn(os.environ['BILLING_TEST_DATABASE_URL'])
    values.update(user=role, password=os.environ['OBSERVATION_TEST_PASSWORD'])
    return ContextConnection(db._UnpooledOwner(), psycopg2.connect(**values), *party)


def policy(owner_db, **changes):
    pid = str(uuid.uuid4())
    values = dict(policy_id=pid, agreement_reference='SYNTHETIC-NOT-LEGAL-'+pid,
                  agreement_revision='synthetic-v1', language_tag='en', status='approved',
                  agreement_digest='sha256:'+'a'*64, cancellation_reference='synthetic-cancellation',
                  renewal_disclosure_reference='synthetic-renewal', trial_start_rule_reference='synthetic-only-rule',
                  retention_policy_reference='synthetic-retention', environment='test', eligible_interval_months=[1],
                  presentation_ttl_seconds=3600, approval_reference='ISOLATED TEST FIXTURE, NOT OWNER APPROVAL')
    values.update(changes)
    with owner_db.cursor() as cur:
        cur.execute('INSERT INTO billing_consent_policy_versions('+','.join(values)+') VALUES('+','.join(['%s']*len(values))+')', tuple(values.values()))
    return pid


def present(party, reservation, pid):
    with closing(service(party)) as conn:
        return R.ConsentRepository(conn).present(reservation['attempt_id'], pid).unpack()


def accept(party, p):
    with closing(service(party)) as conn:
        return R.ConsentRepository(conn).accept(R.PresentationIdentity(uuid.UUID(p['presentation_id']), p['terms_digest']), p['challenge']).unpack()


def invalidate(party, p, reason=R.ConsentState.SUPERSEDED):
    with closing(service(party)) as conn:
        return R.ConsentRepository(conn).invalidate(p['presentation_id'], reason).unpack()


def associate(party, a, operation):
    with closing(service(party)) as conn:
        return R.ConsentRepository(conn).associate(a['acceptance_id'], operation['operation_id']).unpack()


@pytest.fixture
def presentation(owner_db, parties):
    party = parties[0]
    reservation = reserve(party)
    return party, reservation, present(party, reservation, policy(owner_db))


def checkout(party, reservation):
    with closing(db.billing_setup_connection(*party)) as conn:
        trial_checkouts.operation(conn, reservation['attempt_id'], 'prepare', payload={'SYNTHETIC': True}, replay_window_seconds=3600)
        trial_checkouts.operation(conn, reservation['attempt_id'], 'submitted')
        trial_checkouts.operation(conn, reservation['attempt_id'], 'session', session='cs_synthetic_'+reservation['attempt_id'])
        conn.commit()
    with closing(connection(party)) as conn:
        repo = V.ObservationRepository(conn)
        return repo.begin(uuid.uuid4(), V.trial_request(repo.context(reservation['attempt_id'])))


@pytest.fixture
def associated_context(owner_db, customer_scenario):
    resolve_customer(customer_scenario)
    party = customer_scenario[0]
    reservation = reserve(party)
    p = present(party, reservation, policy(owner_db))
    a = accept(party, p)
    operation = checkout(party, reservation)
    return party, reservation, p, a, operation


def test_full_frozen_terms_agreement_and_db_clock(owner_db, presentation):
    party, reservation, p = presentation
    assert p['approved_terms'] == reservation['approved_terms']
    assert p['actor_id'] == party[1] and p['tenant_id'] == party[0]
    assert p['binding_id'] == reservation['binding_id'] and p['attempt_id'] == reservation['attempt_id']
    assert p['status'] == 'presented' and len(p['challenge']) == 72 and 'challenge_digest' not in p
    assert p['quantity'] == 1
    assert p['policy']['agreement_revision'] == 'synthetic-v1' and p['policy']['language_tag'] == 'en'
    assert p['approved_terms']['currency'] == 'USD' and p['approved_terms']['approved_amount'] == reservation['approved_amount']
    with owner_db.cursor() as cur:
        cur.execute("SELECT 'sha256:'||encode(sha256(convert_to(approved_terms::text,'UTF8')),'hex') FROM billing_trial_checkouts WHERE attempt_id=%s", (reservation['attempt_id'],))
        assert cur.fetchone() == (p['terms_digest'],)
        cur.execute("SELECT expires_at-created_at=interval '3600 seconds', created_at<=clock_timestamp(), challenge_digest<>%s FROM billing_consent_presentations WHERE presentation_id=%s", (p['challenge'], p['presentation_id']))
        assert cur.fetchone() == (True, True, True)
    before = fingerprint(owner_db)
    a = accept(party, p)
    assert a['actor_id'] == party[1] and a['presentation_id'] == p['presentation_id']
    assert fingerprint(owner_db) == before
    with pytest.raises(R.ConsentError):
        accept(party, p)


def test_commercial_currency_independent_of_company_analysis_currency(owner_db, presentation):
    party, reservation, p = presentation
    with owner_db.cursor() as cur:
        cur.execute("UPDATE companies SET primary_currency='JOD' WHERE tenant_id=%s", (party[0],))
    assert p['approved_terms']['currency'] == 'USD'
    assert accept(party, p)['tenant_id'] == party[0]


@pytest.mark.parametrize('status', ['pending', 'unsupported'])
def test_pending_policy_never_produces_challenge(owner_db, parties, status):
    r = reserve(parties[0]); p = present(parties[0], r, policy(owner_db, status=status, agreement_digest=None))
    assert p['status'] == ('pending_policy' if status == 'pending' else 'unsupported')
    assert p['challenge'] is None and p['expires_at'] is None
    with closing(service(parties[0])) as conn, pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:
            cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], 'x'*72, p['terms_digest']))


@pytest.mark.parametrize('changes', [dict(environment='live'), dict(eligible_interval_months=[12])])
def test_policy_environment_and_eligible_period(owner_db, parties, changes):
    r = reserve(parties[0])
    with pytest.raises(R.ConsentError):
        present(parties[0], r, policy(owner_db, **changes))


@pytest.mark.parametrize('field', ['agreement_digest', 'cancellation_reference', 'renewal_disclosure_reference',
                                  'trial_start_rule_reference', 'retention_policy_reference', 'environment',
                                  'approval_reference', 'eligible_interval_months', 'presentation_ttl_seconds'])
def test_approved_policy_cannot_omit_unresolved_field(owner_db, field):
    with pytest.raises(psycopg2.Error):
        policy(owner_db, **{field: None})


def test_unknown_policy_and_wrong_reservation(owner_db, parties):
    r = reserve(parties[0])
    with pytest.raises(R.ConsentError):
        present(parties[0], r, str(uuid.uuid4()))
    with pytest.raises(R.ConsentError):
        present(parties[1], r, policy(owner_db))


def test_wrong_actor_tenant_challenge_and_terms(owner_db, parties, presentation):
    party, _, p = presentation
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'admin')", (party[0], parties[1][1]))
    for other in (parties[1], (party[0], parties[1][1])):
        with pytest.raises(R.ConsentError):
            accept(other, p)
    for changed in (dict(p, challenge='x'*72), dict(p, terms_digest='sha256:'+'b'*64)):
        with pytest.raises(R.ConsentError):
            accept(party, changed)
    assert accept(party, p)['actor_id'] == party[1]


@pytest.mark.parametrize('mutation', ["UPDATE tenant_users SET removed_at=clock_timestamp() WHERE tenant_id=%s AND user_id=%s",
                                    "UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",
                                    "UPDATE tenant_users SET platform_suspended_at=clock_timestamp() WHERE tenant_id=%s AND user_id=%s",
                                    "UPDATE users SET platform_disabled_at=clock_timestamp() WHERE %s::uuid IS NOT NULL AND user_id=%s",
                                    "UPDATE companies SET platform_suspended_at=clock_timestamp() WHERE tenant_id=%s AND %s::uuid IS NOT NULL"])
def test_revoked_authorization(owner_db, presentation, mutation):
    party, _, p = presentation
    with owner_db.cursor() as cur:
        cur.execute(mutation, party)
    with pytest.raises(R.ConsentError):
        accept(party, p)


def test_immutable_records_and_changed_reservation_terms(owner_db, presentation):
    party, r, p = presentation
    for table, key, value in [('billing_consent_policy_versions', 'policy_id', p['policy_id']),
                               ('billing_consent_presentations', 'presentation_id', p['presentation_id'])]:
        with owner_db.cursor() as cur, pytest.raises(psycopg2.Error):
            cur.execute(f'UPDATE {table} SET {key}={key} WHERE {key}=%s', (value,))
    with owner_db.cursor() as cur, pytest.raises(psycopg2.Error):
        cur.execute("UPDATE billing_trial_checkouts SET approved_terms=approved_terms||'{\"extra\":1}'::jsonb WHERE attempt_id=%s", (r['attempt_id'],))
    # Test installer alone simulates corrupted/changed frozen data; the command
    # must still detect the FULL JSON change, not just the catalog revision.
    with owner_db.cursor() as cur:
        cur.execute('ALTER TABLE billing_consent_presentations DISABLE TRIGGER consent_immutable')
        cur.execute("UPDATE billing_consent_presentations SET approved_terms=approved_terms||'{\"extra\":1}'::jsonb WHERE presentation_id=%s", (p['presentation_id'],))
        cur.execute('ALTER TABLE billing_consent_presentations ENABLE TRIGGER consent_immutable')
    with pytest.raises(R.ConsentError):
        accept(party, p)


@pytest.mark.parametrize('reason', [R.ConsentState.SUPERSEDED, R.ConsentState.WITHDRAWN])
def test_invalidation_preserves_acceptance_facts(owner_db, presentation, reason):
    party, _, p = presentation
    a = accept(party, p)
    assert invalidate(party, p, reason)['reason'] == reason.value
    with pytest.raises(R.ConsentError):
        accept(party, p)
    with owner_db.cursor() as cur:
        cur.execute('SELECT acceptance_id FROM billing_consent_acceptances WHERE presentation_id=%s', (p['presentation_id'],))
        assert cur.fetchone() == (a['acceptance_id'],)


def test_expired_presentation(owner_db, parties):
    party = parties[0]; r = reserve(party); p = present(party, r, policy(owner_db, presentation_ttl_seconds=1))
    with owner_db.cursor() as cur:
        cur.execute('SELECT pg_sleep(1.05)')
    with pytest.raises(R.ConsentError):
        accept(party, p)


def wait_blocked(owner_db, pid):
    deadline = time.monotonic()+5
    while True:
        with owner_db.cursor() as cur:
            cur.execute('SELECT pg_stat_clear_snapshot()')
            cur.execute('SELECT pg_blocking_pids(%s)', (pid,))
            if cur.fetchone()[0]:
                return
        assert time.monotonic()<deadline, 'Expected database lock edge absent'
        time.sleep(.01)


def test_deterministic_concurrent_duplicate_acceptance(owner_db, presentation):
    party, _, p = presentation
    with closing(service(party)) as first, closing(service(party)) as second:
        with second.cursor() as cur:
            cur.execute('SELECT pg_backend_pid()'); pid = cur.fetchone()[0]
        args = (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest'])
        with first.cursor() as cur:
            cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', args)
        def duplicate():
            with second.cursor() as cur:
                cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(duplicate)
            try:
                wait_blocked(owner_db, pid)
            finally:
                first.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_consent_acceptances WHERE presentation_id=%s', (p['presentation_id'],))
        assert cur.fetchone() == (1,)


def test_supersession_wins_concurrent_acceptance(owner_db, presentation):
    party, _, p = presentation
    with closing(service(party)) as first, closing(service(party)) as second:
        with first.cursor() as cur:
            cur.execute("SELECT billing_consent_invalidate(%s,'superseded')", (p['presentation_id'],))
        with second.cursor() as cur:
            cur.execute('SELECT pg_backend_pid()'); pid = cur.fetchone()[0]
        def submit():
            with second.cursor() as cur:
                cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest']))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            try:
                wait_blocked(owner_db, pid)
            finally:
                first.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)


def test_authorization_locked_through_accept_commit(owner_db, presentation):
    party, _, p = presentation
    raw = psycopg2.connect(os.environ['BILLING_TEST_DATABASE_URL'])
    try:
        with closing(service(party)) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest']))
            with raw.cursor() as cur:
                cur.execute('SELECT pg_backend_pid()'); pid = cur.fetchone()[0]
            def demote():
                with raw.cursor() as cur:
                    cur.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s", party)
                raw.commit()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(demote)
                try:
                    wait_blocked(owner_db, pid)
                finally:
                    conn.commit()
                future.result(timeout=5)
    finally:
        raw.close()


def test_uncommitted_authorization_update_and_repeatable_read_fail_closed(owner_db, presentation):
    party, _, p = presentation
    with closing(psycopg2.connect(os.environ['BILLING_TEST_DATABASE_URL'])) as raw:
        with raw.cursor() as cur:
            cur.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s", party)
        with pytest.raises(R.ConsentError, match='55P03'):
            accept(party, p)
        raw.rollback()
    with closing(service(party)) as conn, pytest.raises(psycopg2.Error):
        conn._raw.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest']))


def test_demotion_while_waiting_for_reservation_is_rechecked(owner_db, presentation):
    party, r, p = presentation
    with closing(psycopg2.connect(os.environ['BILLING_TEST_DATABASE_URL'])) as blocker, closing(service(party)) as waiter:
        with blocker.cursor() as cur:
            cur.execute('SELECT attempt_id FROM billing_trial_checkouts WHERE attempt_id=%s FOR UPDATE', (r['attempt_id'],))
        with waiter.cursor() as cur:
            cur.execute('SELECT pg_backend_pid()'); pid = cur.fetchone()[0]
        def submit():
            with waiter.cursor() as cur:
                cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest']))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            try:
                wait_blocked(owner_db, pid)
                with owner_db.cursor() as cur:
                    cur.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s", party)
            finally:
                blocker.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)


def test_new_agreement_revision_requires_new_acceptance(owner_db, presentation):
    party, r, p = presentation
    invalidate(party, p)
    revised = present(party, r, policy(owner_db, agreement_reference=p['policy']['agreement_reference'],
                                     agreement_revision='synthetic-v2', language_tag='ar', agreement_digest='sha256:'+'b'*64))
    with pytest.raises(R.ConsentError):
        accept(party, p)
    assert revised['policy']['agreement_revision'] == 'synthetic-v2'
    assert revised['policy']['language_tag'] == 'ar'
    assert revised['approved_terms'] == p['approved_terms']
    assert accept(party, revised)['presentation_id'] == revised['presentation_id']


def test_exact_append_only_bridge_and_no_verification_or_access(owner_db, associated_context):
    party, r, p, a, operation = associated_context
    before = fingerprint(owner_db)
    result = associate(party, a, operation)
    assert associate(party, a, operation) == result
    assert result['attempt_id'] == r['attempt_id'] and result['terms_digest'] == p['terms_digest']
    assert result['provider_customer_id'] == operation['provider_customer_id']
    assert fingerprint(owner_db) == before
    with owner_db.cursor() as cur:
        cur.execute('SELECT actor_id,accepted_at,agreement_revision FROM billing_trial_consents WHERE consent_id=%s', (a['acceptance_id'],))
        actor, accepted_at, revision = cur.fetchone()
        assert actor == party[1] and accepted_at.isoformat() == a['accepted_at'] and revision == 'synthetic-v1'
        cur.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s', (operation['operation_id'],))
        assert cur.fetchone() == (0,)
    with pytest.raises(R.ConsentError):
        associate(party, a, dict(operation, operation_id=str(uuid.uuid4())))
    with pytest.raises(R.ConsentError):
        invalidate(party, p, R.ConsentState.WITHDRAWN)
    for table, key, identity in [('billing_consent_acceptances', 'acceptance_id', a['acceptance_id']),
                                 ('billing_consent_associations', 'acceptance_id', a['acceptance_id']),
                                 ('billing_trial_consents', 'consent_id', a['acceptance_id'])]:
        for statement in (f'UPDATE {table} SET {key}={key} WHERE {key}=%s', f'DELETE FROM {table} WHERE {key}=%s'):
            with owner_db.cursor() as cur, pytest.raises(psycopg2.Error):
                cur.execute(statement, (identity,))


@pytest.mark.parametrize('field,value', [('provider_checkout_id', 'wrong-checkout'), ('terms_digest', 'sha256:'+'b'*64),
                                        ('customer_operation_id', None), ('initiated_by', '00000000-0000-0000-0000-000000000000')])
def test_conflicting_association_rejected(owner_db, associated_context, field, value):
    party, _, _, a, operation = associated_context
    if field == 'initiated_by':
        value = str(uuid.uuid4())
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO users(user_id,email,password_hash) VALUES(%s,%s,'synthetic')", (value, value+'@example.test'))
    with owner_db.cursor() as cur:
        cur.execute('ALTER TABLE billing_observation_operations DISABLE TRIGGER observation_guard')
        cur.execute(f'UPDATE billing_observation_operations SET {field}=%s WHERE operation_id=%s', (value, operation['operation_id']))
        cur.execute('ALTER TABLE billing_observation_operations ENABLE TRIGGER observation_guard')
    with pytest.raises(R.ConsentError):
        associate(party, a, operation)
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_trial_consents WHERE consent_id=%s', (a['acceptance_id'],))
        assert cur.fetchone() == (0,)


def test_withdrawn_acceptance_cannot_be_bridged(associated_context):
    party, _, p, a, operation = associated_context
    invalidate(party, p, R.ConsentState.WITHDRAWN)
    with pytest.raises(R.ConsentError):
        associate(party, a, operation)


def test_wrong_customer_identity_rejected_by_composite_fk(owner_db, associated_context):
    party, _, _, a, operation = associated_context
    # The tenant/binding has exactly one immutable Customer. Even an installer
    # bypassing the B3 UPDATE guard cannot persist a different Customer identity.
    with owner_db.cursor() as cur:
        cur.execute('ALTER TABLE billing_observation_operations DISABLE TRIGGER observation_guard')
    try:
        with owner_db.cursor() as cur, pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("UPDATE billing_observation_operations SET provider_customer_id='cus_wrong_synthetic' WHERE operation_id=%s", (operation['operation_id'],))
    finally:
        with owner_db.cursor() as cur:
            cur.execute('ALTER TABLE billing_observation_operations ENABLE TRIGGER observation_guard')
    assert associate(party, a, operation)['provider_customer_id'] == operation['provider_customer_id']


def test_checkout_preparation_closes_acceptance_window(presentation):
    party, r, p = presentation
    with closing(db.billing_setup_connection(*party)) as conn:
        trial_checkouts.operation(conn, r['attempt_id'], 'prepare', payload={'synthetic': True}, replay_window_seconds=3600)
        conn.commit()
    with pytest.raises(R.ConsentError):
        accept(party, p)
    with pytest.raises(R.ConsentError):
        present(party, r, p['policy_id'])


def test_cross_binding_and_tenant_operation_rejected(owner_db, associated_context, parties):
    party, _, _, a, _ = associated_context
    other = parties[1]
    # Switch the selected binding AFTER the original acceptance. Its frozen
    # association must continue using the original merchant/environment.
    binding = 'synthetic-second-binding-'+uuid.uuid4().hex
    with owner_db.cursor() as cur:
        cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        cur.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'stripe','test',%s,true,'synthetic cross-binding test')", (binding, binding))
        cur.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) SELECT %s,price_id,'price_second_'||price_id::text,'synthetic' FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL", (binding,))
    r = reserve(other)
    with owner_db.cursor() as cur:
        cur.execute('INSERT INTO billing_customer_references(tenant_id,binding_id,provider_customer_id) VALUES(%s,%s,%s)', (other[0], r['binding_id'], 'cus_synthetic_other_'+r['attempt_id']))
    other_operation = checkout(other, r)
    with pytest.raises(R.ConsentError):
        associate(party, a, other_operation)
    assert associate(party, a, associated_context[4])['binding_id'] != binding


def test_rollback_acceptance(owner_db, presentation):
    party, _, p = presentation
    with closing(service(party)) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT billing_consent_accept(%s,%s,%s,%s)', (str(uuid.uuid4()), p['presentation_id'], p['challenge'], p['terms_digest']))
        conn.rollback()
    assert accept(party, p)['actor_id'] == party[1]


def test_bridge_insert_failure_rolls_back_b4_consent(owner_db, associated_context):
    party, _, _, a, operation = associated_context
    with owner_db.cursor() as cur:
        cur.execute("CREATE FUNCTION a1_injected_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic injected failure'; END $$")
        cur.execute('CREATE TRIGGER a1_injected_failure BEFORE INSERT ON billing_consent_associations FOR EACH ROW EXECUTE FUNCTION a1_injected_failure()')
    try:
        with pytest.raises(R.ConsentError):
            associate(party, a, operation)
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_trial_consents WHERE consent_id=%s', (a['acceptance_id'],))
            assert cur.fetchone() == (0,)
    finally:
        with owner_db.cursor() as cur:
            cur.execute('DROP TRIGGER a1_injected_failure ON billing_consent_associations')
            cur.execute('DROP FUNCTION a1_injected_failure()')
    assert associate(party, a, operation)['acceptance_id'] == a['acceptance_id']


@pytest.mark.parametrize('role', ['ceopro_app', 'ceopro_billing_setup', 'ceopro_billing_webhook', 'ceopro_credit_accounting',
                                 'ceopro_billing_observer', 'ceopro_trial_attestor', 'ceopro_trial_confirmer', 'ceopro_consent_service'])
def test_effective_acl_real_logins_and_no_set_role(owner_db, parties, role):
    with closing(service(parties[0], role)) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
            assert cur.fetchone() == (role, role, False, False)
            cur.execute("SELECT has_table_privilege(current_user,'billing_consent_acceptances','INSERT'),has_table_privilege(current_user,'billing_trial_consents','INSERT'),pg_has_role(current_user,'ceopro_consent_owner','SET')")
            assert cur.fetchone() == (False, False, False)
            cur.execute("SELECT has_function_privilege(current_user,'billing_consent_accept(uuid,uuid,text,text)','EXECUTE')")
            assert cur.fetchone() == (role == 'ceopro_consent_service',)
            if role not in ('ceopro_trial_attestor', 'ceopro_trial_confirmer'):
                cur.execute("SELECT has_function_privilege(current_user,'billing_confirmation_apply(uuid)','EXECUTE')")
                assert cur.fetchone() == (False,)
        if role != 'ceopro_consent_service':
            with pytest.raises(R.ConsentError, match='restricted_consent_socket_required'):
                R.ConsentRepository(conn)
            with conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute('SELECT billing_consent_accept(NULL,NULL,NULL,NULL)')
            conn.rollback()
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute('INSERT INTO billing_consent_acceptances DEFAULT VALUES')
        conn.rollback()
        with conn.cursor() as cur, pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute('SET ROLE ceopro_consent_owner')


def test_force_rls_and_owner_scope_with_no_public_execute(owner_db, parties, presentation):
    _, _, p = presentation
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_class WHERE relname LIKE 'billing_consent_%' AND relkind='r' AND relrowsecurity AND relforcerowsecurity")
        assert cur.fetchone() == (5,)
        cur.execute("SELECT count(*) FROM pg_proc p, LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.proname LIKE 'billing_consent_%' AND a.grantee=0 AND a.privilege_type='EXECUTE'")
        assert cur.fetchone() == (0,)
        for role in ('ceopro_consent_owner', 'ceopro_consent_service'):
            cur.execute("SELECT has_function_privilege(%s,'billing_confirmation_apply(uuid)','EXECUTE'),has_schema_privilege(%s,'public','CREATE')", (role, role))
            assert cur.fetchone() == (False, False)
        cur.execute("SELECT count(*) FROM pg_auth_members WHERE roleid IN ('ceopro_consent_owner'::regrole,'ceopro_consent_service'::regrole) OR member IN ('ceopro_consent_owner'::regrole,'ceopro_consent_service'::regrole)")
        assert cur.fetchone() == (0,)
        cur.execute('BEGIN')
        try:
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)", parties[1])
            cur.execute('SET LOCAL ROLE ceopro_consent_owner')
            cur.execute('SELECT count(*) FROM billing_consent_presentations WHERE presentation_id=%s', (p['presentation_id'],))
            assert cur.fetchone() == (0,)
        finally:
            cur.execute('ROLLBACK')


def test_active_signup_workspace_and_trial_remain_compatible(owner_db, restricted_runtime, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.routers import auth, billing
    from src.ai.tests.signup_helpers import create_verified_test_account
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(billing.router)
    name = uuid.uuid4().hex
    # Synthetic email delivery; native registration, verification, roles, trial
    # SQL and entitlement projection remain unchanged and execute for real.
    with TestClient(app) as client:
        session = create_verified_test_account(client, dict(full_name='Synthetic A1 Regression',
            business_name='Synthetic A1 Signup', email='consent-'+name+'@example.test', country_code='JO',
            primary_currency='JOD', password='Synthetic!Consent-2026'))
        headers = {'Authorization': 'Bearer '+session['access_token']}
        response = client.get('/billing/subscription', headers=headers)
        assert response.status_code == 200
        assert response.json()['status'] == 'trialing' and response.json()['hasAccess']
        workspace = client.post('/auth/workspaces', headers=headers,
            json=dict(business_name='Synthetic A1 Workspace', country_code='JO', primary_currency='JOD'))
        assert workspace.status_code == 201, workspace.text
        other = workspace.json()
        assert other['tenant_id'] != session['tenant_id']
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_trials WHERE started_by_user_id=%s', (session['user_id'],))
            assert cur.fetchone() == (1,)
            cur.execute('SELECT count(*) FROM billing_consent_acceptances WHERE actor_id=%s', (session['user_id'],))
            assert cur.fetchone() == (0,)
