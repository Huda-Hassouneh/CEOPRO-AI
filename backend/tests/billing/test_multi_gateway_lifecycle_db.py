"""Actual restricted SQL; provider/legal fixtures and elapsed time are synthetic.

Elapsed trials are seeded ONLY by the isolated installer, transactionally restoring
all guards before runtime tests. This is not provider/merchant acceptance or a
production clock-control mechanism. B4 confirmation is independently executed first.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
import hashlib,json,time,uuid,os
import psycopg2
import pytest
from src.ai import db
from src.ai.billing import payment_contracts as C,verification_observations as V
from src.ai.billing import trial_confirmation as T
from src.ai.billing.subscription_lifecycle import SubscriptionLifecycle,LifecycleRepository
from src.ai.core import usage,entitlements
from . import test_subscription_journey_db as J
from .test_subscription_journey_db import parties
from .test_recurring_consent_db import restricted_runtime,service,fingerprint


class SyntheticJourneyGateway:
    """Explicit all-capability test adapter, never Paddle's real readiness proof."""
    def __init__(self,binding,transport,**kw):self.binding=binding;self.transport=transport
    def check_policy(self,p):assert p['trial_start_mode']=='checkout_completion'
    def prepare(self,row,customer,policy,urls):
        r=row['reservation'];return dict(approved_terms=r['approved_terms'],customer=customer.opaque_id,
            idempotency_key='keel-trial-checkout-'+r['attempt_id'],transport=dict(metadata=dict(operation=r['attempt_id'])))
    def validate(self,s,d):
        assert s.reference.binding==self.binding and s.customer.opaque_id==d['provider_customer_id'] and s.client_reference==d['attempt_id']
    def submit(self,d,*,authorize):
        authorize();self.saved=C.CheckoutSnapshot(C.ProviderReference(self.binding.provider,'txn_'+d['attempt_id'],binding=self.binding),C.CheckoutState.OPEN,
            C.PaymentState.NOT_REQUIRED,C.ProviderReference(self.binding.provider,d['provider_customer_id'],binding=self.binding),None,
            'https://synthetic.example.test',d['attempt_id'],{},True)
        self.transport.sent.append(d);return self.saved
    def retrieve(self,d):
        return replace(self.saved,state=C.CheckoutState.COMPLETE,subscription=C.ProviderReference(self.binding.provider,'sub_'+self.saved.reference.opaque_id,binding=self.binding)) if self.transport.status=='complete' else self.saved


class SyntheticCustomerGateway:
    def __init__(self,binding):self.binding=binding;self.sent=[]
    def prepare_customer(self,intent):
        return C.FrozenCustomerRequest(intent.tenant_id,intent.operation_id,intent.binding,'keel-customer-'+intent.operation_id,
            intent.logical_request(),C.CustomerPayload.freeze({'SYNTHETIC':True}),'SYNTHETIC','fixture',C.CapabilityState.SUPPORTED,86400,5)
    def submit_customer(self,request,*,deadline,authorize):
        authorize();self.sent.append(request)
        return C.CustomerSnapshot(C.ProviderReference(self.binding.provider,'ctm_'+request.operation_id,binding=self.binding),
            request.tenant_id,request.operation_id,'create_response','SYNTHETIC')


@pytest.fixture(params=['stripe','paddle'])
def confirmed(owner_db,parties,monkeypatch,request):
    provider=request.param
    if provider=='paddle':
        with owner_db.cursor() as q:
            q.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
            bid='paddle_'+uuid.uuid4().hex
            q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'paddle','test',%s,true,'SYNTHETIC fixture only')",(bid,bid))
            q.execute("INSERT INTO billing_lifecycle_provider_approvals(binding_id,evidence_reference) VALUES(%s,'SYNTHETIC: not merchant acceptance')",(bid,))
            q.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) SELECT %s,price_id,'pri_'||replace(price_id::text,'-',''),'SYNTHETIC mapping' FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL",(bid,))
        monkeypatch.setattr(J,'StripeJourneyGateway',SyntheticJourneyGateway)
        monkeypatch.setattr(J,'Gateway',SyntheticCustomerGateway)
    generator=J.journey.__wrapped__(owner_db,parties)
    s=next(generator)
    try:
        J.accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete'
        result=s.flow.advance(s.operation,'en');assert result['state']=='confirmed'
        with owner_db.cursor() as q:
            q.execute('SELECT subscription_id FROM billing_trial_confirmations WHERE confirmation_id=%s',(result['confirmation_id'],));sid=str(q.fetchone()[0])
            q.execute('SELECT stripe_subscription_id,gateway_binding_id FROM billing_subscriptions WHERE subscription_id=%s',(sid,));legacy,binding=q.fetchone()
            assert (legacy is None)==(provider=='paddle') and binding==s.binding.binding_id
        s.sid=sid;s.provider=provider
        yield s
    finally:
        try:next(generator)
        except StopIteration:pass


