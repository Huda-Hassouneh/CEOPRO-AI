"""Disposable PostgreSQL retry authorization, concurrency and ACL proof only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json,threading,uuid
import psycopg2,pytest
from psycopg2.extras import Json
from src.ai.billing import recurring_consent as R
from src.ai.billing.subscription_journey import DispatchRepository
from . import test_subscription_journey_db as J
from .test_subscription_journey_db import parties,journey
from .test_recurring_consent_db import service,restricted_runtime
from .test_multi_gateway_lifecycle_db import SyntheticCustomerGateway


@pytest.fixture
def operator(owner_db):
    with owner_db.cursor() as q:
        q.execute("SELECT w.tenant_id,m.user_id FROM keel_platform_workspace w CROSS JOIN keel_platform_members m WHERE m.role_key='owner' AND m.status='active'");row=q.fetchone()
        if row:return tuple(map(str,row))
        tenant,user=str(uuid.uuid4()),str(uuid.uuid4())
        q.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'SYNTHETIC operator','US','USD')",(tenant,))
        q.execute("INSERT INTO users(user_id,email,password_hash,email_verified_at) VALUES(%s,%s,'SYNTHETIC nonlogin',now())",(user,user+'@example.test'))
        q.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",(tenant,user))
        q.execute('INSERT INTO keel_platform_workspace(tenant_id) VALUES(%s)',(tenant,))
        q.execute("INSERT INTO keel_platform_members(user_id,role_key,status) VALUES(%s,'owner','active')",(user,))
        return tenant,user


class FixturePaddleGateway:
    def __init__(self,binding,transport,**kw):self.binding=binding
    def prepare(self,row,customer,policy,urls):
        r=row['reservation']
        return dict(approved_terms=r['approved_terms'],customer=customer.opaque_id,
            idempotency_key='keel-trial-checkout-'+r['attempt_id'],transport=dict(customer_id=customer.opaque_id,
                items=[dict(price_id=r['provider_price_id'],quantity=1)],collection_mode='automatic',
                checkout=dict(url=urls[0]),custom_data=dict(keel_journey_operation=r['attempt_id'],tenant_id=r['tenant_id'])))


@pytest.fixture
def submitted(owner_db,parties,monkeypatch):
    key='paddle_retry_'+uuid.uuid4().hex
    with owner_db.cursor() as q:
        q.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'paddle','test',%s,true,'SYNTHETIC retry proof')",(key,key))
        q.execute("INSERT INTO billing_lifecycle_provider_approvals VALUES(%s,'SYNTHETIC, NOT merchant acceptance',clock_timestamp())",(key,))
        q.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) SELECT %s,price_id,'pri_'||replace(price_id::text,'-',''),'SYNTHETIC' FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL",(key,))
    monkeypatch.setattr(J,'StripeJourneyGateway',FixturePaddleGateway)
    monkeypatch.setattr(J,'Gateway',SyntheticCustomerGateway)
    generator=J.journey.__wrapped__(owner_db,parties);s=next(generator)
    try:
        p,d=J.prepared(s);s.retry_presentation=p;s.retry_dispatch=d
        s.retry_args=dict(acceptance=d['acceptance_id'],customer=d['customer_operation_id'])
        assert s.flow.dispatches.command(s.operation,'elect',**s.retry_args)['elected']
        s.retry_dispatch=s.flow.dispatches.command(s.operation,'read')
        yield s
    finally:generator.close()


def evidence(s):
    d=s.retry_dispatch
    return dict(binding_id=d['binding_id'],merchant_account_id=s.binding.merchant_account_id,customer_id=d['provider_customer_id'],
        request=d['request']['transport'],namespace=dict(id=s.binding.merchant_account_id),
        rejection=dict(status=400,error=dict(type='request_error',code='transaction_checkout_url_domain_is_not_approved'),request_id='SYNTHETIC rejection',response_sha256='sha256:'+'a'*64),
        recovery=dict(status=200,data=[],has_more=False,customer_id=d['provider_customer_id'],request_id='SYNTHETIC recovery',observed_at=datetime.now(timezone.utc).isoformat()))


def authorize(conn,operator,s,value=None):
    with conn.cursor() as q:
        q.execute("SELECT set_config('app.current_tenant_id',%s,false),set_config('app.current_user_id',%s,false)",operator)
        q.execute('SELECT billing_authorize_checkout_retry(%s,%s,%s)',(str(s.operation),Json(evidence(s) if value is None else value),'SYNTHETIC explicit authorization'))
        return q.fetchone()[0]


def test_single_retry_preserves_original_history_and_never_reopens(submitted,owner_db,operator):
    s=submitted;before=s.retry_dispatch
    row=authorize(owner_db,operator,s)
    assert row['original_submitted_at']==before['submitted_at'] and row['request']==before['request']
    assert s.flow.dispatches.command(s.operation,'elect',**s.retry_args)['elected']
    assert not s.flow.dispatches.command(s.operation,'elect',**s.retry_args)['elected']
    after=s.flow.dispatches.command(s.operation,'read')
    assert after['submitted_at']==before['submitted_at'] and after['request']==before['request']
    with pytest.raises(psycopg2.errors.UniqueViolation):authorize(owner_db,operator,s)
    with owner_db.cursor() as q:
        q.execute("UPDATE billing_checkout_retry_authorizations SET result='{"+'"state":"unknown"'+"}'::jsonb WHERE attempt_id=%s",(str(s.operation),))
        for statement in ("UPDATE billing_checkout_retry_authorizations SET result='{}'::jsonb WHERE attempt_id=%s",'DELETE FROM billing_checkout_retry_authorizations WHERE attempt_id=%s'):
            with pytest.raises(psycopg2.errors.InvalidParameterValue):q.execute(statement,(str(s.operation),))
    assert not s.flow.dispatches.command(s.operation,'elect',**s.retry_args)['elected']


@pytest.mark.parametrize('problem',['5xx','timeout_code','customer','binding','merchant','request','nonempty','partial','stale','missing_time','missing_digest'])
def test_uncertain_conflicting_or_stale_evidence_is_denied(submitted,owner_db,operator,problem):
    s=submitted;v=deepcopy(evidence(s))
    if problem=='5xx':v['rejection']['status']=503
    elif problem=='timeout_code':v['rejection']['error']['code']='timeout'
    elif problem in ('customer','binding','merchant'):v[{'customer':'customer_id','binding':'binding_id','merchant':'merchant_account_id'}[problem]]='other'
    elif problem=='request':v['request']['items'][0]['quantity']=2
    elif problem=='nonempty':v['recovery']['data']=[{'id':'txn_exists'}]
    elif problem=='partial':v['recovery']['has_more']=True
    elif problem=='stale':v['recovery']['observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    elif problem=='missing_time':del v['recovery']['observed_at']
    elif problem=='missing_digest':del v['rejection']['response_sha256']
    with pytest.raises(psycopg2.errors.InvalidParameterValue):authorize(owner_db,operator,s,v)
    assert not s.flow.dispatches.command(s.operation,'elect',**s.retry_args)['elected']


def test_concurrent_retry_election_has_one_winner(submitted,owner_db,operator):
    s=submitted;authorize(owner_db,operator,s);gate=threading.Barrier(2)
    def elect(_):
        with closing(service(s.party)) as conn:
            gate.wait()
            try:return DispatchRepository(conn).command(s.operation,'elect',**s.retry_args)['elected']
            except R.ConsentError as error:
                assert str(error)=='consent_55P03';return False
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(elect,range(2)))
    assert sum(result)==1


def test_withdrawal_fences_authorized_retry(submitted,owner_db,operator):
    s=submitted;authorize(owner_db,operator,s)
    s.collection.withdraw(s.operation,uuid.UUID(s.retry_presentation['presentation_id']))
    with pytest.raises(R.ConsentError,match='22023'):s.flow.dispatches.command(s.operation,'elect',**s.retry_args)
    with owner_db.cursor() as q:
        q.execute('SELECT retry_submitted_at FROM billing_checkout_retry_authorizations WHERE attempt_id=%s',(str(s.operation),));assert q.fetchone()==(None,)


def test_runtime_cannot_forge_retry_authority(submitted,owner_db,operator):
    s=submitted
    with closing(service(s.party)) as conn:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with conn.cursor() as q:q.execute('SELECT billing_authorize_checkout_retry(%s,%s,%s)',(str(s.operation),Json(evidence(s)),'forged'))
        conn.rollback()
    with owner_db.cursor() as q:
        q.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_checkout_retry_authorizations'::regclass");assert q.fetchone()==(True,True)
        for role in ('ceopro_app','ceopro_billing_setup','ceopro_consent_service','ceopro_trial_attestor','ceopro_trial_confirmer'):
            q.execute("SELECT has_table_privilege(%s,'billing_checkout_retry_authorizations','INSERT'),has_function_privilege(%s,'billing_authorize_checkout_retry(uuid,jsonb,text)','EXECUTE')",(role,role));assert q.fetchone()==(False,False)


def test_revoked_billing_membership_cannot_consume_retry(submitted,owner_db,operator):
    s=submitted;authorize(owner_db,operator,s)
    with owner_db.cursor() as q:q.execute('UPDATE tenant_users SET removed_at=clock_timestamp() WHERE tenant_id=%s AND user_id=%s',s.party)
    try:
        with pytest.raises(R.ConsentError,match='42501'):s.flow.dispatches.command(s.operation,'elect',**s.retry_args)
    finally:
        with owner_db.cursor() as q:q.execute('UPDATE tenant_users SET removed_at=NULL WHERE tenant_id=%s AND user_id=%s',s.party)


def test_demoted_platform_owner_cannot_authorize_retry(submitted,owner_db,operator):
    with owner_db.cursor() as q:q.execute("UPDATE keel_platform_members SET role_key='admin' WHERE user_id=%s",(operator[1],))
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):authorize(owner_db,operator,submitted)
    finally:
        with owner_db.cursor() as q:q.execute("UPDATE keel_platform_members SET role_key='owner' WHERE user_id=%s",(operator[1],))


def test_stripe_dispatch_cannot_enter_paddle_retry(journey,owner_db,operator):
    s=journey;_,d=J.prepared(s);s.retry_dispatch=s.flow.dispatches.command(s.operation,'elect',acceptance=d['acceptance_id'],customer=d['customer_operation_id'])
    with pytest.raises(psycopg2.errors.InvalidParameterValue):authorize(owner_db,operator,s)
