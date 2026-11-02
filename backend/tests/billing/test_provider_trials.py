"""Native roles/transactions + real signed decoding, offline provider transport.

No existing customer or external provider objects are touched by this suite.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from copy import deepcopy
import ast
from pathlib import Path
import time
import uuid

import pytest

from src.ai import db
from src.ai.billing import service,store,stripe_api
from src.ai.billing import checkout_attempts, trial_checkouts
from src.ai.billing.payment_contracts import PaymentProviderError, ProviderOperationOutcome
from src.ai.core import usage
from src.ai.core.security import create_access_token
from .test_reconciliation_roles import restricted_runtime, send  # Explicit native password-role fixtures.


@pytest.fixture
def provider(monkeypatch,owner_db,restricted_runtime):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_offline')
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:15173')
    sessions={}; requests=[]; subscriptions={}
    with owner_db.cursor() as cur:
        cur.execute("SELECT price_id,stripe_price_id FROM billing_plan_prices WHERE plan_key IN ('starter','growth','enterprise') AND retired_at IS NULL")
        original=cur.fetchall()
        cur.execute("UPDATE billing_plan_prices SET stripe_price_id='price_trial_fixture_'||price_id::text WHERE plan_key IN ('starter','growth','enterprise') AND retired_at IS NULL")
    monkeypatch.setattr(stripe_api,'create_customer',lambda *a,**kw:{'id':'cus_trial_'+uuid.uuid4().hex})
    monkeypatch.setattr(stripe_api,'customer_clock_time',lambda *a,**kw:None)
    monkeypatch.setattr(stripe_api,'retrieve_subscription',lambda key:deepcopy(subscriptions[key]))
    def checkout(params,idempotency_key):
        requests.append(deepcopy(params))
        sid='cs_trial_'+uuid.uuid4().hex
        sessions[sid]={'id':sid,'url':'https://checkout.stripe.test/'+sid,'status':'open','mode':'subscription',
            'customer':params['customer'],'client_reference_id':params['client_reference_id'],
            'metadata':params['metadata'],'payment_status':'unpaid'}
        return deepcopy(sessions[sid])
    monkeypatch.setattr(stripe_api,'create_checkout_session',checkout)
    monkeypatch.setattr(stripe_api,'retrieve_checkout_session',lambda sid:deepcopy(sessions[sid]))
    def expire(sid):
        sessions[sid]['status']='expired';return deepcopy(sessions[sid])
    monkeypatch.setattr(stripe_api,'expire_checkout_session',expire)
    def confirm(session_id,*,ready=True):
        params=requests[-1]; data=params['subscription_data']; now=int(time.time())
        end=data.get('trial_end') or now+data.get('trial_period_days',0)*86400
        sid='sub_trial_'+uuid.uuid4().hex
        sub={'id':sid,'customer':params['customer'],'metadata':data['metadata'],'status':'trialing' if end>now else 'active',
            'trial_start':now if end>now else None,'trial_end':end if end>now else None,
            'default_payment_method':'pm_offline_fixture' if ready else None,'cancel_at_period_end':False,
            'items':{'data':[{'id':'si_offline','price':{'id':params['line_items'][0]['price']},'quantity':1,
                'current_period_start':now,'current_period_end':end if end>now else now+30*86400}]}}
        subscriptions[sid]=sub
        sessions[session_id].update(status='complete',subscription=sid,payment_status='no_payment_required' if end>now else 'paid')
        return sub
    yield dict(sessions=sessions,requests=requests,subscriptions=subscriptions,confirm=confirm)
    with owner_db.cursor() as cur:
        for price_id,reference in original:
            cur.execute('UPDATE billing_plan_prices SET stripe_price_id=%s WHERE price_id=%s',(reference,price_id))


def headers(tenant):
    return {'Authorization':'Bearer '+create_access_token(*tenant,email_verified=True)[0]}


def no_access_rows(owner_db,tenant):
    with owner_db.cursor() as cur:
        for table in ('billing_trials','billing_subscriptions','tenant_plan_assignments','tenant_credit_balances'):
            cur.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tenant[0],))
            assert cur.fetchone()[0]==0,table


def test_continue_and_repeated_trial_requests_resume_authorized_trial(client,tenant,owner_db,provider):
    body={'plan_key':'growth','period_code':'monthly'}
    first=client.post('/billing/trial',headers=headers(tenant),json=body)
    assert first.status_code==200,first.text
    for path in ['/billing/trial','/billing/checkout','/billing/trial','/billing/checkout']:
        result=client.post(path,headers=headers(tenant),json=body)
        assert result.status_code==200,result.text
        assert result.json()==first.json()
    assert len(provider['requests'])==1
    no_access_rows(owner_db,tenant)


def test_unsubmitted_stale_reservation_recovers_different_selection(client,tenant,owner_db,provider):
    # A crashed request after eligibility reservation but before freeze/submit.
    with closing(db.billing_setup_connection(*tenant)) as conn:
        with checkout_attempts.tenant_lock(conn,tenant[0]):
            old=checkout_attempts.reserve(conn,tenant[0],'old-pro-selection','enterprise','monthly')
            trial_checkouts.reserve(conn,*tenant,old,'enterprise','monthly')
    result=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert result.status_code==200,result.text
    assert len(provider['requests'])==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE attempt_id=%s',(old['attempt_id'],))
        assert cur.fetchone()[0]=='released'
        cur.execute("SELECT plan_key FROM billing_trial_checkouts WHERE tenant_id=%s AND state='pending'",(tenant[0],))
        assert cur.fetchall()==[('growth',)]
    no_access_rows(owner_db,tenant)


def test_customer_setup_failure_releases_only_unsubmitted_checkout(client,tenant,owner_db,provider,monkeypatch):
    def unavailable(*args,**kwargs):raise PaymentProviderError(ProviderOperationOutcome.OUTCOME_UNKNOWN)
    monkeypatch.setattr(stripe_api,'create_customer',unavailable)
    result=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    assert result.status_code==502,result.text
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchall()==[('released',)]
        cur.execute('SELECT state FROM billing_checkout_attempts WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchall()==[('expired',)]
    assert not provider['requests']
    no_access_rows(owner_db,tenant)


@pytest.mark.parametrize('terminal',['expired','missing'])
def test_terminal_provider_checkout_recovers_without_webhook(client,tenant,owner_db,provider,monkeypatch,terminal):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    sid=first.json()['session_id']
    if terminal=='expired':provider['sessions'][sid]['status']='expired'
    else:
        original=service.StripeGateway.get_checkout
        def read(gateway,reference):
            if reference.opaque_id==sid:raise PaymentProviderError(ProviderOperationOutcome.NOT_FOUND)
            return original(gateway,reference)
        monkeypatch.setattr(service.StripeGateway,'get_checkout',read)
    result=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert result.status_code==200,result.text
    assert result.json()['session_id']!=sid
    with owner_db.cursor() as cur:
        cur.execute('SELECT state,count(*) FROM billing_trial_checkouts WHERE tenant_id=%s GROUP BY state',(tenant[0],))
        assert dict(cur.fetchall())=={'released':1,'pending':1}
    no_access_rows(owner_db,tenant)


def test_open_paid_checkout_cannot_silently_replace_requested_trial(client,tenant,owner_db,provider):
    first=client.post('/billing/checkout',headers=headers(tenant),json={'plan_key':'growth'})
    assert first.status_code==200,first.text
    conflict=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert conflict.status_code==409 and conflict.json()['detail']['reason']=='checkout_pending'
    assert len(provider['requests'])==1
    no_access_rows(owner_db,tenant)


@pytest.mark.parametrize('state',['complete','unknown'])
def test_nonterminal_or_completed_checkout_cannot_be_released(client,tenant,owner_db,provider,state):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    provider['sessions'][first.json()['session_id']]['status']=state
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==409
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'}).status_code==409
    assert len(provider['requests'])==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchone()[0]=='pending'
    no_access_rows(owner_db,tenant)


def test_explicit_close_then_retry_preserves_eligibility(client,tenant,owner_db,provider):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==200
    assert provider['sessions'][first.json()['session_id']]['status']=='expired'
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'}).status_code==200
    no_access_rows(owner_db,tenant)


def test_concurrent_identical_trial_checkouts_resume_one_session(client,tenant,owner_db,provider):
    def start(_):return client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(start,range(4)))
    assert [r.status_code for r in results]==[200]*4
    assert len({r.json()['session_id'] for r in results})==1
    assert len(provider['requests'])==1
    no_access_rows(owner_db,tenant)


def test_unknown_submit_replays_frozen_request_instead_of_releasing(client,tenant,owner_db,provider,monkeypatch):
    submit=stripe_api.create_checkout_session
    saved={};keys=[]
    def uncertain(params,idempotency_key):
        keys.append(idempotency_key)
        if not saved:
            saved.update(submit(params,idempotency_key))
            raise PaymentProviderError(ProviderOperationOutcome.OUTCOME_UNKNOWN)
        return deepcopy(saved)
    monkeypatch.setattr(stripe_api,'create_checkout_session',uncertain)
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert first.status_code==502,first.text
    # Neither an incompatible request nor cancellation may free an uncertain write.
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'}).status_code==409
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==409
    retry=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    assert retry.status_code==200,retry.text
    assert retry.json()['session_id']==saved['id'] and len(set(keys))==1
    assert len(provider['requests'])==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT state,count(*) FROM billing_trial_checkouts WHERE tenant_id=%s GROUP BY state',(tenant[0],))
        assert cur.fetchall()==[('pending',1)]
    no_access_rows(owner_db,tenant)


def test_provider_read_failure_does_not_release_pending(client,tenant,owner_db,provider,monkeypatch):
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'}).status_code==200
    def unavailable(*args):raise PaymentProviderError(ProviderOperationOutcome.UNAVAILABLE)
    monkeypatch.setattr(service.StripeGateway,'get_checkout',unavailable)
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'}).status_code==502
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==502
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchone()[0]=='pending'
    no_access_rows(owner_db,tenant)


def test_expiry_racing_completion_does_not_release_pending(client,tenant,owner_db,provider,monkeypatch):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    sid=first.json()['session_id']
    def completed(reference):
        provider['sessions'][reference]['status']='complete'
        return deepcopy(provider['sessions'][reference])
    monkeypatch.setattr(stripe_api,'expire_checkout_session',completed)
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==409
    assert provider['sessions'][sid]['status']=='complete'
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],))
        assert cur.fetchone()[0]=='pending'
    no_access_rows(owner_db,tenant)


def test_webhook_expiry_then_stale_request_expiry_is_idempotent(client,tenant,owner_db,provider,send):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'})
    with closing(db.billing_setup_connection(*tenant)) as conn:
        attempt=checkout_attempts.active(conn,tenant[0])
        session=provider['sessions'][first.json()['session_id']];session['status']='expired'
        assert send('checkout.session.expired',session).status_code==200
        # The verified expiry raced a caller that already read the old attempt.
        checkout_attempts.expire(conn,attempt)
        checkout_attempts.expire(conn,attempt)
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'growth'}).status_code==200
    no_access_rows(owner_db,tenant)


@pytest.mark.parametrize('plan,days',[('starter',14),('growth',14),('enterprise',7)])
def test_selected_trial_only_activates_after_verified_provider_confirmation(client,tenant,owner_db,provider,send,plan,days):
    response=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':plan})
    assert response.status_code==200,response.text
    sid=response.json()['session_id'];params=provider['requests'][0]
    assert params['mode']=='subscription' and params['payment_method_collection']=='always'
    assert params['subscription_data']['trial_period_days']==days
    assert 'trial_end' not in params['subscription_data']
    with owner_db.cursor() as cur:
        cur.execute('SELECT stripe_price_id FROM billing_plan_prices WHERE plan_key=%s AND period_code=%s AND retired_at IS NULL',(plan,'monthly'))
        assert params['line_items'][0]['price']==cur.fetchone()[0]
    no_access_rows(owner_db,tenant)
    assert client.get('/billing/checkout-status',headers=headers(tenant),params={'session_id':sid}).json()['state']=='pending'
    sub=provider['confirm'](sid)
    event='evt_trial_'+uuid.uuid4().hex
    # Subscription event is intentionally first. Checkout redirects are never authority.
    assert send('customer.subscription.created',sub,event).status_code==200
    assert send('customer.subscription.created',sub,event).json()['duplicate'] is True
    assert send('checkout.session.completed',provider['sessions'][sid],created=int(time.time())-10).status_code==200
    with closing(db.app_role_connection(*tenant)) as conn:
        trial=store.trial(conn,tenant[0]);effective=usage.get_plan(conn,tenant[0])
        assert trial['plan_key']==effective['plan_key']==plan
        assert trial['ends_at']-trial['started_at']==timedelta(days=days)
        assert effective['status']=='trialing' and effective['source']=='stripe'
    with owner_db.cursor() as cur:
        cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))
        snapshot=cur.fetchone()[0];assert snapshot['plan_key']==plan
        cur.execute('SELECT feature_code,COALESCE(trial_limit_value,limit_value) FROM usage_plan_limits WHERE plan_key=%s',(plan,))
        assert {code:item['limit'] for code,item in effective['features'].items()}==dict(cur.fetchall())
        for table in ('billing_trials','billing_subscriptions','tenant_plan_assignments'):
            cur.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==1
    again=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':plan})
    assert again.status_code==409


def test_missing_recurring_method_never_activates_and_retry_is_safe(client,tenant,owner_db,provider,send):
    response=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    sub=provider['confirm'](response.json()['session_id'],ready=False)
    event='evt_setup_'+uuid.uuid4().hex
    assert send('customer.subscription.created',sub,event).status_code==500
    no_access_rows(owner_db,tenant)
    sub['default_payment_method']='pm_offline_fixture'
    assert send('customer.subscription.created',sub,event).status_code==200


def test_rejected_provider_setup_releases_eligibility(client,tenant,owner_db,provider,monkeypatch):
    from src.ai.billing.payment_contracts import PaymentProviderError,ProviderOperationOutcome
    real=stripe_api.create_checkout_session
    def reject(*a,**kw):raise PaymentProviderError(ProviderOperationOutcome.REJECTED)
    monkeypatch.setattr(stripe_api,'create_checkout_session',reject)
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'}).status_code>=400
    no_access_rows(owner_db,tenant)
    monkeypatch.setattr(stripe_api,'create_checkout_session',real)
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'}).status_code==200
    no_access_rows(owner_db,tenant)


def test_abandoned_trial_checkout_can_expire_and_retry_without_consumption(client,tenant,owner_db,provider):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    retry=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    assert first.json()==retry.json() and len(provider['requests'])==1
    no_access_rows(owner_db,tenant)
    assert client.post('/billing/checkout/cancel-pending',headers=headers(tenant)).status_code==200
    second=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'starter'})
    assert second.status_code==200 and second.json()['session_id']!=first.json()['session_id']
    no_access_rows(owner_db,tenant)


def test_concurrent_selected_plan_requests_create_one_pending_provider_checkout(client,tenant,owner_db,provider):
    def start(plan):
        return client.post('/billing/trial',headers=headers(tenant),json={'plan_key':plan}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(start,['enterprise','starter','enterprise','growth']))
    assert 200 in results and set(results)<={200,409}
    assert len(provider['requests'])==1
    no_access_rows(owner_db,tenant)


@pytest.mark.parametrize('extra',[{'trial_days':999},{'trial_end':9999999999},{'require_payment_method_before_activation':False},{'price_id':'forged'},
                                {'payment_method_ready':True},{'provider_subscription_id':'forged'},{'entitlement_plan':'growth'}])
def test_browser_cannot_override_trial_or_provider_terms(client,tenant,provider,extra):
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise',**extra}).status_code==422
    assert not provider['requests']


def test_zero_day_plan_uses_normal_paid_checkout(client,tenant,test_price,owner_db,provider,send):
    key,_=test_price
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':key}).status_code==409
    assert not provider['requests']
    response=client.post('/billing/checkout',headers=headers(tenant),json={'plan_key':key})
    assert response.status_code==200,response.text
    params=provider['requests'][-1]['subscription_data']
    assert 'trial_period_days' not in params and 'trial_end' not in params
    sub=provider['confirm'](response.json()['session_id'])
    assert send('customer.subscription.created',sub).status_code==200
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_trials WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==0


def test_normal_checkout_completion_activates_exactly_once(client,tenant,owner_db,provider,send):
    response=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    sid=response.json()['session_id']; sub=provider['confirm'](sid)
    no_access_rows(owner_db,tenant)
    assert send('checkout.session.completed',provider['sessions'][sid]).status_code==200
    with owner_db.cursor() as cur:
        cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],));snapshot=cur.fetchone()[0]
        cur.execute('SELECT count(*) FROM tenant_credit_balances WHERE tenant_id=%s',(tenant[0],));balances=cur.fetchone()[0]
    assert send('customer.subscription.updated',sub).status_code==200
    assert send('checkout.session.completed',provider['sessions'][sid]).status_code==200
    with owner_db.cursor() as cur:
        cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==snapshot
        cur.execute('SELECT count(*) FROM tenant_credit_balances WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==balances


def test_verified_expired_session_releases_reservation(client,tenant,owner_db,provider,send):
    first=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    sid=first.json()['session_id']; session=provider['sessions'][sid];session['status']='expired'
    assert send('checkout.session.expired',session).status_code==200
    no_access_rows(owner_db,tenant)
    with owner_db.cursor() as cur:
        cur.execute('SELECT state FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]=='released'
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'starter'}).status_code==200


@pytest.mark.parametrize('mutation',['plan','price','tenant','customer','duration','attempt','quantity'])
def test_mismatched_provider_evidence_never_activates(client,tenant,owner_db,provider,send,mutation):
    result=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    sub=provider['confirm'](result.json()['session_id'])
    if mutation=='plan':
        with owner_db.cursor() as cur:
            cur.execute("SELECT stripe_price_id FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL")
            sub['items']['data'][0]['price']['id']=cur.fetchone()[0]
    elif mutation=='price':
        # A replacement price for the SAME plan/term is still unauthorized.
        price=sub['items']['data'][0]['price']['id'];replacement='price_replaced_'+uuid.uuid4().hex
        with owner_db.cursor() as cur:cur.execute('UPDATE billing_plan_prices SET stripe_price_id=%s WHERE stripe_price_id=%s',(replacement,price))
        sub['items']['data'][0]['price']['id']=replacement
    elif mutation=='tenant':sub['metadata']['tenant_id']=str(uuid.uuid4())
    elif mutation=='customer':sub['customer']='cus_unrelated_'+uuid.uuid4().hex
    elif mutation=='duration':sub['trial_end']+=86400
    elif mutation=='attempt':sub['metadata']['keel_trial_attempt_id']=str(uuid.uuid4())
    elif mutation=='quantity':sub['items']['data'][0]['quantity']=2
    event='evt_mismatch_'+uuid.uuid4().hex
    assert send('customer.subscription.created',sub,event).status_code==500
    no_access_rows(owner_db,tenant)
    with owner_db.cursor() as cur:
        cur.execute('SELECT processed_at,error FROM billing_webhook_events WHERE stripe_event_id=%s',(event,))
        processed,error=cur.fetchone();assert processed is None and error


def test_pending_storage_and_confirmation_are_restricted(client,tenant,owner_db,provider):
    from .test_reconciliation_roles import deny
    response=client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'})
    with owner_db.cursor() as cur:
        cur.execute('SELECT attempt_id FROM billing_trial_checkouts WHERE tenant_id=%s',(tenant[0],));attempt=str(cur.fetchone()[0])
        cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_trial_checkouts'::regclass");assert cur.fetchone()==(True,True)
    with closing(db.billing_setup_connection(*tenant)) as setup,closing(db.app_role_connection(*tenant)) as app,closing(db.billing_webhook_connection('evt_unverified')) as webhook:
        for conn in (setup,app):
            deny(conn,'UPDATE billing_trial_checkouts SET state=%s WHERE attempt_id=%s',('activated',attempt))
            deny(conn,"SELECT billing_confirm_trial_checkout(%s,'offline','forged',now(),now()+interval '7 days')",(attempt,))
        deny(webhook,"SELECT billing_confirm_trial_checkout(%s,'offline','forged',now(),now()+interval '7 days')",(attempt,))
        with closing(db.app_role_connection(str(uuid.uuid4()),tenant[1])) as other,other.cursor() as cur:
            cur.execute('SELECT count(*) FROM billing_trial_checkouts');assert cur.fetchone()[0]==0
    no_access_rows(owner_db,tenant)


def test_manual_custom_paid_contract_supported_but_new_free_trial_blocked(owner_db,tenant):
    from src.ai.billing import admin
    terms=dict(tenant_id=tenant[0],contract_ref='test-negotiated',approved_by='synthetic-approval',reason='isolated paid contract',limits={},monthly_price=100)
    with pytest.raises(admin.AdminError,match='provider'):
        admin.set_custom_contract(owner_db,**terms,trial_days=7)
    no_access_rows(owner_db,tenant)
    admin.set_custom_contract(owner_db,**terms,trial_days=0)
    with owner_db.cursor() as cur:
        cur.execute('SELECT plan_key,status,source FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()==('custom','active','contract')


def test_expired_historical_trial_cannot_obtain_second_free_trial(client,tenant,owner_db,provider):
    from datetime import datetime,timezone
    assert store.start_trial(owner_db,tenant[0],now=datetime.now(timezone.utc)-timedelta(days=30),started_by_user_id=tenant[1],plan_key='growth')
    before=store.trial(owner_db,tenant[0])
    assert client.post('/billing/trial',headers=headers(tenant),json={'plan_key':'enterprise'}).status_code==409
    assert store.trial(owner_db,tenant[0])==before and not provider['requests']


def test_historical_custom_trial_remains_readable_and_unchanged(owner_db,tenant):
    from src.ai.billing import admin
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO tenant_custom_contracts(tenant_id,contract_ref,monthly_price,currency,trial_days,approved_by,reason) VALUES(%s,'historical-fixture',100,'USD',14,'synthetic-approval','grandfathering regression')",(tenant[0],))
        cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source,current_period_start,current_period_end) VALUES(%s,'custom','trialing','contract',CURRENT_DATE,CURRENT_DATE+14)",(tenant[0],))
        cur.execute('SELECT to_jsonb(a) FROM tenant_plan_assignments a WHERE tenant_id=%s',(tenant[0],));before=cur.fetchone()[0]
    effective=usage.get_plan(owner_db,tenant[0]);assert(effective['plan_key'],effective['status'])==('custom','trialing')
    with pytest.raises(admin.AdminError):
        admin.set_custom_contract(owner_db,tenant_id=tenant[0],contract_ref='historical-fixture',approved_by='synthetic-approval',reason='no automatic replacement',limits={},trial_days=14)
    with owner_db.cursor() as cur:
        cur.execute('SELECT to_jsonb(a) FROM tenant_plan_assignments a WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==before
        cur.execute('SELECT trial_days FROM tenant_custom_contracts WHERE tenant_id=%s',(tenant[0],));assert cur.fetchone()[0]==14


def test_trial_policy_layers_import_no_provider_sdk():
    root=Path(__file__).resolve().parents[2]/'src/ai'
    for file in ['onboarding_profile.py','billing/trial_checkouts.py','billing/payment_contracts.py','billing/service.py','billing/webhooks.py','core/usage.py','core/entitlements.py']:
        tree=ast.parse((root/file).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):assert all(n.name!='stripe' and not n.name.startswith('stripe.') for n in node.names),file
            if isinstance(node,ast.ImportFrom):assert not (node.module or '').startswith('stripe'),file


def test_one_person_concurrent_workspaces_reserve_only_one_trial(client,tenant,owner_db,provider):
    other=str(uuid.uuid4())
    try:
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic second workspace','JO','JOD')",(other,))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')",(other,tenant[1]))
        def start(tid):
            return client.post('/billing/trial',headers=headers((tid,tenant[1])),json={'plan_key':'enterprise'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(start,[tenant[0],other]))
        assert sorted(results)==[200,409] and len(provider['requests'])==1
        with owner_db.cursor() as cur:
            cur.execute("SELECT count(*) FROM billing_trial_checkouts WHERE started_by_user_id=%s AND state='pending'",(tenant[1],));assert cur.fetchone()[0]==1
        no_access_rows(owner_db,tenant);no_access_rows(owner_db,(other,tenant[1]))
    finally:
        with owner_db.cursor() as cur:cur.execute('DELETE FROM companies WHERE tenant_id=%s',(other,))