@pytest.fixture
def elapsed(owner_db,confirmed):
    s=confirmed
    # Transactional installer-only time fixture; guards are restored before any
    # restricted service call. No application credential can perform this DDL.
    with owner_db.cursor() as q:
        q.execute('BEGIN')
        try:
            for table in ('billing_subscriptions','billing_trial_confirmations','billing_trials'):
                q.execute('ALTER TABLE '+table+' DISABLE TRIGGER USER')
            q.execute("UPDATE billing_subscriptions SET current_period_start=date_trunc('second',clock_timestamp())-interval '15 days',current_period_end=date_trunc('second',clock_timestamp())-interval '1 day',trial_end=date_trunc('second',clock_timestamp())-interval '1 day',last_event_at=date_trunc('second',clock_timestamp())-interval '2 days' WHERE subscription_id=%s",(s.sid,))
            q.execute('UPDATE billing_trial_confirmations c SET trial_started_at=s.current_period_start,trial_ends_at=s.trial_end FROM billing_subscriptions s WHERE c.subscription_id=s.subscription_id AND s.subscription_id=%s',(s.sid,))
            q.execute('UPDATE billing_trials t SET started_at=c.trial_started_at,ends_at=c.trial_ends_at FROM billing_trial_confirmations c WHERE t.tenant_id=c.tenant_id AND c.subscription_id=%s',(s.sid,))
            for table in ('billing_subscriptions','billing_trial_confirmations','billing_trials'):
                q.execute('ALTER TABLE '+table+' ENABLE TRIGGER USER')
            q.execute('COMMIT')
        except BaseException:q.execute('ROLLBACK');raise
    yield s


class LifecycleObserver:
    def __init__(self,s,context):
        self.binding=s.binding;self.context=context;self.state=C.SubscriptionState.ACTIVE;self.payment=True;self.mutate=None;self.cancel=False;self.paid_at=datetime.now(timezone.utc)
    def observe_subscription(self,request,*,event=None):
        s=self.context['subscription'];f=s['approved_terms'];now=datetime.now(timezone.utc)
        start=datetime.fromisoformat(s['trial_end']);end=start.replace(month=start.month+1) if start.month<12 else start.replace(year=start.year+1,month=1)
        # SQL uses calendar months, including the original UTC instant.
        terms=C.ObservedRecurringTerms(C.Money(Decimal(str(f['approved_amount'])),f['currency']),f['interval_months'],1,C.ProviderReference(self.binding.provider,s['provider_price_id'],binding=self.binding))
        pay=C.ObservedSettlement(C.ProviderReference(self.binding.provider,'paid_invoice_fixture',binding=self.binding),request.customer,request.subscription,terms.amount,
            C.PaymentState.PAID,True,False,self.paid_at,((start,end),),purpose=C.SettlementPurpose.RENEWAL) if self.payment else None
        value=C.ProviderVerificationObservation(request,C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,request.subscription,now,'SYNTHETIC','fixture'),C.VerificationOutcome.VERIFIED,
            C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED),customer=request.customer,subscription=request.subscription,
            subscription_state=self.state,terms=terms,settlement=pay,period_start=start,period_end=end,cancel_at_period_end=self.cancel)
        return self.mutate(value) if self.mutate else value


