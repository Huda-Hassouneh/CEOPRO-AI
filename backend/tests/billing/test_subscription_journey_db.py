"""Connected synthetic journey using actual restricted PG identities, no APIs.

Installer supplies explicitly synthetic approved legal/provider fixtures only.
These capabilities and approvals are NOT production or Stripe acceptance.
"""
from contextlib import ExitStack, closing
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from types import SimpleNamespace
import uuid
import pytest
import psycopg2
from src.ai import db
from src.ai.billing import payment_contracts as C, customer_operations as U
from src.ai.billing import recurring_consent as R, verification_observations as V, trial_confirmation as T
from src.ai.billing.authenticated_consent import ConsentCollection, PolicyDocument, CollectionBlocked
from src.ai.billing.subscription_journey import SubscriptionJourney, DispatchRepository
from src.ai.billing.stripe_journey import StripeJourneyGateway
from src.ai.billing.trial_coordinator import ReservationRepository, _binding, observation_identity, customer_identity
from src.ai.core import usage, entitlements
from .test_recurring_consent_db import policy, service, restricted_runtime, fingerprint
from .test_payment_bindings_db import parties as legacy_parties
from .test_recurring_consent_db import wait_blocked
from .test_customer_operations_db import Gateway


class CheckoutTransport:
    """Synthetic provider retains accepted writes even if their response is lost."""
    def __init__(self,binding):
        self.binding=binding; self.sent=[]; self.sessions={}; self.timeout=False; self.status='open'
    def verify_namespace(self): pass
    def checkout_create(self,payload,key):
        self.sent.append((deepcopy(payload),key))
        value=dict(payload,id='cs_'+payload['client_reference_id'],status='open',livemode=False,url='https://checkout.stripe.com/c/synthetic')
        self.sessions[value['id']]=value
        if self.timeout: raise TimeoutError('synthetic lost response')
        return deepcopy(value)
    def checkout_retrieve(self,identity):
        value=deepcopy(self.sessions[identity]);value['status']=self.status
        if self.status=='complete': value['subscription']='sub_'+identity
        return value
    def checkout_list(self,customer):
        return [v for v in self.sessions.values() if v['customer']==customer]
    def checkout_expire(self,identity,key):
        self.status='expired';return self.checkout_retrieve(identity)
    def subscription_retrieve(self,identity):
        value=next(iter(self.sessions.values()))
        return dict(id=identity,customer=value['customer'],livemode=False,current_period_end=123456789,
                    cancel_at_period_end=getattr(self,'canceled',False),schedule=None)
    def subscription_cancel(self,identity,key):
        self.canceled=True;self.cancel_calls=getattr(self,'cancel_calls',0)+1
        return self.subscription_retrieve(identity)


class Observer:
    def __init__(self,binding):
        self.binding=binding;self.ready=True;self.capabilities=True;self.start=None;self.mutate=None
    def observe_trial_checkout(self,request):
        now=datetime.now(timezone.utc);self.start=self.start or now
        ref=lambda s:C.ProviderReference(self.binding.provider,s,binding=self.binding)
        readiness=(C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED if self.ready else C.PaymentMethodReadiness.PENDING_SETUP)
        caps=C.GatewayCapabilities(**{f.name:C.CapabilityState.SUPPORTED for f in fields(C.GatewayCapabilities)}) if self.capabilities else C.GatewayCapabilities()
        value=C.ProviderVerificationObservation(request,C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,
            request.checkout,now,'SYNTHETIC-FULL-JOURNEY','synthetic'),C.VerificationOutcome.PENDING,caps,
            customer=request.customer,checkout=request.checkout,subscription=ref('sub_'+request.checkout.opaque_id),
            checkout_state=C.CheckoutState.COMPLETE,subscription_state=C.SubscriptionState.TRIALING,
            terms=request.expected_terms,trial=C.ObservedTrialWindow(self.start,self.start+timedelta(days=14),self.start+timedelta(days=14)),
            payment_method=C.PaymentMethodEvidence(request.customer,ref('seti_synthetic'),now,readiness,ref('pm_synthetic')),
            recurring_authorization=C.RecurringAuthorizationEvidence(request.customer,ref('seti_synthetic'),C.RecurringAuthorizationKind.PAYMENT_METHOD_SETUP,readiness),
            cancel_at_period_end=False)
        return self.mutate(value) if self.mutate else value
    def checkout_window(self,request,observed): return observed.provenance.observed_at,observed.provenance.observed_at+timedelta(hours=1)


