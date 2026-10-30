"""Local clock is optional; production cannot reach its out-of-image adapter.
Stripe network doubled; native HTTP, restricted passwords, RLS and accounting real.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import time
import uuid

import pytest

from src.ai import db
from src.ai.billing import stripe_api, test_clock, service, store, credits, admin
from src.ai.core import usage
from src.ai.core.security import create_access_token
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401
from .test_database import live_subscription

REAL_CLIENT = stripe_api._client
REAL_STRIPE = stripe_api.stripe


@pytest.fixture
def sdk(monkeypatch):
    calls=[]; customers={}; sessions={}
    state={'id':'clock_offlineFixture','livemode':False,'status':'ready','frozen_time':int(time.time())}
    mode={'livemode':False}
    def balance():calls.append(('balance',));return deepcopy(mode)
    def clock(cid):calls.append(('clock',cid));return deepcopy(state)
    def create(**params):
        calls.append(('create',deepcopy(params)))
        cid='cus_offline_'+params['metadata']['tenant_id']
        customers.setdefault(cid,dict(id=cid,livemode=False,metadata=params['metadata'],test_clock=params.get('test_clock')))
        return deepcopy(customers[cid])
    def retrieve(cid):calls.append(('customer',cid));return deepcopy(customers[cid])
    def session(params=None,**kw):
        data=params or kw;key=data.get('idempotency_key','one')
        sessions.setdefault(key,{'id':'cs_offline_'+uuid.uuid4().hex,'url':'https://checkout.stripe.test/offline','status':'open'})
        return deepcopy(sessions[key])
    client=SimpleNamespace(Webhook=REAL_STRIPE.Webhook, InvalidRequestError=REAL_STRIPE.InvalidRequestError, Balance=SimpleNamespace(retrieve=balance),
                           test_helpers=SimpleNamespace(TestClock=SimpleNamespace(retrieve=clock)),
                           Customer=SimpleNamespace(create=create,retrieve=retrieve),
                           checkout=SimpleNamespace(Session=SimpleNamespace(create=lambda **kw:session(**kw),retrieve=lambda sid:next(deepcopy(v) for v in sessions.values() if v['id']==sid))))
    monkeypatch.setattr(stripe_api,'stripe',client)
    monkeypatch.setattr(stripe_api,'_client',REAL_CLIENT)
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_offline')
    for key in ('STRIPE_TEST_CLOCK_ENABLED','STRIPE_TEST_CLOCK_ID','KEEL_LOCAL_TEST_CLOCKS','ENVIRONMENT','APP_ENV','RENDER','KUBERNETES_SERVICE_HOST'):
        monkeypatch.delenv(key,raising=False)
    return SimpleNamespace(client=client,calls=calls,customers=customers,clock=state,mode=mode)


def enable(monkeypatch):
    for key,value in {'STRIPE_TEST_CLOCK_ENABLED':'true','STRIPE_TEST_CLOCK_ID':'clock_offlineFixture',
                      'KEEL_DEV_ISOLATED':'1','KEEL_LOCAL_TEST_CLOCKS':'1','SENTRY_ENVIRONMENT':'development',
                      'DATABASE_URL':'postgresql://ceopro_app:fixture@127.0.0.1/keel_billing_test_fixture'}.items():
        monkeypatch.setenv(key,value)


@pytest.mark.parametrize('flag',[None,'false'])
@pytest.mark.parametrize('clock_id',[None,'clock_unused'])
def test_disabled_customer_request_is_exactly_unchanged(sdk,monkeypatch,flag,clock_id):
    if flag is not None:monkeypatch.setenv('STRIPE_TEST_CLOCK_ENABLED',flag)
    if clock_id:monkeypatch.setenv('STRIPE_TEST_CLOCK_ID',clock_id)
    result=stripe_api.create_customer('synthetic@example.test','Synthetic','tenant','same-key')
    assert result['test_clock'] is None
    assert sdk.calls==[('create',{'email':'synthetic@example.test','name':'Synthetic','metadata':{'tenant_id':'tenant'},'idempotency_key':'same-key'})]
    assert stripe_api.customer_clock_time(result['id'],'tenant') is None
    assert len(sdk.calls)==1


@pytest.mark.parametrize('key,value',[
    ('STRIPE_TEST_CLOCK_ID',''),('STRIPE_TEST_CLOCK_ID','not-a-clock'),('STRIPE_SECRET_KEY','sk_live_invalid'),
    ('KEEL_DEV_ISOLATED','0'),('KEEL_LOCAL_TEST_CLOCKS','0'),('SENTRY_ENVIRONMENT','production'),
    ('APP_ENV','production'),('ENVIRONMENT','staging'),('RENDER','true'),('DATABASE_URL','postgresql://app@remote.example/db')])
def test_misconfiguration_denied_before_provider_calls(sdk,monkeypatch,key,value):
    enable(monkeypatch);monkeypatch.setenv(key,value)
    with pytest.raises(test_clock.TestClockError):stripe_api.create_customer('a@example.test','A','tenant','key')
    assert sdk.calls==[]


def test_production_image_has_no_optional_adapter(sdk,monkeypatch):
    enable(monkeypatch)
    monkeypatch.setattr(test_clock.Path,'is_file',lambda _:False)
    with pytest.raises(test_clock.TestClockError):stripe_api.create_customer('a@example.test','A','tenant','key')
    assert sdk.calls==[]
    root=Path(__file__).resolve().parents[2]
    docker=(root/'Dockerfile.ai').read_text()
    assert 'COPY' in docker and 'tools/dev' not in docker
    assert 'dockerContext: ./backend' in (root.parent/'render.yaml').read_text()


@pytest.mark.parametrize('condition',['live_balance','live_clock','advancing','missing','future_clock','wrong_id'])
def test_bad_provider_clock_never_falls_back_to_normal_customer(sdk,monkeypatch,condition):
    enable(monkeypatch)
    if condition=='live_balance':sdk.mode['livemode']=True
    elif condition=='live_clock':sdk.clock['livemode']=True
    elif condition=='advancing':sdk.clock['status']='advancing'
    elif condition=='future_clock':sdk.clock['frozen_time']+=7200
    elif condition=='wrong_id':sdk.clock['id']='clock_other'
    else:monkeypatch.setattr(sdk.client.test_helpers.TestClock,'retrieve',lambda _:(_ for _ in ()).throw(ValueError('not found')))
    with pytest.raises(test_clock.TestClockError):stripe_api.create_customer('a@example.test','A','tenant','key')
    assert not any(c[0]=='create' for c in sdk.calls)


def test_new_test_customer_associated_idempotently_and_disabled_returns_to_normal(sdk,monkeypatch):
    enable(monkeypatch)
    one=stripe_api.create_customer('a@example.test','A','tenant','stable')
    two=stripe_api.create_customer('a@example.test','A','tenant','stable')
    assert one['id']==two['id'] and one['test_clock']=='clock_offlineFixture'
    assert len(sdk.customers)==1
    monkeypatch.setenv('STRIPE_TEST_CLOCK_ENABLED','false')
    before=len(sdk.calls)
    ordinary=stripe_api.create_customer('b@example.test','B','ordinary','ordinary-stable')
    assert ordinary['test_clock'] is None
    assert [c[0] for c in sdk.calls[before:]]==['create']


@pytest.mark.parametrize('attached',[None,'clock_other'])
def test_existing_customer_is_never_reassigned(sdk,monkeypatch,attached):
    enable(monkeypatch)
    sdk.customers['cus_existing']={'id':'cus_existing','livemode':False,'metadata':{'tenant_id':'tenant'},'test_clock':attached}
    with pytest.raises(test_clock.TestClockError):stripe_api.customer_clock_time('cus_existing','tenant',require_clock=True)
    assert sdk.customers['cus_existing']['test_clock']==attached
    assert not any(c[0]=='create' for c in sdk.calls)


def test_unrelated_customer_metadata_is_rejected(sdk,monkeypatch):
    enable(monkeypatch)
    sdk.customers['cus_other']={'id':'cus_other','livemode':False,'metadata':{'tenant_id':'other'},'test_clock':'clock_offlineFixture'}
    with pytest.raises(test_clock.TestClockError):stripe_api.customer_clock_time('cus_other','tenant')


@pytest.fixture
def clock_runtime(sdk,monkeypatch,restricted_runtime):
    from os import environ
    scoped=environ['DATABASE_URL']
    enable(monkeypatch);monkeypatch.setenv('DATABASE_URL',scoped)
    yield sdk


def test_native_checkout_mapping_reuse_conflict_and_disable(client,clock_runtime,tenant,test_price,owner_db,monkeypatch):
    sdk=clock_runtime;tid,uid=tenant;plan,_=test_price
    sdk.clock['frozen_time']-=8*3600  # Existing ready clock with a past origin.
    headers={'Authorization':'Bearer '+create_access_token(tid,uid,email_verified=True)[0]}
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:15173')
    assert client.post('/billing/trial',json={'plan_key':'growth'},headers=headers).status_code==200
    response=client.post('/billing/checkout',json={'plan_key':plan,'period_code':'monthly'},headers=headers)
    assert response.status_code==200,response.json()
    again=client.post('/billing/checkout',json={'plan_key':plan,'period_code':'monthly'},headers=headers)
    assert again.status_code==200 and again.json()==response.json()
    assert sum(c[0]=='create' for c in sdk.calls)==1
    cid=store.customer_id(owner_db,tid)
    assert sdk.customers[cid]['test_clock']=='clock_offlineFixture'
    # The original signup trial stays absolute UTC; no trial is reissued or extended.
    trial=store.trial(owner_db,tid)
    assert int(trial['ends_at'].timestamp())>sdk.clock['frozen_time']
    with closing(db.app_role_connection(str(uuid.uuid4()),uid)) as other:assert store.customer_id(other,tid) is None
    monkeypatch.setenv('STRIPE_TEST_CLOCK_ID','clock_other')
    assert client.post('/billing/checkout',json={'plan_key':plan,'period_code':'monthly'},headers=headers).status_code==503
    assert store.customer_id(owner_db,tid)==cid
    monkeypatch.setenv('STRIPE_TEST_CLOCK_ENABLED','false')
    before=len(sdk.calls)
    assert client.post('/billing/checkout',json={'plan_key':plan,'period_code':'monthly'},headers=headers).status_code==200
    assert not any(c[0] in ('clock','balance','customer') for c in sdk.calls[before:])


@pytest.mark.parametrize('kind',['data','ai'])
def test_clock_time_is_tenant_scoped_and_renewal_credits_are_idempotent(clock_runtime,tenant,test_price,owner_db,send,monkeypatch,kind):
    sdk=clock_runtime;tid,uid=tenant;_,price=test_price
    # Private fixture needs explicit synthetic budget terms, never public prices.
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO usage_plan_limits(plan_key,feature_code,limit_value,trial_limit_value) VALUES(%s,'data_credits',100,10),(%s,'ai_credits',100,10)",(test_price[0],test_price[0]))
    live=live_subscription(tid,price,status='trialing');live['trial_end']=int(time.time())+14*86400;live['items']['data'][0]['current_period_end']=live['trial_end']
    sdk.customers[live['customer']]={'id':live['customer'],'livemode':False,'metadata':{'tenant_id':tid},'test_clock':sdk.clock['id']}
    monkeypatch.setattr(stripe_api,'retrieve_subscription',lambda _:deepcopy(live))
    assert send('customer.subscription.created',{'id':live['id']}).status_code==200
    with closing(db.app_role_connection(tid,uid)) as conn:assert usage.get_plan(conn,tid)['status']=='trialing'
    sdk.clock['frozen_time']=live['trial_end']
    # No webhook is enough to expire only this trial, using the provider clock.
    with closing(db.app_role_connection(tid,uid)) as conn:assert usage.get_plan(conn,tid)['status']=='expired'
    live['status']='active';live['items']['data'][0].update(current_period_start=live['trial_end'],current_period_end=live['trial_end']+30*86400)
    invoice={'id':'in_clock_'+uuid.uuid4().hex,'customer':live['customer'],'subscription':live['id'],'status':'paid','amount_paid':100,'currency':'usd','lines':{'data':[{'period':{'start':live['trial_end'],'end':live['trial_end']+30*86400}}]}}
    live['latest_invoice']=invoice['id'];monkeypatch.setattr(stripe_api,'retrieve_invoice',lambda _:deepcopy(invoice))
    event='evt_clock_'+uuid.uuid4().hex
    assert send('invoice.paid',invoice,event).status_code==200
    vendor='clock_fixture_'+uuid.uuid4().hex
    admin.set_price(owner_db,budget_kind=kind,provider=vendor,operation='op',unit='request',unit_cost_usd=Decimal('0.01'),source='synthetic isolated clock fixture',verified_on=date.today(),approved_by='test',reason='clock period',safety_margin=Decimal('0'))
    try:
        with credits.metering(tid,'restricted_test',actor_user_id=uid):
            receipt=credits.reserve(kind,vendor,'op',{'request':1},idempotency_key='clock-first')
            credits.settle(receipt,{'request':1})
        assert receipt.period_start==datetime.fromtimestamp(live['trial_end'],timezone.utc).date()
        assert receipt.period_start>datetime.now(timezone.utc).date()
        assert send('invoice.paid',invoice,event).json()['duplicate'] is True
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*),sum(consumed_credits) FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind=%s',(tid,kind));rows,spent=cur.fetchone();assert rows==1 and spent>0
        old_spent=spent
        # Advance a full simulated billing period without touching wall time.
        sdk.clock['frozen_time']+=30*86400
        item=live['items']['data'][0]
        item['current_period_start']+=30*86400;item['current_period_end']+=30*86400
        invoice['id']='in_clock_renewal_'+uuid.uuid4().hex
        invoice['lines']['data'][0]['period']={'start':item['current_period_start'],'end':item['current_period_end']}
        live['latest_invoice']=invoice['id'];renewal='evt_clock_renewal_'+uuid.uuid4().hex
        assert send('invoice.paid',invoice,renewal).status_code==200
        with credits.metering(tid,'restricted_test',actor_user_id=uid):
            renewed=credits.reserve(kind,vendor,'op',{'request':1},idempotency_key='clock-renewal')
            credits.settle(renewed,{'request':1})
        assert renewed.period_start==datetime.fromtimestamp(item['current_period_start'],timezone.utc).date()
        assert renewed.period_start>receipt.period_start
        assert send('invoice.paid',invoice,renewal).json()['duplicate'] is True
        with owner_db.cursor() as cur:
            cur.execute('SELECT count(*),sum(consumed_credits) FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind=%s',(tid,kind))
            rows,spent=cur.fetchone();assert rows==2 and spent==old_spent*2
        # Another tenant without a Stripe mapping remains on actual UTC, even
        # when the global local-testing switch is on and this clock is advanced.
        other=str(uuid.uuid4())
        with closing(db.app_role_connection(other,uid)) as conn:
            p=usage.get_plan(conn,other);assert p['period_start']<=datetime.now(timezone.utc).date()<=p['period_end']
    finally:
        with owner_db.cursor() as cur:cur.execute('DELETE FROM provider_cost_schedules WHERE provider=%s',(vendor,))


def test_disabled_production_customer_creation_does_not_load_dev_adapter(sdk,monkeypatch):
    monkeypatch.setenv('SENTRY_ENVIRONMENT','production')
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_live_invalid_fixture')
    monkeypatch.setenv('STRIPE_TEST_CLOCK_ENABLED','false')
    monkeypatch.setenv('STRIPE_TEST_CLOCK_ID','clock_ignored')
    monkeypatch.setattr(test_clock.Path,'is_file',lambda _:False)
    stripe_api.create_customer('a@example.test','A','tenant','same-key')
    assert [c[0] for c in sdk.calls]==['create']
    assert 'test_clock' not in sdk.calls[0][1]


def test_enabled_trial_schedule_preserves_cutoff_and_simulated_expiry(client,clock_runtime,tenant,owner_db,send,monkeypatch):
    from .test_trial_plan_transitions import TrialProvider
    sdk=clock_runtime;tid,uid=tenant
    # Read real comparable public rights. Only provider HTTP and price-link
    # responses are doubled; public database price mappings remain untouched.
    provider=TrialProvider(tid,'price_offline_current')
    sdk.customers[provider.live['customer']]={'id':provider.live['customer'],'livemode':False,'metadata':{'tenant_id':tid},'test_clock':sdk.clock['id']}
    provider.install(monkeypatch)
    monkeypatch.setattr(store,'resolve_price',lambda *a:('growth','monthly'))
    assert send('customer.subscription.created',{'id':provider.live['id']}).status_code==200
    original_price=store.current_price
    def configured(conn,key,term):
        value=original_price(conn,key,term)
        return {**value,'stripe_price_id':'price_offline_'+key}
    monkeypatch.setattr(store,'current_price',configured)
    headers={'Authorization':'Bearer '+create_access_token(tid,uid,email_verified=True)[0]}
    before=store.current_subscription(owner_db,tid)
    response=client.post('/billing/change-plan',headers=headers,json={'plan_key':'starter','period_code':'monthly'})
    assert response.status_code==200,response.json()
    assert provider.updates[0]['phases'][0]['trial_end']==provider.original['trial_end']
    after=store.current_subscription(owner_db,tid)
    for field in ('status','trial_end','current_period_start','current_period_end'):assert before[field]==after[field]
    assert client.delete('/billing/scheduled-change',headers=headers).status_code==200
    assert client.post('/billing/change-plan',headers=headers,json={'plan_key':'enterprise','period_code':'monthly'}).status_code==200
    assert provider.live['status']=='trialing' and provider.live['trial_end']==provider.original['trial_end']
    sdk.clock['frozen_time']=provider.original['trial_end']+1
    response=client.post('/billing/change-plan',headers=headers,json={'plan_key':'starter','period_code':'monthly'})
    assert response.status_code==409,response.json()
    with closing(db.app_role_connection(tid,uid)) as conn:assert usage.get_plan(conn,tid)['status']=='expired'