def build(s):
    ac=service(s.party,'ceopro_trial_attestor');cc=service(s.party,'ceopro_trial_confirmer')
    att=LifecycleRepository(ac,attestor=True);confirm=LifecycleRepository(cc);context=confirm.context(s.sid)
    observer=LifecycleObserver(s,context)
    flow=SubscriptionLifecycle(s.flow.observations,att,confirm,lambda b:observer)
    return flow,observer,ac,cc


def event(s,identity=None):
    now=datetime.now(timezone.utc)
    raw=dict(event_id=identity or 'evt_'+uuid.uuid4().hex,event_type='subscription.updated',occurred_at=now.isoformat(),data=dict(synthetic=True))
    return C.VerifiedPaymentEvent(s.provider,raw['event_id'],C.PaymentEventKind.SUBSCRIPTION_CHANGED,now,None,
        C.ProviderReference(s.provider,'sub_'+('cs_' if s.provider=='stripe' else 'txn_')+str(s.operation),binding=s.binding),None,None,None,json.dumps(raw).encode(),raw,binding=s.binding)


def test_both_providers_initial_confirmation_still_requires_b4_and_global_exclusivity(owner_db,confirmed):
    s=confirmed
    with closing(db.app_role_connection(*s.party)) as c:
        assert usage.get_plan(c,s.party[0])['status']=='trialing'
    # Cross-provider rows still share the original global unique index.
    with owner_db.cursor() as q:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            q.execute("INSERT INTO billing_subscriptions(tenant_id,stripe_subscription_id,stripe_customer_id,plan_key,period_code,status) VALUES(%s,%s,'cus_synthetic_other','growth','monthly','active')",(s.party[0],'sub_other_'+uuid.uuid4().hex))


def test_shared_paid_renewal_replay_cancellation_cutoff_and_credits(owner_db,elapsed):
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        with owner_db.cursor() as q:q.execute('SELECT count(*) FROM usage_ledger');ledger=q.fetchone()
        e=event(s);result=flow.reconcile(s.sid,e);assert result['state']=='active' and result['version']==1
        assert flow.reconcile(s.sid,e)==result
        from src.ai.billing import store
        with closing(db.app_role_connection(*s.party)) as c:
            payments=store.payments(c,s.party[0]);assert len(payments)==1 and payments[0]['provider']==s.provider
            assert payments[0]['binding_id']==s.binding.binding_id
        with closing(db.app_role_connection(*s.parties[1])) as c:assert store.payments(c,s.party[0])==[]
        observer.payment=False;observer.cancel=True
        assert flow.reconcile(s.sid,event(s))['state']=='active'
        with closing(db.app_role_connection(*s.party)) as c:
            p=usage.get_plan(c,s.party[0]);assert p['status']=='active' and p['access_ends_at']
            assert usage.get_plan(c,s.party[0],now=p['access_ends_at'])['status']=='expired'
        observer.state=C.SubscriptionState.CANCELLED
        assert flow.reconcile(s.sid,event(s))['state']=='active','Paid cancellation must retain settled access through cutoff'
        with owner_db.cursor() as q:
            q.execute('SELECT count(*) FROM usage_ledger');assert q.fetchone()==ledger
            q.execute('SELECT count(*) FROM billing_lifecycle_applications WHERE tenant_id=%s', (s.party[0],));assert q.fetchone()==(3,)
    finally:ac.close();cc.close()


def test_failure_then_verified_recovery_preserves_frozen_rights(owner_db,elapsed):
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        observer.state=C.SubscriptionState.PAST_DUE;observer.payment=False
        assert flow.reconcile(s.sid,event(s))['state']=='past_due'
        with closing(db.app_role_connection(*s.party)) as c:assert usage.get_plan(c,s.party[0])['status']=='past_due'
        observer.state=C.SubscriptionState.ACTIVE;observer.payment=True
        assert flow.reconcile(s.sid,event(s))['state']=='active'
    finally:ac.close();cc.close()