@pytest.fixture
def parties(owner_db,restricted_runtime):
    # Born into the new cohort, exactly like the registration INSERT trigger.
    with owner_db.cursor() as q:q.execute("SELECT set_config('app.recurring_journey_required','true',false)")
    try:yield from legacy_parties.__wrapped__(owner_db,restricted_runtime)
    finally:
        with owner_db.cursor() as q:q.execute("SELECT set_config('app.recurring_journey_required','false',false)")


@pytest.fixture
def journey(owner_db,parties):
    party=parties[0];operation=uuid.uuid4()
    with ExitStack() as stack:
        setup=stack.enter_context(closing(db.billing_setup_connection(*party)))
        cons=stack.enter_context(closing(service(party)))
        observe=stack.enter_context(closing(service(party,'ceopro_billing_observer')))
        attest=stack.enter_context(closing(service(party,'ceopro_trial_attestor')))
        confirm=stack.enter_context(closing(service(party,'ceopro_trial_confirmer')))
        reservations=ReservationRepository(setup)
        row=reservations.reserve(operation,'growth','monthly');binding=_binding(row)
        text='SYNTHETIC TEST AGREEMENT. NOT APPROVED LEGAL TEXT.'
        pid=policy(owner_db,agreement_digest='sha256:'+hashlib.sha256(text.encode()).hexdigest())
        with owner_db.cursor() as q:
            q.execute('SELECT to_jsonb(p) FROM billing_consent_policy_versions p WHERE policy_id=%s',(pid,));registry=q.fetchone()[0]
        keys=('agreement_reference','agreement_revision','language_tag','agreement_digest','cancellation_reference',
            'renewal_disclosure_reference','trial_start_rule_reference','retention_policy_reference','approval_reference')
        document=PolicyDocument(uuid.UUID(pid),text,'synthetic-operator','synthetic-refund',tuple((k,registry[k]) for k in keys),'provider_confirmed_trial_start')
        collection=ConsentCollection(*party,reservations,R.ConsentRepository(cons),policies=lambda *args:document,business_eligibility=lambda row:True)
        customer=Gateway(binding);transport=CheckoutTransport(binding);observer=Observer(binding)
        gateway=StripeJourneyGateway(binding,transport,provider_consent_reviewed=True)
        flow=SubscriptionJourney(collection,DispatchRepository(cons),U.CustomerRepository(setup),lambda b:customer,lambda b:gateway,
            V.ObservationRepository(observe),lambda b,history:observer,
            attestor=T.TrialConfirmationRepository(attest,attestor=True),confirmer=T.TrialConfirmationRepository(confirm),
            contact=lambda r:('synthetic@example.test','SYNTHETIC B2B'),
            return_urls=lambda r:('https://keel.example.test/onboarding/payment','https://keel.example.test/onboarding/payment'))
        yield SimpleNamespace(**locals())


def accepted(s):
    p=s.collection.present(s.operation,'en')
    s.collection.accept(s.operation,'en',uuid.UUID(p['presentation_id']),p['challenge'],True)
    return p


def complete(s):
    accepted(s);assert s.flow.advance(s.operation,'en')['state']=='checkout_ready'
    s.transport.status='complete'
    return s.flow.advance(s.operation,'en')


