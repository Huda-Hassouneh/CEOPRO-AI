"""B4 native PG17 tests. Provider AND local-consent evidence is synthetic.

Only the isolated installer seeds consent and enables dedicated test logins.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import os
from threading import Event
import time
import uuid

import psycopg2
import pytest
from psycopg2.extras import Json
from src.ai import db
from src.ai.billing import payment_contracts as C, verification_observations as V, trial_confirmation as T
from src.ai.core import usage
from .test_verification_observations_db import parties, restricted_runtime, ContextConnection, connection, customer_scenario, resolve_customer
from .test_payment_bindings_db import fingerprint, reserve
from src.ai.billing import trial_checkouts


def bound(party, role):
    settings = psycopg2.extensions.parse_dsn(os.environ['BILLING_TEST_DATABASE_URL'])
    settings.update(user=role, password=os.environ['OBSERVATION_TEST_PASSWORD'])
    return ContextConnection(db._UnpooledOwner(), psycopg2.connect(**settings), *party)


@pytest.fixture
def evidence(owner_db, customer_scenario):
    resolve_customer(customer_scenario)  # real durable SQL, offline provider double
    party=customer_scenario[0]
    reservation=reserve(party)
    with closing(db.billing_setup_connection(*party)) as conn:
        trial_checkouts.operation(conn,reservation['attempt_id'],'prepare',payload={'synthetic':True},replay_window_seconds=3600)
        trial_checkouts.operation(conn,reservation['attempt_id'],'submitted')
        trial_checkouts.operation(conn,reservation['attempt_id'],'session',session='cs_'+reservation['attempt_id'])
        conn.commit()
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);request=V.trial_request(repo.context(reservation['attempt_id']))
        row=repo.begin(uuid.uuid4(),request)
    now = datetime.now(timezone.utc)
    ref = lambda x: C.ProviderReference(request.binding.provider, x, binding=request.binding)
    authority = C.RecurringAuthorizationEvidence(request.customer, ref('setup_test'),
        C.RecurringAuthorizationKind.PAYMENT_METHOD_SETUP, C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED)
    base = C.ProviderVerificationObservation(request,
        C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP, request.checkout, now, 'synthetic-b4', 'synthetic-api'),
        C.VerificationOutcome.PENDING, C.GatewayCapabilities(**{f.name:C.CapabilityState.SUPPORTED for f in fields(C.GatewayCapabilities)}),
        customer=request.customer, checkout=request.checkout, subscription=ref('sub_'+row['operation_id']),
        checkout_state=C.CheckoutState.COMPLETE, subscription_state=C.SubscriptionState.TRIALING,
        terms=request.expected_terms, trial=C.ObservedTrialWindow(now, now+timedelta(days=request.approved_terms.trial_duration_days),
        now+timedelta(days=request.approved_terms.trial_duration_days)),
        payment_method=C.PaymentMethodEvidence(request.customer, ref('setup_test'), now,
            C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED, ref('pm_test')),
        recurring_authorization=authority, cancel_at_period_end=False)
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn)
        repo.record(repo.claim(row),uuid.uuid4(),base)
        claim=repo.claim(repo.read(row['operation_id']))
    consent=str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute('INSERT INTO billing_trial_consents(consent_id,operation_id,tenant_id,binding_id,provider_customer_id,actor_id,agreement_reference,agreement_revision,accepted_at,provenance) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (consent,row['operation_id'],party[0],request.binding.binding_id,request.customer.opaque_id,party[1],
             'keel-agreement-test','agreement-v1',now-timedelta(seconds=1),'ISOLATED SYNTHETIC TRUSTED CONSENT'))
    verified=replace(base, outcome=C.VerificationOutcome.VERIFIED, recurring_authorization=replace(authority,
        consent=C.RecurringConsentState.RECORDED, consent_reference=ref('keel-agreement-test'), consent_terms_revision='agreement-v1'))
    return party,request,claim,base,verified,consent


def attest(evidence, **overrides):
    party,_,claim,_,verified,consent=evidence
    args=dict(checkout_completed_at=verified.provenance.observed_at,
              checkout_expires_at=verified.provenance.observed_at+timedelta(hours=1))
    args.update(overrides)
    with closing(bound(party,'ceopro_trial_attestor')) as conn:
        return T.TrialConfirmationRepository(conn,attestor=True).attest(claim,verified,consent,**args).unpack()


def confirm(evidence, attestation):
    with closing(bound(evidence[0],'ceopro_trial_confirmer')) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='10s'")
        return T.TrialConfirmationRepository(conn).confirm(attestation['attestation_id']).unpack()


def test_atomic_confirmation_and_exact_repeat_preserve_cutoff_and_credits(owner_db,evidence):
    party,request,claim,_,verified,_=evidence
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM tenant_credit_balances');credits=cur.fetchone()
        cur.execute('SELECT count(*) FROM usage_ledger');ledger=cur.fetchone()
    a=attest(evidence);result=confirm(evidence,a)
    assert confirm(evidence,a)==result
    with owner_db.cursor() as cur:
        cur.execute('SELECT state,confirmation_id FROM billing_trial_checkouts WHERE attempt_id=%s',(request.reservation_id,))
        assert cur.fetchone()==('confirmed',result['confirmation_id'])
        cur.execute('SELECT state FROM billing_checkout_attempts WHERE attempt_id=%s',(request.reservation_id,))
        assert cur.fetchone()==('confirmed',)
        cur.execute('SELECT started_at,ends_at FROM billing_trials WHERE tenant_id=%s',(party[0],))
        assert cur.fetchone()==(verified.trial.started_at,verified.trial.ends_at)
        cur.execute('SELECT trial_end,status FROM billing_subscriptions WHERE tenant_id=%s',(party[0],))
        assert cur.fetchone()==(verified.trial.ends_at,'trialing')
        cur.execute('SELECT count(*) FROM tenant_credit_balances');assert cur.fetchone()==credits
        cur.execute('SELECT count(*) FROM usage_ledger');assert cur.fetchone()==ledger
    with closing(db.app_role_connection(*party)) as conn:
        assert usage.get_plan(conn,party[0],now=verified.trial.ends_at)['status']=='expired'


def test_catalog_change_and_insert_update_snapshot_and_override_precedence(owner_db,evidence):
    party,request,*_=evidence
    a=attest(evidence)
    with owner_db.cursor() as cur:
        cur.execute('SELECT approved_terms FROM billing_trial_checkouts WHERE attempt_id=%s',(request.reservation_id,));terms=cur.fetchone()[0]
        cur.execute("SELECT limit_value,trial_limit_value FROM usage_plan_limits WHERE plan_key='growth' AND feature_code='tracked_products'");old=cur.fetchone()
        cur.execute("UPDATE usage_plan_limits SET limit_value=987654,trial_limit_value=123456 WHERE plan_key='growth' AND feature_code='tracked_products'")
    try:
        confirm(evidence,a)
        with owner_db.cursor() as cur:
            cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(party[0],));snap=cur.fetchone()[0]
            assert snap['features']==terms['features'] and snap['entitlements']==terms['entitlements']
            assert snap['catalog_version']==terms['entitlement_version']
            assert snap['commercial_catalog_version']==terms['catalog_version']
            cur.execute('BEGIN')
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party)
            cur.execute("UPDATE tenant_plan_assignments SET catalog_snapshot='{}'::jsonb WHERE tenant_id=%s",(party[0],))
            cur.execute('COMMIT')
            cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(party[0],));assert cur.fetchone()[0]==snap
            cur.execute("INSERT INTO tenant_entitlement_overrides(tenant_id,feature_code,limit_value,contract_ref,approved_by,reason) VALUES(%s,'tracked_products',77,'synthetic-owner','isolated-installer','test')",(party[0],))
        with closing(db.app_role_connection(*party)) as conn:
            assert usage.get_plan(conn,party[0])['features']['tracked_products']['limit']==77
    finally:
        with owner_db.cursor() as cur:cur.execute("UPDATE usage_plan_limits SET limit_value=%s,trial_limit_value=%s WHERE plan_key='growth' AND feature_code='tracked_products'",old)


def test_timestamp_only_refresh_preserves_history_without_material_conflict(owner_db,evidence):
    party,_,claim,base,_,_=evidence
    # Release only this fixture claim so the observer can record its fresh read.
    with owner_db.cursor() as cur:
        cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party)
        cur.execute('SET LOCAL ROLE ceopro_observation_owner')
        cur.execute("UPDATE billing_observation_operations SET claim_until=clock_timestamp()-interval '1 second',version=version+1 WHERE operation_id=%s",(claim['operation_id'],))
        cur.execute('COMMIT')
    refreshed=replace(base,payment_method=replace(base.payment_method,observed_at=base.payment_method.observed_at+timedelta(microseconds=1)))
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);repo.record(repo.claim(repo.read(claim['operation_id'])),uuid.uuid4(),refreshed)
        assert not repo.read(claim['operation_id'])['has_conflict']
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(DISTINCT evidence_digest) FROM billing_verification_observations WHERE operation_id=%s',(claim['operation_id'],))
        assert cur.fetchone()==(2,)


@pytest.mark.parametrize('fact',['subscription','terms','consent','binding','environment','provider','capability','readiness','future_trial_start'])
def test_forged_attestation_cannot_replace_provider_facts(owner_db,evidence,fact):
    party,request,claim,base,verified,consent=evidence
    doc=V.evidence_document(verified);req=V.request_document(request)
    if fact=='subscription':doc['subscription']='unrelated_same_customer'
    elif fact=='terms':doc['terms']['amount']='0'
    elif fact=='consent':consent=str(uuid.uuid4())
    elif fact=='binding':req['binding']['merchant_account_id']='different-account'
    elif fact=='environment':req['binding']['environment']='live'
    elif fact=='provider':req['binding']['provider']='unapproved-provider'
    elif fact=='capability':doc['capabilities']['off_session_recurring']='unknown'
    elif fact=='readiness':doc['recurring_authority']['readiness']='attached'
    else:
        doc['trial']={k:(verified.trial.started_at+timedelta(seconds=20)+(timedelta(days=request.approved_terms.trial_duration_days) if k!='started_at' else timedelta())).isoformat() for k in ('started_at','ends_at','cutoff')}
    with closing(bound(party,'ceopro_trial_attestor')) as conn:
        with pytest.raises(psycopg2.Error) as failure:
            with conn.cursor() as cur:cur.execute('SELECT billing_confirmation_attest(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()),claim['operation_id'],claim['version'],claim['claim_token'],consent,Json(req),Json(doc),
                 verified.provenance.observed_at,verified.provenance.observed_at,verified.provenance.observed_at+timedelta(hours=1)))
        assert failure.value.pgcode in ('22023','55000')


@pytest.mark.parametrize('conflict',['expired_claim','used_tenant','used_person','current_subscription','released','expired_checkout','expired_attempt'])
def test_stale_eligibility_and_late_confirmation_fail_closed(owner_db,evidence,parties,conflict):
    party,request,claim,base,verified,_=evidence;a=attest(evidence)
    with owner_db.cursor() as cur:
        if conflict=='expired_claim':
            cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party);cur.execute('SET LOCAL ROLE ceopro_observation_owner')
            cur.execute("UPDATE billing_observation_operations SET claim_until=clock_timestamp()-interval '1 second',version=version+1 WHERE operation_id=%s",(claim['operation_id'],));assert cur.rowcount==1;cur.execute('COMMIT')
        elif conflict in ('used_tenant','used_person'):
            tid=party[0] if conflict=='used_tenant' else parties[1][0]
            cur.execute("INSERT INTO billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(%s,'growth',now()-interval '30 days',now()-interval '16 days',%s)",(tid,party[1]))
        elif conflict=='current_subscription':
            cur.execute("INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,plan_key,period_code,status) VALUES(%s,%s,'other_customer','growth','monthly','active')",(party[0],'other_sub_'+uuid.uuid4().hex))
        elif conflict=='released':
            # Administrative fixture models a previously released terminal reservation.
            cur.execute("UPDATE billing_trial_checkouts SET state='released',released_at=now(),release_reason='unsubmitted' WHERE attempt_id=%s",(request.reservation_id,))
        elif conflict=='expired_attempt':
            cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party)
            cur.execute('SET LOCAL ROLE ceopro_trial_issuer')
            cur.execute("UPDATE billing_checkout_attempts SET state='expired' WHERE attempt_id=%s",(request.reservation_id,));assert cur.rowcount==1;cur.execute('COMMIT')
        else:
            # Immutable attestation cannot be edited; test the expiry at attestation boundary instead.
            with pytest.raises(T.ConfirmationError):attest(evidence,checkout_expires_at=verified.provenance.observed_at-timedelta(seconds=1))
            return
    before=fingerprint(owner_db)
    with pytest.raises(T.ConfirmationError):confirm(evidence,a)
    assert fingerprint(owner_db)==before


def test_atomic_assignment_failure_rolls_back_every_rights_change(owner_db,evidence):
    a=attest(evidence);before=fingerprint(owner_db)
    with owner_db.cursor() as cur:
        cur.execute("CREATE FUNCTION b4_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic assignment failure'; END $$")
        cur.execute('CREATE TRIGGER b4_fail BEFORE INSERT ON tenant_plan_assignments FOR EACH ROW EXECUTE FUNCTION b4_fail()')
    try:
        with pytest.raises(T.ConfirmationError):confirm(evidence,a)
        assert fingerprint(owner_db)==before
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_trial_confirmations WHERE attestation_id=%s',(a['attestation_id'],));assert cur.fetchone()==(0,)
    finally:
        with owner_db.cursor() as cur:cur.execute('DROP TRIGGER b4_fail ON tenant_plan_assignments');cur.execute('DROP FUNCTION b4_fail()')
    confirm(evidence,a)


def test_duplicate_concurrent_confirmation_is_idempotent(evidence):
    a=attest(evidence)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:confirm(evidence,a),range(2)))
    assert results[0]==results[1]


def test_different_attestation_cannot_reissue_existing_trial(evidence):
    first=attest(evidence);second=attest(evidence)
    result=confirm(evidence,first)
    with pytest.raises(T.ConfirmationError,match='22023'):confirm(evidence,second)
    assert confirm(evidence,first)==result


def test_wrong_tenant_cannot_confirm_or_read_attestation(evidence,parties):
    a=attest(evidence)
    with closing(bound(parties[1],'ceopro_trial_confirmer')) as conn:
        with pytest.raises(T.ConfirmationError,match='42501'):
            T.TrialConfirmationRepository(conn).confirm(a['attestation_id'])


def test_real_runtime_roles_cannot_attest_confirm_write_consent_or_set_role(owner_db,evidence):
    party,*_=evidence
    for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting','ceopro_billing_observer'):
        with closing(bound(party,role)) as conn:
            for sql in ("SELECT billing_confirmation_apply(gen_random_uuid())",'SELECT * FROM billing_trial_consents',
                        'SET ROLE ceopro_trial_confirmer','SET ROLE ceopro_trial_attestor','SET ROLE ceopro_confirmation_owner'):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    with conn.cursor() as cur:cur.execute(sql)
                conn.rollback()
    with owner_db.cursor() as cur:
        for table in ('billing_trial_consents','billing_trial_attestations','billing_trial_confirmations'):
            cur.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,));assert cur.fetchone()==(True,True)
        cur.execute("SELECT count(*) FROM pg_auth_members WHERE roleid IN ('ceopro_confirmation_owner'::regrole,'ceopro_trial_attestor'::regrole,'ceopro_trial_confirmer'::regrole) OR member IN ('ceopro_confirmation_owner'::regrole,'ceopro_trial_attestor'::regrole,'ceopro_trial_confirmer'::regrole)")
        assert cur.fetchone()==(0,)
        cur.execute("SELECT has_table_privilege('ceopro_confirmation_owner','billing_trial_consents','INSERT')");assert cur.fetchone()==(False,)
        cur.execute("SELECT proowner::regrole::text,proconfig,has_function_privilege('ceopro_app',oid,'EXECUTE') FROM pg_proc WHERE proname LIKE 'billing_confirmation_%'")
        for owner,config,app in cur.fetchall():
            assert owner=='ceopro_confirmation_owner' and config==['search_path=pg_catalog, public, pg_temp'] and not app
    for role in ('ceopro_trial_attestor','ceopro_trial_confirmer'):
        with closing(bound(party,role)) as conn:
            for sql in ('INSERT INTO billing_trial_consents(consent_id) VALUES(gen_random_uuid())',
                        'UPDATE tenant_plan_assignments SET trial_confirmation_id=NULL',
                        "SELECT billing_setup_trial('growth',true)",
                        'SET ROLE ceopro_confirmation_owner'):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    with conn.cursor() as cur:cur.execute(sql)
                conn.rollback()


def expire_claim(owner_db,party,operation):
    with owner_db.cursor() as cur:
        cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party);cur.execute('SET LOCAL ROLE ceopro_observation_owner')
        cur.execute("UPDATE billing_observation_operations SET claim_until=clock_timestamp()-interval '1 second',version=version+1 WHERE operation_id=%s",(operation,));assert cur.rowcount==1;cur.execute('COMMIT')


@pytest.mark.parametrize('material',[False,True])
def test_legacy_conflict_history_is_preserved_and_only_semantic_equivalence_can_confirm(owner_db,evidence,material):
    party,request,claim,base,verified,consent=evidence
    expire_claim(owner_db,party,claim['operation_id'])
    refreshed=replace(base,payment_method=replace(base.payment_method,observed_at=base.payment_method.observed_at+timedelta(microseconds=2)))
    if material:refreshed=replace(refreshed,subscription=C.ProviderReference(request.binding.provider,'other_subscription',binding=request.binding))
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);repo.record(repo.claim(repo.read(claim['operation_id'])),uuid.uuid4(),refreshed)
    # Model the pre-B4 full-digest rule: sticky conflict due to timestamp alone.
    with owner_db.cursor() as cur:
        cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party);cur.execute('SET LOCAL ROLE ceopro_observation_owner')
        cur.execute("UPDATE billing_observation_operations SET has_conflict=true,state='reconciliation_required',version=version+1 WHERE operation_id=%s",(claim['operation_id'],));assert cur.rowcount==1;cur.execute('COMMIT')
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);newclaim=repo.claim(repo.read(claim['operation_id']))
    revised=(party,request,newclaim,base,verified,consent)
    if material:
        with pytest.raises(T.ConfirmationError):attest(revised)
    else:confirm(revised,attest(revised))
    with owner_db.cursor() as cur:
        cur.execute('SELECT has_conflict FROM billing_observation_operations WHERE operation_id=%s',(claim['operation_id'],));assert cur.fetchone()==(True,)
        cur.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s',(claim['operation_id'],));assert cur.fetchone()==(2,)


def test_actual_checkout_webhook_customer_row_precedes_subscription_lock_without_cycle(owner_db,evidence):
    from src.ai.billing import store
    party,_,_,_,verified,_=evidence;a=attest(evidence)
    held=Event();release=Event();eid='evt_b4_'+uuid.uuid4().hex
    sub=dict(id=verified.subscription.opaque_id,customer=verified.customer.opaque_id,status='trialing',
             trial_end=int(verified.trial.ends_at.timestamp()),current_period_start=int(verified.trial.started_at.timestamp()),
             current_period_end=int(verified.trial.ends_at.timestamp()),items={'data':[{'price':{'id':verified.terms.price.opaque_id}}]})
    def webhook():
        with closing(db.billing_webhook_connection(eid)) as conn:
            store.claim_event(conn,eid,'customer.subscription.updated',datetime.now(timezone.utc),{'data':{'object':sub}})
            conn.commit();conn.bind_tenant(party[0])
            store.save_customer(conn,party[0],sub['customer'])
            held.set();assert release.wait(10)
            with conn.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('keel_stripe_subscription:'+sub['id'],))
            store.apply_subscription(conn,party[0],sub,'growth','monthly',datetime.now(timezone.utc));conn.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            legacy=pool.submit(webhook);assert held.wait(5)
            pending=pool.submit(confirm,evidence,a)
            deadline=time.monotonic()+5
            while True:
                with owner_db.cursor() as cur:
                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE usename='ceopro_trial_confirmer' AND wait_event IN ('transactionid','tuple')")
                    if cur.fetchone()[0]:break
                assert time.monotonic()<deadline,'Confirmation did not wait at the legacy Customer row'
                time.sleep(.02)
            release.set();legacy.result(timeout=5)
            with pytest.raises(T.ConfirmationError):pending.result(timeout=5)
    finally:release.set()
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_trial_confirmations WHERE tenant_id=%s',(party[0],));assert cur.fetchone()==(0,)
        cur.execute('SELECT stripe_subscription_id FROM billing_subscriptions WHERE tenant_id=%s',(party[0],));assert cur.fetchone()==(sub['id'],)


def test_subscription_first_webhook_causes_nonblocking_confirmation_rollback(owner_db,evidence):
    from src.ai.billing import store
    party,request,_,_,verified,_=evidence;a=attest(evidence)
    held=Event();release=Event();eid='evt_b4_inverse_'+uuid.uuid4().hex
    sub=dict(id=verified.subscription.opaque_id,customer=verified.customer.opaque_id,status='trialing',
             trial_end=int(verified.trial.ends_at.timestamp()),current_period_start=int(verified.trial.started_at.timestamp()),
             current_period_end=int(verified.trial.ends_at.timestamp()),items={'data':[{'price':{'id':verified.terms.price.opaque_id}}]})
    def webhook():
        with closing(db.billing_webhook_connection(eid)) as conn:
            store.claim_event(conn,eid,'customer.subscription.updated',datetime.now(timezone.utc),{'data':{'object':sub}})
            conn.commit();conn.bind_tenant(party[0])
            with conn.cursor() as cur:cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('keel_stripe_subscription:'+sub['id'],))
            held.set();assert release.wait(10)
            store.save_customer(conn,party[0],sub['customer'])
            store.apply_subscription(conn,party[0],sub,'growth','monthly',datetime.now(timezone.utc));conn.commit()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            worker=pool.submit(webhook);assert held.wait(5)
            with pytest.raises(T.ConfirmationError,match='55000'):confirm(evidence,a)
            # Failed try-lock rolls back even the preceding Customer bridge write.
            with owner_db.cursor() as cur:
                cur.execute('SELECT count(*) FROM billing_customers WHERE tenant_id=%s',(party[0],));assert cur.fetchone()==(0,)
                cur.execute('SELECT state FROM billing_trial_checkouts WHERE attempt_id=%s',(request.reservation_id,));assert cur.fetchone()==('pending',)
            release.set();worker.result(timeout=5)
    finally:release.set()


def second_owner(owner_db, evidence, parties):
    party=evidence[0];other=(party[0],parties[1][1])
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",other)
    return other


def wait_for_blocker(owner_db, pid, blocker=None):
    """Observe an actual lock edge; elapsed sleeps are not the barrier."""
    deadline=time.monotonic()+8
    while True:
        with owner_db.cursor() as cur:
            cur.execute('SELECT pg_stat_clear_snapshot()')
            cur.execute('SELECT pg_blocking_pids(%s)',(pid,))
            blockers=cur.fetchone()[0]
        if blockers and (blocker is None or blocker in blockers):return
        assert time.monotonic()<deadline,'Expected database lock edge not established'
        time.sleep(.01)


def end_barrier(owner_db, *, commit=False):
    # owner_db is autocommit=True: explicit BEGIN barriers must use SQL COMMIT /
    # ROLLBACK. psycopg2's commit()/rollback() do not end them in that mode.
    with owner_db.cursor() as cur:cur.execute('COMMIT' if commit else 'ROLLBACK')


def mutate_authority(conn, party, change):
    """Use real application statements/platform commands, never SET ROLE."""
    with conn.cursor() as cur:
        cur.execute("SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert cur.fetchone()==('ceopro_app','ceopro_app',False,False)
        cur.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='10s'")
    if change in ('staff','admin','accountant','remove'):
        usage.lock_feature(conn,party[0],usage.TEAM_SEATS)
        with conn.cursor() as cur:
            if change=='remove':
                cur.execute('UPDATE tenant_users SET removed_at=clock_timestamp() WHERE tenant_id=%s AND user_id=%s',party)
            else:
                cur.execute('UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s AND user_id=%s',(change,*party))
            assert cur.rowcount==1
    else:
        action={'member_suspend':'membership_status','user_suspend':'user_status','company_suspend':'company_status'}[change]
        target=party[1] if change=='user_suspend' else party[0]
        if change=='member_suspend':
            with conn.cursor() as cur:
                cur.execute("SELECT keel_platform_command('company',%s)",(Json({'id':party[0]}),))
                members=cur.fetchone()[0]['members']
                target=next(m['tenant_user_id'] for m in members if m['user_id']==party[1])
        with conn.cursor() as cur:
            cur.execute('SELECT keel_platform_command(%s,%s)',(action,Json({'id':target,'active':False,'reason':'Isolated authorization race regression'})))
            result=cur.fetchone()[0]
            assert result.get('active',False) is False and 'error' not in result,result


def assert_no_confirmation_rights(owner_db,evidence,before):
    assert fingerprint(owner_db)==before
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_trial_confirmations WHERE tenant_id=%s',(evidence[0][0],))
        assert cur.fetchone()==(0,)
        cur.execute('SELECT state,confirmation_id FROM billing_trial_checkouts WHERE attempt_id=%s',(evidence[1].reservation_id,))
        assert cur.fetchone()==('pending',None)
        cur.execute('SELECT state FROM billing_checkout_attempts WHERE attempt_id=%s',(evidence[1].reservation_id,))
        assert cur.fetchone()==('open',)


@pytest.mark.parametrize('initial,change',[
    ('owner','staff'),('admin','staff'),('accountant','staff'),('owner','remove'),
    ('owner','member_suspend'),('owner','user_suspend'),('owner','company_suspend'),
    ('owner','admin'),('admin','accountant'),('accountant','admin')])
def test_authorization_change_commits_while_confirmation_waits_on_customer(
        owner_db,evidence,parties,platform_owner_context,initial,change):
    """Permanent reproduction of the rejected probe: revocation wins."""
    party,request,*_=evidence
    a=attest(evidence);other=second_owner(owner_db,evidence,parties)
    with owner_db.cursor() as cur:
        cur.execute('UPDATE tenant_users SET role_key=%s WHERE tenant_id=%s AND user_id=%s',(initial,*party))
        cur.execute('INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,%s)',(party[0],request.customer.opaque_id))
    before=fingerprint(owner_db)
    with closing(bound(party,'ceopro_trial_confirmer')) as confirmer:
        pid=confirmer._raw.get_backend_pid()
        with owner_db.cursor() as cur:
            cur.execute('BEGIN');cur.execute('SELECT 1 FROM billing_customers WHERE tenant_id=%s FOR UPDATE',(party[0],))
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                def apply():
                    with confirmer.cursor() as cur:cur.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='10s'")
                    return T.TrialConfirmationRepository(confirmer).confirm(a['attestation_id'])
                pending=pool.submit(apply)
                try:
                    wait_for_blocker(owner_db,pid,owner_db.get_backend_pid())
                    actor=other if change in ('staff','admin','accountant','remove') else platform_owner_context
                    with closing(db.app_role_connection(*actor)) as revoker:
                        mutate_authority(revoker,party,change);revoker.commit()
                    end_barrier(owner_db,commit=True)
                    if change in ('admin','accountant'):
                        assert pending.result(timeout=10).unpack()['started_by_user_id']==party[1]
                    else:
                        with pytest.raises(T.ConfirmationError,match='^confirmation_42501$'):
                            pending.result(timeout=10)
                finally:end_barrier(owner_db)
        finally:end_barrier(owner_db)
    if change not in ('admin','accountant'):assert_no_confirmation_rights(owner_db,evidence,before)


@pytest.mark.parametrize('change',['staff','remove','member_suspend','user_suspend','company_suspend'])
def test_confirmation_stabilizes_authority_until_commit(
        owner_db,evidence,parties,platform_owner_context,change):
    """Confirmation wins: actual revocation cannot commit before it."""
    party=evidence[0];a=attest(evidence);other=second_owner(owner_db,evidence,parties)
    with closing(bound(party,'ceopro_trial_confirmer')) as confirmer:
        with confirmer.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='8s'; SET LOCAL statement_timeout='10s'")
            cur.execute('SELECT billing_confirmation_apply(%s)',(a['attestation_id'],))
            result=cur.fetchone()[0]
        # Rights are deliberately uncommitted while an authorized revoker tries.
        actor=other if change in ('staff','remove') else platform_owner_context
        with closing(db.app_role_connection(*actor)) as revoker:
            with ThreadPoolExecutor(max_workers=1) as pool:
                def revoke():mutate_authority(revoker,party,change);revoker.commit()
                future=pool.submit(revoke)
                try:
                    wait_for_blocker(owner_db,revoker._raw.get_backend_pid(),confirmer._raw.get_backend_pid())
                    assert not future.done()
                    with owner_db.cursor() as cur:
                        cur.execute('SELECT count(*) FROM billing_trial_confirmations WHERE tenant_id=%s',(party[0],));assert cur.fetchone()==(0,)
                    confirmer.commit()
                    future.result(timeout=10)
                finally:confirmer.rollback()
        with owner_db.cursor() as cur:
            cur.execute('SELECT confirmation_id FROM billing_trial_confirmations WHERE tenant_id=%s',(party[0],))
            assert str(cur.fetchone()[0])==result['confirmation_id']
        with pytest.raises(T.ConfirmationError,match='^confirmation_42501$'):confirm(evidence,a)


@pytest.mark.parametrize('table,key',[('tenant_users','tenant_id'),('users','user_id'),('companies','tenant_id')])
def test_busy_authorization_rows_fail_closed_without_waiting(owner_db,evidence,table,key):
    a=attest(evidence);before=fingerprint(owner_db);party=evidence[0]
    # Fixed allowlist, synthetic installer controls the held row only; confirmation
    # itself uses the real restricted password-authenticated service identity.
    target=party[1] if table=='users' else party[0]
    with owner_db.cursor() as cur:
        cur.execute('BEGIN');cur.execute(f'SELECT 1 FROM {table} WHERE {key}=%s FOR NO KEY UPDATE',(target,))
    try:
        with pytest.raises(T.ConfirmationError,match='^confirmation_55P03$'):confirm(evidence,a)
    finally:end_barrier(owner_db)
    assert_no_confirmation_rights(owner_db,evidence,before)
    confirm(evidence,a)  # Locks released; no poisoned claim or partial rights.


@pytest.mark.parametrize('repeat',[False,True])
@pytest.mark.parametrize('change',['staff','remove','member_suspend','user_suspend','company_suspend'])
def test_revoked_principal_cannot_use_fresh_or_idempotent_confirmation(
        owner_db,evidence,parties,platform_owner_context,repeat,change):
    a=attest(evidence);other=second_owner(owner_db,evidence,parties)
    if repeat:confirm(evidence,a)
    before=fingerprint(owner_db)
    actor=other if change in ('staff','remove') else platform_owner_context
    with closing(db.app_role_connection(*actor)) as revoker:
        mutate_authority(revoker,evidence[0],change);revoker.commit()
    with pytest.raises(T.ConfirmationError,match='^confirmation_42501$'):confirm(evidence,a)
    assert fingerprint(owner_db)==before
    if not repeat:assert_no_confirmation_rights(owner_db,evidence,before)


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_old_transaction_snapshot_cannot_authorize_confirmation(owner_db,evidence,isolation):
    a=attest(evidence);before=fingerprint(owner_db)
    with closing(bound(evidence[0],'ceopro_trial_confirmer')) as conn:
        conn._raw.rollback()  # End constructor's context transaction first.
        conn._raw.set_session(isolation_level=isolation)
        conn._apply_tenant_context()
        with pytest.raises(T.ConfirmationError,match='^confirmation_25001$'):
            T.TrialConfirmationRepository(conn).confirm(a['attestation_id'])
    assert_no_confirmation_rights(owner_db,evidence,before)


def test_platform_authority_reverse_edge_is_nonblocking(owner_db,evidence,platform_owner_context):
    a=attest(evidence);before=fingerprint(owner_db)
    with closing(db.app_role_connection(*platform_owner_context)) as platform:
        with platform.cursor() as cur:
            cur.execute("SELECT keel_platform_command('me','{}')")
            assert 'error' not in cur.fetchone()[0]
        # Real platform boundary owns platform-authority, then waits for B4's
        # billing-tenant in the inverse graph. B4 must never wait on platform.
        with pytest.raises(T.ConfirmationError,match='^confirmation_55P03$'):confirm(evidence,a)
        platform.rollback()
    assert_no_confirmation_rights(owner_db,evidence,before)