@pytest.mark.parametrize('problem',['zero','wrong_amount','currency','price','coverage','missing_payment','stale','changed_body','wrong_binding','revoked'])
def test_lifecycle_negative_boundaries_never_grant(owner_db,elapsed,problem):
    s=elapsed;flow,observer,ac,cc=build(s);e=event(s)
    try:
        if problem=='zero':observer.mutate=lambda o:replace(o,settlement=replace(o.settlement,amount_paid=C.Money(Decimal(0),'USD')))
        elif problem=='wrong_amount':observer.mutate=lambda o:replace(o,terms=replace(o.terms,amount=C.Money(o.terms.amount.amount+1,'USD')))
        elif problem=='currency':observer.mutate=lambda o:replace(o,terms=replace(o.terms,amount=C.Money(o.terms.amount.amount,'EUR')))
        elif problem=='price':observer.mutate=lambda o:replace(o,terms=replace(o.terms,price=C.ProviderReference(s.provider,'wrong',binding=s.binding)))
        elif problem=='coverage':observer.mutate=lambda o:replace(o,settlement=replace(o.settlement,coverage=((o.period_start,o.period_end+timedelta(days=1)),)))
        elif problem=='missing_payment':observer.payment=False
        elif problem=='stale':e=replace(e,occurred_at=e.occurred_at-timedelta(days=10))
        elif problem=='changed_body':
            observer.state=C.SubscriptionState.PAST_DUE;observer.payment=False;flow.reconcile(s.sid,e);e=replace(e,raw_payload=b'{"changed":true}',raw_evidence=dict(e.raw_evidence,data={'changed':True}))
        elif problem=='wrong_binding':e=replace(e,binding=replace(s.binding,binding_id='wrong'),subscription=None)
        else:
            with owner_db.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",s.party)
        before=fingerprint(owner_db)
        with pytest.raises((ValueError,psycopg2.Error)):flow.reconcile(s.sid,e)
        assert fingerprint(owner_db)==before
    finally:ac.close();cc.close()


def test_no_ordinary_runtime_can_attest_apply_or_write_lifecycle(owner_db,elapsed):
    s=elapsed
    for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook','ceopro_credit_accounting'):
        with closing(service(s.party,role)) as c:
            with c.cursor() as q:
                q.execute("SELECT has_function_privilege(current_user,'billing_lifecycle_apply(uuid)','EXECUTE'),has_function_privilege(current_user,'billing_lifecycle_attest(uuid,uuid,uuid,uuid,bigint)','EXECUTE'),has_table_privilege(current_user,'billing_lifecycle_attestations','INSERT')")
                assert q.fetchone()==(False,False,False)
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):q.execute('SELECT billing_lifecycle_apply(%s)',(str(uuid.uuid4()),))
            c.rollback()
    with closing(service(s.parties[1],'ceopro_trial_confirmer')) as c:
        with pytest.raises(T.ConfirmationError,match='42501'):LifecycleRepository(c).context(s.sid)


@pytest.mark.parametrize('problem',['invoice_rebound','stale_after_apply'])
def test_immutable_payment_identity_and_old_notifications_cannot_extend_access(owner_db,elapsed,problem):
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        first=event(s);flow.reconcile(s.sid,first);before=fingerprint(owner_db)
        if problem=='invoice_rebound':observer.mutate=lambda o:replace(o,settlement=replace(o.settlement,coverage=((o.period_start,o.period_end+timedelta(days=1)),)))
        else:first=replace(event(s),occurred_at=first.occurred_at-timedelta(seconds=1))
        with pytest.raises(ValueError):flow.reconcile(s.sid,first if problem=='stale_after_apply' else event(s))
        assert fingerprint(owner_db)==before
    finally:ac.close();cc.close()


def test_concurrent_consumption_has_one_immutable_application(owner_db,elapsed):
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        e=event(s)
        # Produce a valid attestation without consuming it; then use two real
        # password sockets concurrently against exactly that same attestation.
        original=flow.confirmer.apply;flow.confirmer.apply=lambda identity:{'attestation':identity}
        result=flow.reconcile(s.sid,e);flow.confirmer.apply=original
        def apply():
            with closing(service(s.party,'ceopro_trial_confirmer')) as c:
                try:return LifecycleRepository(c).apply(result['attestation'])
                except T.ConfirmationError as error:
                    assert str(error).endswith(('55P03','55000'));return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:apply(),range(2)))
        assert any(r and r['state']=='active' for r in results)
        assert original(result['attestation'])['version']==1
        with owner_db.cursor() as q:
            q.execute('SELECT count(*) FROM billing_lifecycle_applications WHERE tenant_id=%s',(s.party[0],));assert q.fetchone()==(1,)
    finally:ac.close();cc.close()