def test_connected_approved_synthetic_journey_confirmation_expiry_and_credit_integrity(owner_db,journey,monkeypatch):
    s=journey
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM tenant_credit_balances');credits=q.fetchone()
        q.execute('SELECT count(*) FROM usage_ledger');ledger=q.fetchone()
    result=complete(s)
    assert result['state']=='confirmed' and len(s.customer.sent)==len(s.transport.sent)==1
    assert s.flow.advance(s.operation,'en')['state']=='confirmed'
    with closing(db.app_role_connection(*s.party)) as c:
        assert usage.get_plan(c,s.party[0])['status']=='trialing'
        assert usage.get_plan(c,s.party[0],now=s.observer.start+timedelta(days=14))['status']=='expired'
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM tenant_credit_balances');assert q.fetchone()==credits
        q.execute('SELECT count(*) FROM usage_ledger');assert q.fetchone()==ledger
    monkeypatch.setattr(entitlements,'_cache',{})
    assert entitlements._plan(*s.party)['trial_ends_at']==s.observer.start+timedelta(days=14)
    with pytest.raises(CollectionBlocked,match='cancellation_unsupported'):s.flow.cancel(s.operation)
    with pytest.raises(R.ConsentError,match='55000'):
        s.collection.withdraw(s.operation,uuid.uuid5(s.operation,'consent-presentation:'+s.pid))


def test_supported_cancellation_is_durable_preserves_history_and_access_period(owner_db,journey):
    s=journey;complete(s);before=fingerprint(owner_db);s.gateway.cancellation_supported=True
    assert s.flow.cancel(s.operation)['state']=='cancellation_recorded'
    assert s.flow.cancel(s.operation)['state']=='cancellation_recorded'
    assert s.transport.cancel_calls==1 and fingerprint(owner_db)==before


def test_withdrawal_cleanup_expires_late_open_checkout_without_recreating(owner_db,journey):
    s=journey;p=accepted(s);s.transport.timeout=True;s.flow.advance(s.operation,'en')
    s.collection.withdraw(s.operation,uuid.UUID(p['presentation_id']))
    assert s.flow.cleanup(s.operation)['reason']=='provider_checkout_expired'
    assert len(s.transport.sent)==1 and s.transport.status=='expired'


def test_missing_policy_and_unchecked_consent_never_submit(owner_db,journey):
    s=journey;before=fingerprint(owner_db)
    s.collection.policies=None
    with pytest.raises(CollectionBlocked,match='policy_not_approved'):s.flow.advance(s.operation,'en')
    assert not s.customer.sent and not s.transport.sent and fingerprint(owner_db)==before
    s.collection.policies=lambda *a:s.document
    p=s.collection.present(s.operation,'en')
    with pytest.raises(CollectionBlocked,match='unchecked'):
        s.collection.accept(s.operation,'en',uuid.UUID(p['presentation_id']),p['challenge'],False)


def test_ambiguous_checkout_recovers_original_without_second_submission(owner_db,journey):
    s=journey;accepted(s);s.transport.timeout=True
    assert s.flow.advance(s.operation,'en')['reason']=='checkout_outcome_unknown'
    s.transport.timeout=False
    assert s.flow.advance(s.operation,'en')['state']=='checkout_ready'
    assert len(s.transport.sent)==len(s.customer.sent)==1


def test_authoritative_checkout_expiry_is_durable_and_status_never_calls_provider(owner_db,journey,monkeypatch):
    s=journey;accepted(s);s.flow.advance(s.operation,'en');before=fingerprint(owner_db)
    with monkeypatch.context() as m:
        m.setattr(s.gateway,'retrieve',lambda *a:pytest.fail('GET status cannot call provider'))
        assert s.flow.progress(s.operation)['state']=='pending'
    s.transport.status='expired'
    assert s.flow.advance(s.operation,'en')['state']=='expired'
    assert s.flow.progress(s.operation)['state']=='expired'
    assert s.flow.advance(s.operation,'en')['state']=='expired'
    assert len(s.transport.sent)==1 and fingerprint(owner_db)==before


def test_zero_recovery_never_resubmits_and_withdrawal_fences_late_checkout(owner_db,journey):
    s=journey;p=accepted(s);s.transport.timeout=True
    s.flow.advance(s.operation,'en');sessions=s.transport.sessions;s.transport.sessions={}
    assert s.flow.advance(s.operation,'en')['reason']=='checkout_recovery_required'
    assert len(s.transport.sent)==1
    s.collection.withdraw(s.operation,uuid.UUID(p['presentation_id']))
    s.transport.sessions=sessions;s.transport.status='complete'
    with pytest.raises(ValueError):s.flow.advance(s.operation,'en')
    assert len(s.transport.sent)==1


