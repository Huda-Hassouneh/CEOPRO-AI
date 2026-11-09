"""PG17, password logins, real FORCE RLS; provider facts are synthetic doubles."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import os
import uuid

import psycopg2
from psycopg2.extras import Json
import pytest

from src.ai import db
from src.ai.billing import verification_observations as V,trial_checkouts
from src.ai.billing import payment_contracts as C
from src.infrastructure.db_pool import PooledTenantConnection
from .test_payment_bindings_db import parties,reserve,fingerprint
from .test_reconciliation_roles import restricted_runtime  # noqa: F401
from .test_customer_operations_db import scenario as customer_scenario,run as resolve_customer


class ContextConnection(PooledTenantConnection):
    def _apply_tenant_context(self):
        with self._raw.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true),set_config('TimeZone','UTC',true)",
                (self._tenant_id,self._user_id))


def role_password(role):
    """Each restricted login has its own credential; never assume equality."""
    runtime = {'ceopro_app': 'APP_DB_PASSWORD',
               'ceopro_billing_setup': 'BILLING_SETUP_DB_PASSWORD',
               'ceopro_billing_webhook': 'BILLING_WEBHOOK_DB_PASSWORD',
               'ceopro_credit_accounting': 'CREDIT_ACCOUNTING_DB_PASSWORD'}
    return os.environ[runtime.get(role, 'OBSERVATION_TEST_PASSWORD')]


def connection(party):
    values=psycopg2.extensions.parse_dsn(os.environ['BILLING_TEST_DATABASE_URL'])
    values.update(user='ceopro_billing_observer',password=role_password('ceopro_billing_observer'))
    raw=psycopg2.connect(**values)
    return ContextConnection(db._UnpooledOwner(),raw,*party)


@pytest.fixture
def scenario(owner_db,parties):
    party=parties[0];r=reserve(party)
    with closing(db.billing_setup_connection(*party)) as conn:
        trial_checkouts.operation(conn,r['attempt_id'],'prepare',payload={'synthetic':True},replay_window_seconds=3600)
        trial_checkouts.operation(conn,r['attempt_id'],'submitted')
        trial_checkouts.operation(conn,r['attempt_id'],'session',session='checkout_'+r['attempt_id'])
        conn.commit()
    with owner_db.cursor() as cur:
        cur.execute('INSERT INTO billing_customer_references(tenant_id,binding_id,provider_customer_id) VALUES(%s,%s,%s)',
            (party[0],r['binding_id'],'customer_'+r['attempt_id']))
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);request=V.trial_request(repo.context(r['attempt_id']))
        row=repo.begin(uuid.uuid4(),request)
    return party,request,row


def observation(request, *, source=C.ObservationSource.AUTHORITATIVE_LOOKUP,event=None,**changes):
    now=datetime.now(timezone.utc)
    ref=lambda value:C.ProviderReference(request.binding.provider,value,binding=request.binding)
    result=C.ProviderVerificationObservation(request,C.ObservationProvenance(source,ref(event) if event else request.checkout,now,'offline-double-v1','offline-api-v1'),
        C.VerificationOutcome.PENDING,customer=request.customer,checkout=request.checkout,subscription=ref('subscription_A'),
        checkout_state=C.CheckoutState.COMPLETE,subscription_state=C.SubscriptionState.TRIALING,terms=request.expected_terms,
        trial=C.ObservedTrialWindow(now,now+timedelta(days=request.approved_terms.trial_duration_days),now+timedelta(days=request.approved_terms.trial_duration_days)))
    return replace(result,**changes)


def record(scenario, *, value=None):
    party,request,row=scenario
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);claimed=repo.claim(repo.read(row['operation_id']))
        return repo.record(claimed,uuid.uuid4(),value or observation(request)),repo.read(row['operation_id'])


def test_record_claim_replay_immutable_evidence_and_no_activation(owner_db,scenario):
    before=fingerprint(owner_db)
    party,request,row=scenario
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);claimed=repo.claim(row);oid=uuid.uuid4();obs=observation(request)
        stored=repo.record(claimed,oid,obs)
        assert repo.record(claimed,oid,obs)==stored  # Lost successful application reply.
        assert stored.unpack()['source']=='authoritative_lookup' and stored.unpack()['receipt_id'] is None
        copy=stored.unpack();copy['evidence']['terms']['amount']='9999'
        assert stored.unpack()['evidence']['terms']['amount']!='9999'
        assert repo.read(row['operation_id'])['state']=='observed'
        with pytest.raises(V.ObservationError):repo.record(claimed,oid,replace(obs,outcome=C.VerificationOutcome.UNAVAILABLE))
    assert fingerprint(owner_db)==before
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE attempt_id=%s',(request.reservation_id,));assert cur.fetchone()==('pending',)


def test_authenticated_receipt_deduplication_is_distinct_from_manual_lookup(scenario):
    party,request,row=scenario;now=datetime.now(timezone.utc);event='event_'+uuid.uuid4().hex
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn)
        receipt=repo.notification(row,event,'sha256:'+'a'*64,now)
        assert repo.notification(row,event,'sha256:'+'a'*64,now)['receipt_id']==receipt['receipt_id']
        with pytest.raises(V.ObservationError):repo.notification(row,event,'sha256:'+'b'*64,now)
        claimed=repo.claim(row)
        with pytest.raises(V.ObservationError):repo.record(claimed,uuid.uuid4(),observation(request),receipt_id=receipt['receipt_id'])
        stored=repo.record(claimed,uuid.uuid4(),observation(request,source=C.ObservationSource.AUTHENTICATED_NOTIFICATION,event=event),receipt_id=receipt['receipt_id'])
        assert stored.unpack()['source']=='authenticated_notification'
        assert stored.unpack()['receipt_id']==receipt['receipt_id']


def test_concurrent_claims_and_changed_request_replay(scenario):
    party,request,row=scenario
    def submit(_):
        with closing(connection(party)) as conn:
            try:V.ObservationRepository(conn).claim(row);return 'claimed'
            except V.ObservationError:return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(submit,range(2)))==['claimed','denied']
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn)
        with pytest.raises(V.ObservationError):repo.begin(row['operation_id'],replace(request,subscription=C.ProviderReference(request.binding.provider,'wrong',binding=request.binding)))


def expire(owner_db,scenario):
    party,_,row=scenario
    with owner_db.cursor() as cur:
        cur.execute('BEGIN')
        cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party)
        cur.execute('SET LOCAL ROLE ceopro_observation_owner')
        cur.execute("UPDATE billing_observation_operations SET claim_until=clock_timestamp()-interval '1 second',version=version+1 WHERE operation_id=%s",(row['operation_id'],))
        assert cur.rowcount==1
        cur.execute('COMMIT')


def test_expired_claim_and_late_worker_are_fenced(owner_db,scenario):
    party,request,row=scenario
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);old=repo.claim(row)
    expire(owner_db,scenario)
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);new=repo.claim(repo.read(row['operation_id']))
        assert new['claim_token']!=old['claim_token']
        with pytest.raises(V.ObservationError):repo.record(old,uuid.uuid4(),observation(request))
        repo.record(new,uuid.uuid4(),observation(request))


@pytest.mark.parametrize('seconds',[-360,60])
def test_stale_and_future_observations_do_not_persist(scenario,seconds):
    party,request,row=scenario;obs=observation(request)
    obs=replace(obs,provenance=replace(obs.provenance,observed_at=obs.provenance.observed_at+timedelta(seconds=seconds)))
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);claimed=repo.claim(row)
        with pytest.raises(V.ObservationError):repo.record(claimed,uuid.uuid4(),obs)
        assert repo.read(row['operation_id'])['last_observation_id'] is None


def test_conflicting_observations_are_retained_and_ambiguity_is_sticky(scenario):
    first,row=record(scenario)
    party,request,_=scenario
    second,conflict=record(scenario,value=observation(request,subscription=C.ProviderReference(request.binding.provider,'subscription_B',binding=request.binding)))
    assert first.unpack()['observation_id']!=second.unpack()['observation_id']
    assert conflict['state']=='reconciliation_required' and conflict['has_conflict']
    _,later=record(scenario)
    assert later['has_conflict'] and later['state']=='reconciliation_required'


@pytest.mark.parametrize('field',['customer','binding','terms','customer_operation'])
def test_wrong_scoped_or_frozen_lineage_is_rejected(scenario,field):
    party,request,row=scenario;doc=V.request_document(request)
    if field=='customer':doc['customer']='customer_other'
    elif field=='binding':doc['binding']['environment']='live'
    elif field=='terms':doc['terms_digest']='sha256:'+'b'*64
    else:doc['customer_operation_id']=str(uuid.uuid4())
    with closing(connection(party)) as conn,pytest.raises(psycopg2.Error):
        with conn.cursor() as cur:cur.execute('SELECT billing_observation_begin(%s,%s)',(str(uuid.uuid4()),Json(doc)))


def test_real_password_roles_rls_acl_membership_and_set_role(owner_db,scenario,parties):
    party,request,row=scenario
    with closing(connection(party)) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT session_user,current_user');assert cur.fetchone()==('ceopro_billing_observer','ceopro_billing_observer')
            for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_trial_issuer','ceopro_observation_owner'):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute('SET ROLE '+role)
                conn.rollback()
            for query in ('UPDATE billing_observation_operations SET version=99','DELETE FROM billing_verification_observations',
                          'CREATE TABLE public.observer_escape(id int)',"SELECT billing_setup_trial('growth',true)"):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute(query)
                conn.rollback()
    with closing(connection(parties[1])) as conn:
        repo=V.ObservationRepository(conn);assert repo.read(row['operation_id']) is None
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_observation_operations');assert cur.fetchone()==(0,)
    with owner_db.cursor() as cur:
        for table in ('billing_observation_operations','billing_observation_receipts','billing_verification_observations'):
            cur.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,));assert cur.fetchone()==(True,True)
        cur.execute("SELECT count(*) FROM pg_auth_members WHERE roleid IN ('ceopro_billing_observer'::regrole,'ceopro_observation_owner'::regrole) OR member IN ('ceopro_billing_observer'::regrole,'ceopro_observation_owner'::regrole)")
        assert cur.fetchone()==(0,)
        cur.execute("SELECT p.proowner::regrole::text,p.proconfig,has_function_privilege('ceopro_app',p.oid,'EXECUTE'),has_function_privilege('ceopro_billing_setup',p.oid,'EXECUTE'),has_function_privilege('ceopro_billing_webhook',p.oid,'EXECUTE') FROM pg_proc p WHERE p.proname LIKE 'billing_observation_%'")
        for owner,config,app,setup,webhook in cur.fetchall():
            assert owner=='ceopro_observation_owner' and config==['search_path=pg_catalog, public, pg_temp']
            assert not app and not setup and not webhook


def test_old_runtime_roles_cannot_forge_or_call_new_commands(owner_db,scenario):
    party,_,row=scenario
    for factory in (lambda:db.app_role_connection(*party),lambda:db.billing_setup_connection(*party),lambda:db.billing_webhook_connection('event_forged'),lambda:db.credit_accounting_connection(*party)):
        with closing(factory()) as conn:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                with conn.cursor() as cur:cur.execute('SELECT billing_observation_claim(%s,0,gen_random_uuid())',(row['operation_id'],))
            conn.rollback()
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                with conn.cursor() as cur:cur.execute('SELECT * FROM billing_verification_observations')


def test_atomic_record_rollback_and_immutable_evidence(owner_db,scenario):
    party,request,row=scenario
    with owner_db.cursor() as cur:
        cur.execute("CREATE FUNCTION b3_injected() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic record failure'; END $$")
        cur.execute('CREATE TRIGGER b3_injected BEFORE UPDATE ON billing_observation_operations FOR EACH ROW WHEN (NEW.last_observation_id IS NOT NULL) EXECUTE FUNCTION b3_injected()')
    try:
        with pytest.raises(V.ObservationError):record(scenario)
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s',(row['operation_id'],));assert cur.fetchone()==(0,)
    finally:
        with owner_db.cursor() as cur:
            cur.execute('DROP TRIGGER b3_injected ON billing_observation_operations');cur.execute('DROP FUNCTION b3_injected()')
    expire(owner_db,scenario);stored,_=record(scenario)
    with owner_db.cursor() as cur:
        cur.execute('BEGIN');cur.execute("SELECT set_config('app.current_tenant_id',%s,true),set_config('app.current_user_id',%s,true)",party);cur.execute('SET LOCAL ROLE ceopro_observation_owner')
        with pytest.raises(psycopg2.errors.InvalidParameterValue):cur.execute("UPDATE billing_verification_observations SET outcome='verified' WHERE observation_id=%s",(stored.unpack()['observation_id'],))
        cur.execute('ROLLBACK')


@pytest.mark.parametrize('difference',['provider','account','environment'])
def test_identical_opaque_ids_are_scoped_and_forged_record_context_is_rejected(owner_db,parties,difference):
    first,second=parties
    with closing(db.billing_setup_connection(*first)) as conn:
        from src.ai.billing import payment_bindings
        a=payment_bindings.selected(conn)
    b=replace(a,binding_id='binding_'+uuid.uuid4().hex,
        provider='hypothetical-mor' if difference=='provider' else a.provider,
        merchant_account_id='merchant_other' if difference=='account' else a.merchant_account_id,
        environment=C.GatewayEnvironment.LIVE if difference=='environment' else a.environment)
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,provenance) VALUES(%s,%s,%s,%s,'synthetic scoped fixture')",
            (b.binding_id,b.provider,b.environment.value,b.merchant_account_id))
        for party,binding in ((first,a),(second,b)):
            cur.execute("INSERT INTO billing_customer_references(tenant_id,binding_id,provider_customer_id) VALUES(%s,%s,'identical_customer')",(party[0],binding.binding_id))
    rows=[];requests=[]
    for party,binding in ((first,a),(second,b)):
        request=C.SubscriptionObservationRequest(party[0],binding,C.ProviderReference(binding.provider,'identical_customer',binding=binding),C.ProviderReference(binding.provider,'identical_subscription',binding=binding))
        with closing(connection(party)) as conn:
            repo=V.ObservationRepository(conn);row=repo.begin(uuid.uuid4(),request);rows.append(repo.claim(row));requests.append(request)
    assert requests[0].customer!=requests[1].customer
    # Mutate the caller's row, so the Python precheck alone would accept wrong binding.
    forged=dict(rows[0],request=V.request_document(requests[1]))
    value=C.ProviderVerificationObservation(requests[1],C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,requests[1].subscription,
        datetime.now(timezone.utc),'synthetic-adapter','synthetic-api'))
    with closing(connection(first)) as conn:
        with pytest.raises(V.ObservationError):V.ObservationRepository(conn).record(forged,uuid.uuid4(),value)
    # The original bound operation remains recoverable, without provider switching.
    for party,row,request in zip((first,second),rows,requests):
        value=C.ProviderVerificationObservation(request,C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,request.subscription,
            datetime.now(timezone.utc),'synthetic-adapter','synthetic-api'))
        with closing(connection(party)) as conn:
            stored=V.ObservationRepository(conn).record(row,uuid.uuid4(),value)
            assert stored.unpack()['binding_id']==request.binding.binding_id


def test_existing_customer_operation_lineage_and_disabled_binding_recovery(owner_db,customer_scenario):
    result=resolve_customer(customer_scenario)
    party,intent,_=customer_scenario
    r=reserve(party)
    with closing(db.billing_setup_connection(*party)) as conn:
        trial_checkouts.operation(conn,r['attempt_id'],'prepare',payload={'synthetic':True},replay_window_seconds=3600)
        trial_checkouts.operation(conn,r['attempt_id'],'submitted')
        trial_checkouts.operation(conn,r['attempt_id'],'session',session='checkout_'+r['attempt_id']);conn.commit()
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);request=V.trial_request(repo.context(r['attempt_id']))
        assert request.customer_operation_id==intent.operation_id and request.customer==result
        row=repo.begin(uuid.uuid4(),request)
    with owner_db.cursor() as cur:cur.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE binding_id=%s',(request.binding.binding_id,))
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);stored=repo.record(repo.claim(row),uuid.uuid4(),observation(request))
        assert stored.unpack()['binding_id']==request.binding.binding_id


def test_forged_json_and_missing_consent_cannot_activate_or_store_secret_shapes(scenario,owner_db):
    party,request,row=scenario
    before=fingerprint(owner_db)
    with closing(connection(party)) as conn:
        repo=V.ObservationRepository(conn);claimed=repo.claim(row);value=observation(request)
        document=V.evidence_document(value);document['recurring_authority']={'client_secret':'synthetic-private'}
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            with conn.cursor() as cur:cur.execute('SELECT billing_observation_record(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row['operation_id'],claimed['version'],claimed['claim_token'],str(uuid.uuid4()),'authoritative_lookup',None,
                 request.checkout.opaque_id,datetime.now(timezone.utc),'synthetic-adapter','synthetic-api','pending',Json(document),Json(row['request'])))
        conn.rollback()
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            with conn.cursor() as cur:cur.execute('SELECT billing_observation_record(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row['operation_id'],claimed['version'],claimed['claim_token'],str(uuid.uuid4()),'authoritative_lookup',None,
                 request.checkout.opaque_id,datetime.now(timezone.utc),'synthetic-adapter','synthetic-api','verified',Json(V.evidence_document(value)),Json(row['request'])))
        conn.rollback()
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with conn.cursor() as cur:cur.execute('SELECT billing_observation_evidence(%s)',(Json(document),))
        conn.rollback()
    assert fingerprint(owner_db)==before