def test_real_adapter_translation_reaches_shared_restricted_sql(client,owner_db,elapsed,monkeypatch):
    from .test_multi_gateway_adapters import PaddleReader
    from .test_stripe_verification import Reader,data
    from src.ai.billing.paddle_gateway import PaddleVerificationGateway
    from src.ai.billing.subscription_lifecycle import StripeLifecycleAdapter
    from src.ai.billing.stripe_verification import StripeVerificationGateway
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        ctx=flow.confirmer.context(s.sid);sub=ctx['subscription'];terms=sub['approved_terms']
        start=datetime.fromisoformat(sub['trial_end']);end=start.replace(month=start.month+1) if start.month<12 else start.replace(year=start.year+1,month=1)
        begin,stop=int(start.timestamp()),int(end.timestamp());amount=str(int(Decimal(str(terms['approved_amount']))*100))
        e=event(s)
        if s.provider=='paddle':
            reader=PaddleReader();reader.binding=s.binding
            reader.s.update(id=sub['provider_subscription_id'],customer_id=sub['provider_customer_id'],current_billing_period=dict(starts_at=start.isoformat(),ends_at=end.isoformat()))
            reader.s['items'][0]['price'].update(id=sub['provider_price_id'],unit_price=dict(amount=amount,currency_code=terms['currency']))
            reader.t.update(customer_id=sub['provider_customer_id'],subscription_id=sub['provider_subscription_id'],billing_period=reader.s['current_billing_period'],items=deepcopy(reader.s['items']))
            reader.t['payments'][0].update(amount=amount,captured_at=start.isoformat())
            reader.t['details']['totals'].update(total=amount,subtotal=amount,grand_total=amount)
            reader.t['details']['line_items'][0]['price_id']=sub['provider_price_id']
            for detail in ('totals','unit_totals'):reader.t['details']['line_items'][0][detail].update(total=amount,subtotal=amount)
            adapter=PaddleVerificationGateway(s.binding,reader)
            e=replace(e,invoice=C.ProviderReference('paddle','txn_test',binding=s.binding))
        else:
            reader=Reader(s.binding)
            mapping={'cus_A':sub['provider_customer_id'],'sub_A':sub['provider_subscription_id'],'price_A':sub['provider_price_id'],'acct_A':s.binding.merchant_account_id,'tenant_A':sub['tenant_id']}
            def convert(v):
                if isinstance(v,dict):return {k:convert(x) for k,x in v.items()}
                if isinstance(v,list):return [convert(x) for x in v]
                return mapping.get(v,v) if isinstance(v,str) else v
            reader.data={(kind,mapping.get(identity,identity)):convert(value) for (kind,identity),value in reader.data.items()}
            remote=reader.data['subscription',sub['provider_subscription_id']];remote.update(status='active',trial_start=int(datetime.fromisoformat(sub['current_period_start']).timestamp()),trial_end=begin)
            remote['items']['data'][0].update(current_period_start=begin,current_period_end=stop)
            reader.data['price',sub['provider_price_id']].update(unit_amount=int(amount),unit_amount_decimal=amount)
            reader.data['invoice','in_A'].update(amount_paid=int(amount),billing_reason='subscription_cycle',status_transitions=dict(paid_at=begin))
            reader.data['invoice_lines','in_A']['data'][0].update(amount=int(amount),subtotal=int(amount),period=dict(start=begin,end=stop))
            adapter=StripeLifecycleAdapter(StripeVerificationGateway(s.binding,reader))
        flow.observer_for_binding=lambda b:adapter
        from contextlib import contextmanager
        from src.ai.billing.journey_webhooks import JourneyWebhookReconciler,BoundStripeJourneyWebhookDecoder
        from src.ai.billing.paddle_gateway import PaddleWebhookDecoder
        from .test_multi_gateway_adapters import signed as paddle_signed
        from .test_contract import signed as stripe_signed
        @contextmanager
        def resolve(notification):yield s.flow,s.operation,'en'
        s.flow.lifecycle=flow
        secret='SYNTHETIC_ENDPOINT_NOT_REAL'
        if s.provider=='paddle':
            raw=dict(event_id=e.event_id,event_type='transaction.completed',occurred_at=e.occurred_at.isoformat(),data=reader.t)
            decoder=PaddleWebhookDecoder(s.binding,secret)
            payload=json.dumps(raw).encode();header={'Paddle-Signature':paddle_signed(payload,int(time.time()),secret)}
        else:
            raw=dict(id=e.event_id,type='invoice.paid',created=int(e.occurred_at.timestamp()),livemode=False,data=dict(object=reader.data['invoice','in_A']))
            decoder=BoundStripeJourneyWebhookDecoder(s.binding,secret)
            payload=json.dumps(raw).encode();header={'Stripe-Signature':stripe_signed(payload,secret)}
        monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
        client.app.state.bound_journey_webhooks={s.provider:(decoder,JourneyWebhookReconciler(resolve))}
        try:
            route='/billing/trial-journeys/webhook/'+s.provider
            # Missing authoritative evidence must request delivery retry; it
            # cannot be acknowledged merely because its receipt was persisted.
            if s.provider=='paddle':reader.fail=True
            else:reader.error=RuntimeError('synthetic transient provider outage')
            assert client.post(route,content=payload,headers=header).status_code==500
            if s.provider=='paddle':reader.fail=False
            else:reader.error=None
            response=client.post(route,content=payload,headers=header)
            assert response.status_code==200,response.text
            assert response.json()['state']=='active'
            assert client.post(route,content=payload,headers=header).json()['version']==1
            assert client.post(route,content=payload+b' ',headers=header).status_code==400
        finally:del client.app.state.bound_journey_webhooks
        with closing(db.app_role_connection(*s.party)) as c:assert usage.get_plan(c,s.party[0])['status']=='active'
    finally:ac.close();cc.close()