def test_pending_to_ready_keeps_history_and_setup_source(owner_db,journey):
    s=journey;accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete';s.observer.ready=False
    assert s.flow.advance(s.operation,'en')['reason']=='recurring_readiness_unproved'
    oid=observation_identity(s.operation)
    req=V.trial_request(s.flow.observations.context(s.operation))
    sub=C.ProviderReference('stripe','sub_cs_'+str(s.operation),binding=s.binding)
    assert s.flow.observations.setup_source(oid,sub)=='seti_synthetic'
    assert s.flow.observations.setup_source(oid,C.ProviderReference('stripe','wrong',binding=s.binding)) is None
    s.observer.ready=True
    assert s.flow.advance(s.operation,'en')['state']=='confirmed'
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s',(str(oid),));assert q.fetchone()==(2,)


@pytest.mark.parametrize('problem',['capability','terms','customer','binding','revoked','other_tenant'])
def test_negative_boundaries_never_grant_rights(owner_db,journey,problem):
    s=journey;accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete'
    if problem=='capability':s.observer.capabilities=False
    elif problem=='terms':s.observer.mutate=lambda o:replace(o,terms=replace(o.terms,amount=C.Money(o.terms.amount.amount+1,'USD')))
    elif problem=='customer':s.observer.mutate=lambda o:replace(o,customer=C.ProviderReference('stripe','wrong',binding=s.binding))
    elif problem=='binding':s.gateway.binding=replace(s.binding,binding_id='wrong')
    elif problem=='revoked':
        with owner_db.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",s.party)
    else:s.collection.tenant=s.parties[1][0]
    before=fingerprint(owner_db)
    try: result=s.flow.advance(s.operation,'en');assert result['state']!='confirmed'
    except (ValueError,psycopg2.Error):pass
    assert fingerprint(owner_db)==before


def test_native_runtime_acl_and_global_webhook_guard(owner_db,journey):
    from src.ai.billing.journey_webhooks import protected
    s=journey;accepted(s);s.flow.advance(s.operation,'en')
    d=s.flow.dispatches.command(s.operation,'read')
    with closing(service(s.parties[1],'ceopro_billing_webhook')) as c:
        assert protected(c,customer=d['provider_customer_id'])
        assert protected(c,checkout=d['provider_checkout_id'])
        assert not protected(c,customer='unknown_legacy')
    for role in ('ceopro_app','ceopro_billing_setup','ceopro_billing_webhook'):
        with closing(service(s.party,role)) as c:
            with c.cursor() as q:
                q.execute("SELECT has_function_privilege(current_user,'billing_journey_dispatch(uuid,uuid,uuid,jsonb,text,text)','EXECUTE'),has_table_privilege(current_user,'billing_journey_dispatches','INSERT')")
                assert q.fetchone()==(False,False)


def prepared(s):
    p=accepted(s)
    customer=U.resolve(s.flow.customers,C.CustomerIntent(s.party[0],str(customer_identity(s.row)),
        'recurring-trial-v1',s.binding,'synthetic@example.test','SYNTHETIC B2B'),s.flow.customer_gateway)
    request=s.gateway.prepare(s.row,customer,dict(s.document.values(),trial_start_mode='provider_confirmed_trial_start'),s.flow.return_urls(s.row))
    d=s.flow.dispatches.command(s.operation,'prepare',acceptance=uuid.uuid5(uuid.UUID(p['presentation_id']),'authenticated-acceptance-v1'),
        customer=customer_identity(s.row),request=request)
    return p,d


def test_concurrent_dispatch_has_exactly_one_elected_sender(owner_db,journey):
    s=journey;p,d=prepared(s)
    def elect():
        with closing(service(s.party)) as c:
            return DispatchRepository(c).command(s.operation,'elect',acceptance=d['acceptance_id'],customer=d['customer_operation_id'])
    with ThreadPoolExecutor() as pool:
        values=list(pool.map(lambda _:elect(),range(2)))
    assert sum(v['elected'] for v in values)==1
    assert values[0]['submitted_at']==values[1]['submitted_at']
    # Lost elected-process response cannot elect a replacement sender.
    assert elect()['elected'] is False


def test_withdrawal_commits_before_dispatch_election_denies_sender(owner_db,journey):
    s=journey;p,d=prepared(s)
    with closing(service(s.party)) as first,closing(service(s.party)) as second:
        with second.cursor() as q:q.execute('SELECT pg_backend_pid()');pid=q.fetchone()[0]
        with first.cursor() as q:q.execute('SELECT billing_consent_invalidate(%s,%s)',(p['presentation_id'],'withdrawn'))
        with ThreadPoolExecutor() as pool:
            future=pool.submit(lambda:DispatchRepository(second).command(s.operation,'elect',acceptance=d['acceptance_id'],customer=d['customer_operation_id']))
            try:wait_blocked(owner_db,pid)
            finally:first.commit()
            with pytest.raises(R.ConsentError,match='22023'):future.result(timeout=8)
    assert s.flow.dispatches.command(s.operation,'read')['submitted_at'] is None


def test_new_cohort_cannot_use_legacy_trial_sql_or_clear_cohort(owner_db,journey):
    s=journey
    with closing(db.billing_setup_connection(*s.party)) as c:
        with c.cursor() as q:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege) as error:q.execute("SELECT billing_setup_trial('growth',true)")
            assert error.value.diag.message_primary=='Trusted journey confirmation required'
    with owner_db.cursor() as q:
        with pytest.raises(psycopg2.errors.InvalidParameterValue):
            q.execute('UPDATE companies SET subscription_journey_required=false WHERE tenant_id=%s',(s.party[0],))


def test_unassigned_legacy_default_cannot_grant_new_cohort_access(journey,monkeypatch):
    s=journey;monkeypatch.setenv('UNASSIGNED_PLAN_ACCESS','default')
    with closing(db.app_role_connection(*s.party)) as c:
        assert usage.get_plan(c,s.party[0])['status']=='none'


def test_registration_company_cohort_selection_is_durable_and_default_off(owner_db,monkeypatch):
    from src.ai.routers.auth import _insert_company
    for enabled in (False,True):
        monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true' if enabled else 'false');tid=str(uuid.uuid4())
        with owner_db.cursor() as q:
            q.execute('BEGIN')
            try:_insert_company(q,tid,'Synthetic registration','US','USD',False);q.execute('COMMIT')
            except BaseException:q.execute('ROLLBACK');raise
            q.execute('SELECT subscription_journey_required FROM companies WHERE tenant_id=%s',(tid,))
            assert q.fetchone()==(enabled,)


def test_verified_webhook_completes_once_retries_and_malicious_event_cannot_use_legacy(owner_db,journey,monkeypatch):
    from src.ai.billing import webhooks
    from src.ai.billing.journey_webhooks import JourneyWebhookReconciler
    s=journey;accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete'
    d=s.flow.dispatches.command(s.operation,'read');session=s.gateway.retrieve(d)
    e=C.VerifiedPaymentEvent('stripe','evt_synthetic_'+str(s.operation),C.PaymentEventKind.CHECKOUT_COMPLETED,datetime.now(timezone.utc),
        session.customer,session.subscription,session.reference,None,None,b'{}',{},session,binding=s.binding)
    @contextmanager
    def resolve(event):yield s.flow,s.operation,'en'
    handler=JourneyWebhookReconciler(resolve)
    monkeypatch.setattr(webhooks,'_handle_locked',lambda *a:pytest.fail('No legacy fallthrough'))
    with closing(service(s.party,'ceopro_billing_webhook')) as c:
        assert webhooks.handle_event(c,e,journey_handler=handler)==dict(duplicate=False,journey=True)
        assert webhooks.handle_event(c,e,journey_handler=handler)==dict(duplicate=True,journey=True)
        with pytest.raises(webhooks.WebhookRetry):webhooks.handle_event(c,replace(e,raw_payload=b'{"changed":"body"}'),journey_handler=handler)
        wrong=replace(e,customer=C.ProviderReference('stripe','wrong',binding=s.binding))
        with pytest.raises(webhooks.WebhookRetry):webhooks.handle_event(c,wrong,journey_handler=handler)
        # Paid invoices/subscription updates are not silently acknowledged until
        # the trusted paid lifecycle contract is available. Trial still expires.
        with pytest.raises(webhooks.WebhookRetry):webhooks.handle_event(c,replace(e,kind=C.PaymentEventKind.INVOICE_SETTLED),journey_handler=handler)
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM billing_observation_receipts WHERE provider_event_id=%s',(e.event_id,));assert q.fetchone()==(1,)