journey=J.journey

def test_completed_withdrawal_compensation_recovers_lost_cancel_response_without_resending(owner_db,journey,monkeypatch):
    s=journey;p=J.accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete'
    s.collection.withdraw(s.operation,uuid.UUID(p['presentation_id']));s.gateway.cancellation_supported=True
    state={'status':'trialing','writes':0}
    def read(sid):return dict(id=sid,customer=next(iter(s.transport.sessions.values()))['customer'],livemode=False,status=state['status'],schedule=None)
    def cancel(sid,key):state.update(status='canceled',writes=state['writes']+1);raise TimeoutError('synthetic committed remote response lost')
    monkeypatch.setattr(s.transport,'subscription_retrieve',read)
    monkeypatch.setattr(s.transport,'subscription_cancel_immediately',cancel,raising=False)
    before=fingerprint(owner_db)
    assert s.flow.cleanup(s.operation)['state']=='pending'
    assert s.flow.cleanup(s.operation)['reason']=='provider_trial_compensated'
    assert state['writes']==1 and len(s.transport.sent)==1 and fingerprint(owner_db)==before
    with pytest.raises(ValueError):s.flow.advance(s.operation,'en')


def test_frozen_price_preview_and_restricted_catalog_safety(owner_db,elapsed):
    from src.ai.billing import store
    s=elapsed
    with closing(db.app_role_connection(*s.party)) as c:
        snap=store.subscription_price_snapshot(c,s.party[0]);assert Decimal(snap['exactAmount'])==Decimal(str(s.row['reservation']['approved_amount']))
    with owner_db.cursor() as q:
        q.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s)",(['billing_lifecycle_attestations','billing_lifecycle_applications','billing_lifecycle_provider_approvals','billing_journey_compensations','billing_lifecycle_payments'],))
        assert q.fetchall()==[(True,True)]*5
        for signature in ('billing_lifecycle_apply(uuid)','billing_lifecycle_context(uuid)','billing_lifecycle_attest(uuid,uuid,uuid,uuid,bigint)','billing_journey_compensate(uuid,text,text)'):
            q.execute("SELECT has_function_privilege('public',%s,'EXECUTE')",(signature,));assert q.fetchone()==(False,)