def test_bound_signed_http_webhook_drives_actual_journey_and_replay(client,owner_db,journey,monkeypatch):
    from src.ai.billing.journey_webhooks import BoundStripeJourneyWebhookDecoder,JourneyWebhookReconciler
    from src.ai.billing import webhooks
    from .test_contract import signed
    s=journey;accepted(s);s.flow.advance(s.operation,'en');s.transport.status='complete'
    d=s.flow.dispatches.command(s.operation,'read')
    payload=json.dumps(dict(id='evt_http_'+str(s.operation),object='event',type='checkout.session.completed',
        livemode=False,created=int(time.time()),data=dict(object=s.transport.checkout_retrieve(d['provider_checkout_id'])))).encode()
    @contextmanager
    def resolve(event):yield s.flow,s.operation,'en'
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    monkeypatch.setattr(webhooks,'_handle_locked',lambda *a:pytest.fail('Dedicated endpoint cannot use legacy activation'))
    secret='whsec_SYNTHETIC_JOURNEY_NOT_REAL'
    client.app.state.subscription_journey_webhook_decoder=BoundStripeJourneyWebhookDecoder(s.binding,secret)
    client.app.state.subscription_journey_webhook_handler=JourneyWebhookReconciler(resolve)
    try:
        route='/billing/trial-journeys/webhook'
        headers={'Stripe-Signature':signed(payload,secret)}
        first=client.post(route,content=payload,headers=headers)
        assert first.status_code==200 and first.json()['journey'] is True,first.text
        assert client.post(route,content=payload,headers=headers).json()['duplicate'] is True
        assert client.post(route,content=payload+b' ',headers=headers).status_code==400
        with closing(db.app_role_connection(*s.party)) as c:assert usage.get_plan(c,s.party[0])['status']=='trialing'
    finally:
        del client.app.state.subscription_journey_webhook_decoder
        del client.app.state.subscription_journey_webhook_handler


@pytest.mark.parametrize('block',['withdrawn','revoked','unrelated_actor'])
def test_checkout_page_handoff_rechecks_protected_consent_and_current_actor(owner_db,journey,block):
    s=journey;p=accepted(s);s.flow.advance(s.operation,'en');before=fingerprint(owner_db)
    details=s.flow.checkout_details(s.operation,'en')
    assert details==dict(operation_id=str(s.operation),provider='stripe',environment='test',binding_id=s.binding.binding_id,transaction_id=next(iter(s.transport.sessions)))
    assert len(s.transport.sent)==1 and fingerprint(owner_db)==before
    if block=='withdrawn':s.collection.withdraw(s.operation,uuid.UUID(p['presentation_id']))
    elif block=='revoked':
        with owner_db.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",s.party)
    else:s.collection.actor=str(uuid.uuid4())
    with pytest.raises((CollectionBlocked,psycopg2.Error,R.ConsentError,ValueError)):
        s.flow.checkout_details(s.operation,'en')
    assert len(s.transport.sent)==1


def test_actual_paddle_customer_checkout_and_trial_observation_compose_without_fabricated_readiness(owner_db,parties,monkeypatch):
    from . import test_subscription_journey_db as J
    from .test_paddle_completion import CustomerReader
    from src.ai.billing.paddle_gateway import PaddleDurableCustomerGateway,PaddleJourneyGateway,PaddleVerificationGateway
    with owner_db.cursor() as q:
        q.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        bid='paddle_'+uuid.uuid4().hex
        q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'paddle','test',%s,true,'SYNTHETIC acceptance')",(bid,bid))
        q.execute("INSERT INTO billing_lifecycle_provider_approvals(binding_id,evidence_reference) VALUES(%s,'SYNTHETIC only')",(bid,))
        q.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) SELECT %s,price_id,'pri_'||replace(price_id::text,'-',''),'SYNTHETIC only' FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL",(bid,))
        q.execute("SELECT amount FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL");amount=q.fetchone()[0]
    readers={}
    class API(CustomerReader):
        def __init__(self,b):super().__init__(b);self.transactions=[];self.complete=False
        def price(self,identifier):return dict(id=identifier,status='active',billing_cycle=dict(interval='month',frequency=1),unit_price=dict(amount=str(int(amount*100)),currency_code='USD'),trial_period=dict(interval='day',frequency=14))
        def request(self,method,path,body=None,*,params=None):
            if path=='/customers' or path.startswith('/customers/'):return super().request(method,path,body,params=params)
            self.calls.append((method,path,deepcopy(body),deepcopy(params)))
            if path.startswith('/prices/'):return self.price(path.rsplit('/',1)[1])
            if method=='POST' and path=='/transactions':
                value=dict(deepcopy(body),id='txn_'+'a'*26,status='ready',currency_code='USD',items=[dict(quantity=1,price=self.price(body['items'][0]['price_id']))],
                    adjustments=[],details=dict(totals={k:'0' for k in ('total','grand_total','subtotal','tax','discount','credit','credit_to_balance')}))
                value['checkout']['url']+='&_ptxn='+value['id'];self.transactions.append(value)
                return deepcopy(value)
            if path=='/transactions':return dict(items=deepcopy(self.transactions),has_more=False)
            if path.startswith('/transactions/'):
                value=deepcopy(self.transactions[0])
                if self.complete:value.update(status='completed',subscription_id='sub_original')
                return value
            if path=='/subscriptions/sub_original':
                value=self.transactions[0];start=datetime.now(timezone.utc);end=start+timedelta(days=14)
                return dict(id='sub_original',customer_id=value['customer_id'],status='trialing',collection_mode='automatic',discount=None,scheduled_change=None,
                    current_billing_period=dict(starts_at=start.isoformat(),ends_at=end.isoformat()),
                    items=[dict(quantity=1,price=value['items'][0]['price'],trial_dates=dict(starts_at=start.isoformat(),ends_at=end.isoformat()))])
            raise AssertionError('Unexpected synthetic API')
    def api(b):return readers.setdefault(b.binding_id,API(b))
    monkeypatch.setattr(J,'Gateway',lambda b:PaddleDurableCustomerGateway(b,api(b),merchant_reviewed=True))
    monkeypatch.setattr(J,'CheckoutTransport',api)
    monkeypatch.setattr(J,'StripeJourneyGateway',lambda b,t,**kw:PaddleJourneyGateway(b,t,merchant_reviewed=True,checkout_page_ready=True,approved_checkout_origin='https://keel.example.test'))
    monkeypatch.setattr(J,'Observer',lambda b:PaddleVerificationGateway(b,api(b)))
    generator=J.journey.__wrapped__(owner_db,parties);s=next(generator)
    try:
        accepted(s);before=fingerprint(owner_db)
        assert s.flow.advance(s.operation,'en')['state']=='checkout_ready'
        assert s.flow.advance(s.operation,'en')['state']=='checkout_ready'
        t=readers[bid];t.complete=True
        result=s.flow.advance(s.operation,'en')
        assert result['state']=='blocked' and result['reason']=='provider_capabilities_unproved'
        assert sum(c[0]=='POST' and c[1]=='/customers' for c in t.calls)==1
        assert sum(c[0]=='POST' and c[1]=='/transactions' for c in t.calls)==1
        assert fingerprint(owner_db)==before
        with owner_db.cursor() as q:
            q.execute("SELECT outcome,evidence->>'subscription' FROM billing_verification_observations WHERE operation_id=%s",(str(observation_identity(s.operation)),))
            assert q.fetchall()==[('pending','sub_original')]
    finally:
        try:next(generator)
        except StopIteration:pass