def test_shared_settlement_identity_cannot_be_claimed_across_tenants(owner_db,elapsed):
    s=elapsed
    second=J.journey.__wrapped__(owner_db,[s.parties[1],s.party]);other=next(second)
    try:
        J.accepted(other);other.flow.advance(other.operation,'en');other.transport.status='complete'
        result=other.flow.advance(other.operation,'en');assert result['state']=='confirmed'
        with owner_db.cursor() as q:
            q.execute('SELECT subscription_id FROM billing_trial_confirmations WHERE confirmation_id=%s',(result['confirmation_id'],));other.sid=str(q.fetchone()[0])
        other.provider=s.provider
        flow2,obs2,a2,c2=build(other)
        try:
            flow2.confirmer.apply=lambda identity:{'attestation':identity}
            prepared=flow2.reconcile(other.sid,event(other))
            ctx=flow2.confirmer.context(other.sid)['subscription'];begin=datetime.fromisoformat(ctx['trial_end']);end=begin+timedelta(days=30)
            with owner_db.cursor() as q:
                q.execute("INSERT INTO billing_lifecycle_payments(binding_id,provider_invoice_id,tenant_id,subscription_id,provider,amount,currency,paid_at,period_start,period_end,attestation_id) VALUES(%s,'paid_invoice_fixture',%s,%s,%s,59,'USD',now(),%s,%s,%s)",
                    (s.binding.binding_id,other.party[0],other.sid,s.provider,begin,end,prepared['attestation']))
        finally:a2.close();c2.close()
        flow,obs,a,c=build(s)
        try:
            before=fingerprint(owner_db)
            with pytest.raises(T.ConfirmationError,match='22023'):flow.reconcile(s.sid,event(s))
            assert fingerprint(owner_db)==before
        finally:a.close();c.close()
    finally:
        try:next(second)
        except StopIteration:pass


def test_billing_revocation_is_transactionally_stabilized_in_both_orders(owner_db,elapsed):
    s=elapsed;flow,observer,ac,cc=build(s)
    try:
        flow.confirmer.apply=lambda identity:{'attestation':identity}
        prepared=flow.reconcile(s.sid,event(s))['attestation']
        # An uncommitted demotion holds a conflicting authority row/advisory
        # lock. A fresh service cannot stabilize authorization behind it.
        with owner_db.cursor() as q:
            q.execute('BEGIN')
            try:
                q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",s.party)
                with pytest.raises(T.ConfirmationError,match='55P03'):LifecycleRepository(cc).apply(prepared)
            finally:q.execute('ROLLBACK')
        # Conversely, a stabilized application fences demotion until commit.
        with closing(service(s.party,'ceopro_trial_confirmer')) as first,closing(psycopg2.connect(os.environ['BILLING_TEST_DATABASE_URL'])) as revoke:
            with revoke.cursor() as q:q.execute('SELECT pg_backend_pid()');pid=q.fetchone()[0]
            with first.cursor() as q:q.execute('SELECT billing_lifecycle_apply(%s)',(prepared,));assert q.fetchone()[0]['state']=='active'
            def demote():
                with revoke.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",s.party)
                revoke.commit()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(demote)
                try:J.wait_blocked(owner_db,pid)
                finally:first.commit()
                pending.result(timeout=8)
        with pytest.raises(T.ConfirmationError,match='42501'):LifecycleRepository(cc).apply(prepared)
    finally:ac.close();cc.close()


def test_billing_calendar_preserves_original_anchor_across_clamping(owner_db):
    cases=[('2027-01-31','2027-01-31',1,'2027-02-28'),('2027-02-28','2027-01-31',1,'2027-03-31'),
        ('2027-02-28','2027-01-30',1,'2027-03-30'),('2028-01-31','2028-01-31',1,'2028-02-29'),
        ('2027-11-30','2027-01-31',3,'2028-02-29'),('2027-02-15','2027-01-31',0,'2027-02-28')]
    with owner_db.cursor() as q:
        for begin,anchor,months,expected in cases:
            q.execute('SELECT billing_lifecycle_boundary(%s::timestamptz,%s::timestamptz,%s)',(begin+'T12:34:56Z',anchor+'T12:34:56Z',months))
            assert q.fetchone()[0]==datetime.fromisoformat(expected+'T12:34:56+00:00')
