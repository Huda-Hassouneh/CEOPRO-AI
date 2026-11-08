"""Synthetic provider API fixtures; no merchant/provider acceptance."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import hashlib,hmac,json
from types import SimpleNamespace
import pytest
from src.ai.billing import payment_contracts as C
from src.ai.billing.paddle_gateway import (PaddleWebhookDecoder,PaddleVerificationGateway,BoundPaddleTransport,
    PaddleCancellationGateway,notification_digest)
from src.ai.billing.subscription_lifecycle import StripeLifecycleAdapter
from src.ai.billing.stripe_verification import StripeVerificationGateway
from .test_stripe_verification import Reader,subscription_request,NOW,START,STOP

B=C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,'slr_synthetic','binding_paddle')
ref=lambda value:C.ProviderReference('paddle',value,binding=B)


class PaddleReader:
    binding=B
    api_version='1'
    def __init__(self):
        self.calls=[];self.sent=[];self.fail=False
        self.s=dict(id='sub_test',customer_id='ctm_test',status='active',collection_mode='automatic',discount=None,
            current_billing_period=dict(starts_at=NOW.isoformat(),ends_at=(NOW+timedelta(days=30)).isoformat()),scheduled_change=None,
            items=[dict(quantity=1,price=dict(id='pri_test',billing_cycle=dict(interval='month',frequency=1),unit_price=dict(amount='5900',currency_code='USD')))])
        self.t=dict(id='txn_test',subscription_id='sub_test',customer_id='ctm_test',status='completed',collection_mode='automatic',
            origin='subscription_recurring',adjustments=[],currency_code='USD',billing_period=self.s['current_billing_period'],
            items=deepcopy(self.s['items']),details=dict(totals=dict(total='5900',grand_total='5900',subtotal='5900',tax='0',discount='0',credit='0',credit_to_balance='0'),line_items=[dict(price_id='pri_test',quantity=1,tax_rate='0',unit_totals=dict(subtotal='5900',discount='0',tax='0',total='5900'),totals=dict(subtotal='5900',discount='0',tax='0',total='5900'),proration=None)]),
            payments=[dict(status='captured',amount='5900',captured_at=NOW.isoformat())])
    def verify_namespace(self):
        if self.fail:raise RuntimeError('synthetic namespace unavailable')
    def request(self,method,path,body=None,*,params=None):
        self.calls.append((method,path,deepcopy(body)))
        if method=='POST':
            self.sent.append(body)
            if body['effective_from']=='immediately':self.s['status']='canceled'
            else:self.s['scheduled_change']=dict(action='cancel',effective_at=self.s['current_billing_period']['ends_at'])
        return deepcopy(self.t if path.startswith('/transactions/') else self.s)


def paddle_request():return C.SubscriptionObservationRequest('tenant',B,ref('ctm_test'),ref('sub_test'))

def paddle_event(reader=None):
    return C.VerifiedPaymentEvent('paddle','evt_test',C.PaymentEventKind.INVOICE_SETTLED,NOW,ref('ctm_test'),ref('sub_test'),None,ref('txn_test'),None,b'{}',{},binding=B)


def test_paddle_authoritative_renewal_is_scoped_precise_and_not_trial_readiness():
    r=PaddleReader();o=PaddleVerificationGateway(B,r,clock=lambda:NOW).observe_subscription(paddle_request(),event=paddle_event())
    assert o.outcome is C.VerificationOutcome.VERIFIED and o.settlement.amount_paid==C.Money(Decimal(59),'USD')
    assert o.settlement.purpose is C.SettlementPurpose.RENEWAL and o.recurring_authorization is None
    assert not o.capabilities.supports_card_backed_trial()


@pytest.mark.parametrize('problem',['customer','subscription','price','amount','currency','tax','credit','discount','authorized','manual','proration','origin','method_change','zero','partial','refund','missing_tax','line_price','line_quantity','line_total','line_tax_rate','missing_line_totals'])
def test_paddle_financial_and_identity_contradictions_never_prove_paid_coverage(problem):
    r=PaddleReader();t=r.t
    if problem=='customer':t['customer_id']='wrong'
    elif problem=='subscription':t['subscription_id']='wrong'
    elif problem=='price':t['items'][0]['price']['id']='wrong'
    elif problem=='amount':t['details']['totals']['total']='5901'
    elif problem=='currency':t['currency_code']='JPY'
    elif problem in ('tax','credit','discount'):t['details']['totals'][problem]='1'
    elif problem=='authorized':t['payments'][0]['status']='authorized'
    elif problem=='manual':t['collection_mode']='manual'
    elif problem=='proration':t['details']['line_items'][0]['proration']={'rate':'0.5'}
    elif problem in ('origin','method_change'):t['origin']='subscription_payment_method_change'
    elif problem=='zero':t['details']['totals'].update(total='0',grand_total='0',subtotal='0');t['payments'][0]['amount']='0'
    elif problem=='refund':t['adjustments']=[{'action':'refund','status':'approved'}]
    elif problem=='missing_tax':del t['details']['totals']['tax']
    elif problem=='line_price':t['details']['line_items'][0]['price_id']='another_price'
    elif problem=='line_quantity':t['details']['line_items'][0]['quantity']=2
    elif problem=='line_total':t['details']['line_items'][0]['unit_totals']['total']='5901'
    elif problem=='line_tax_rate':t['details']['line_items'][0]['tax_rate']='0.1'
    elif problem=='missing_line_totals':del t['details']['line_items'][0]['totals']
    else:t['payments'][0]['amount']='2900'
    o=PaddleVerificationGateway(B,r,clock=lambda:NOW).observe_subscription(paddle_request(),event=paddle_event())
    assert o.outcome is not C.VerificationOutcome.VERIFIED and o.settlement is None


@pytest.mark.parametrize('state',['past_due','paused','canceled','trialing'])
def test_paddle_lifecycle_states_do_not_invent_payment_or_setup_authority(state):
    r=PaddleReader();r.s['status']=state
    o=PaddleVerificationGateway(B,r,clock=lambda:NOW).observe_subscription(paddle_request())
    assert o.settlement is None and o.recurring_authorization is None
    assert o.subscription_state.value=={'canceled':'cancelled'}.get(state,state)
    if state=='trialing':assert o.outcome is C.VerificationOutcome.PENDING


def signed(body,ts=1000,secret='SYNTHETIC'):
    return 'ts='+str(ts)+';h1='+hmac.new(secret.encode(),str(ts).encode()+b':'+body,hashlib.sha256).hexdigest()


@pytest.mark.parametrize('problem',['tampered','expired','future','secret','duplicate_ts','duplicate_json','valid'])
def test_paddle_raw_signature_and_time_boundary(problem):
    raw=dict(event_id='evt_test',event_type='transaction.completed',occurred_at=NOW.isoformat(),notification_id='ntf_one',data=dict(id='txn_test',subscription_id='sub_test',customer_id='ctm_test'))
    body=json.dumps(raw).encode();ts=900 if problem=='expired' else 1100 if problem=='future' else 1000
    if problem=='duplicate_json':body=b'{"event_id":"evt_test",'+body[1:]
    header=signed(body,ts,'wrong' if problem=='secret' else 'SYNTHETIC')
    if problem=='tampered':body+=b' '
    if problem=='duplicate_ts':header+=';ts=1000'
    decoder=PaddleWebhookDecoder(B,'SYNTHETIC',clock=lambda:1000)
    if problem=='valid':
        e=decoder.decode(body,header);assert e.binding==B and e.invoice==ref('txn_test') and e.raw_payload==body
    else:
        with pytest.raises(C.InvalidPaymentWebhook):decoder.decode(body,header)


def test_delivery_notification_identity_is_not_immutable_event_identity():
    raw=dict(event_id='evt_test',event_type='subscription.updated',occurred_at=NOW.isoformat(),notification_id='ntf_first',data=dict(id='sub_test',customer_id='ctm_test'))
    decoder=PaddleWebhookDecoder(B,'SYNTHETIC',clock=lambda:1000)
    def decode():
        body=json.dumps(raw).encode();return decoder.decode(body,signed(body))
    a=decode();raw['notification_id']='ntf_second';b=decode()
    assert a.raw_payload!=b.raw_payload and notification_digest(a)==notification_digest(b)
    raw['data']['customer_id']='wrong';assert notification_digest(a)!=notification_digest(decode())


def test_paddle_scheduled_cancellation_and_immediate_trial_compensation_are_distinct():
    r=PaddleReader();g=PaddleCancellationGateway(B,r,merchant_reviewed=True);c=dict(provider_subscription_id='sub_test',provider_customer_id='ctm_test')
    assert g.cancel(c,submit=True,authorize=lambda:None)
    assert r.sent==[{'effective_from':'next_billing_period'}]
    assert g.cancel(c,submit=False,authorize=lambda:pytest.fail('Retry must not write'))
    r.s.update(status='trialing',scheduled_change=None)
    session=C.CheckoutSnapshot(ref('txn_test'),C.CheckoutState.COMPLETE,C.PaymentState.NOT_REQUIRED,ref('ctm_test'),ref('sub_test'),None,'op',{},True)
    assert g.compensate(session,dict(provider_customer_id='ctm_test'),submit=True,authorize=lambda:None)
    assert r.sent[-1]=={'effective_from':'immediately'}


def test_paddle_live_and_unreviewed_operations_are_refused():
    live=replace(B,environment=C.GatewayEnvironment.LIVE)
    with pytest.raises(ValueError):BoundPaddleTransport(live,'pdl_live_apikey_synthetic')
    with pytest.raises(ValueError):PaddleWebhookDecoder(live,'SYNTHETIC')
    r=PaddleReader();g=PaddleCancellationGateway(B,r)
    with pytest.raises(ValueError):g.cancel({},submit=True,authorize=lambda:None)
    assert r.calls==[]


def test_stripe_shared_lifecycle_reuses_strict_verification_and_exact_invoice():
    r=Reader();r.data['subscription','sub_A']['status']='active'
    r.data['invoice','in_A'].update(amount_paid=5900,billing_reason='subscription_cycle')
    for line in r.data['invoice_lines','in_A']['data']:line.update(amount=5900,subtotal=5900)
    g=StripeLifecycleAdapter(StripeVerificationGateway(r.binding,r,lambda:NOW))
    o=g.observe_subscription(subscription_request())
    assert o.outcome is C.VerificationOutcome.VERIFIED and o.settlement.amount_paid.amount==Decimal(59)
    e=C.VerifiedPaymentEvent('stripe','evt',C.PaymentEventKind.INVOICE_SETTLED,NOW,None,None,None,C.ProviderReference('stripe','wrong',binding=r.binding),None,b'{}',{},binding=r.binding)
    with pytest.raises(ValueError,match='settlement'):g.observe_subscription(subscription_request(),event=e)


@pytest.mark.parametrize('problem',['namespace','redirect','timeout','valid'])
def test_paddle_transport_pins_origin_version_and_never_retries_writes(problem):
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        if problem=='timeout':raise TimeoutError('synthetic')
        return SimpleNamespace(status_code=302 if problem=='redirect' else 200,
            json=lambda:{'data':{'id':'wrong' if problem=='namespace' else B.merchant_account_id}})
    transport=BoundPaddleTransport(B,'pdl_sdbx_apikey_SYNTHETIC',client=SimpleNamespace(request=request))
    if problem=='valid':transport.verify_namespace()
    elif problem=='namespace':
        with pytest.raises(ValueError):transport.verify_namespace()
    else:
        with pytest.raises(C.PaymentProviderError):transport.request('POST','/transactions',{})
    assert len(calls)==1 and calls[0][1].startswith('https://sandbox-api.paddle.com/')
    assert calls[0][2]['follow_redirects'] is False and calls[0][2]['headers']['Paddle-Version']=='1'


def test_paddle_single_sender_encoder_has_no_unproved_idempotency_or_negative_recovery():
    from src.ai.billing.paddle_gateway import PaddleJourneyGateway
    class Transport(PaddleReader):
        def request(self,method,path,body=None,**kwargs):
            if method=='GET' and path=='/transactions':return dict(items=[],has_more=False)
            if path.startswith('/prices/'):
                return dict(id='pri_test',status='active',trial_period=dict(interval='day',frequency=14),billing_cycle=dict(interval='month',frequency=1),unit_price=dict(amount='5900',currency_code='USD'))
            assert method=='POST' and path=='/transactions'
            self.sent.append(deepcopy(body))
            return dict(id='txn_test',status='ready',customer_id='ctm_test',currency_code='USD',collection_mode='automatic',items=[dict(quantity=1,price=dict(id='pri_test',unit_price=dict(amount='5900',currency_code='USD'),billing_cycle=dict(interval='month',frequency=1),trial_period=dict(interval='day',frequency=14)))],
                custom_data=body['custom_data'],checkout=dict(url=body['checkout']['url']+'&_ptxn=txn_test'))
    t=Transport();g=PaddleJourneyGateway(B,t,merchant_reviewed=True,approved_checkout_origin='https://merchant.example.test',checkout_page_ready=True)
    terms=dict(tenant_id='tenant',binding=dict(provider='paddle',environment='test',merchant_account_id=B.merchant_account_id,binding_id=B.binding_id),approved_amount='59',currency='USD',interval_months=1,provider_price_id='pri_test')
    r=dict(attempt_id='operation',tenant_id='tenant',trial_duration_days=14,provider_price_id='pri_test',approved_terms=terms)
    request=g.prepare({'reservation':r},ref('ctm_test'),{'trial_start_mode':'checkout_completion'},('https://merchant.example.test/pay?trial_operation=operation','https://merchant.example.test/cancel'))
    d=dict(binding_id=B.binding_id,attempt_id='operation',tenant_id='tenant',provider_customer_id='ctm_test',request=request,provider_checkout_id=None)
    receipt=dict(d,submitted_at='synthetic committed election')
    assert g.submit(d,authorize=lambda:receipt).state is C.CheckoutState.OPEN
    assert g.recover(d) is None and len(t.sent)==1
    d['request']['transport']['items'][0]['quantity']=2
    with pytest.raises(ValueError):g.submit(d,authorize=lambda:pytest.fail('Conflicting request cannot authorize'))
    assert len(t.sent)==1


@pytest.mark.parametrize('switch',['binding','api_version'])
def test_paddle_transport_cannot_switch_namespace_during_an_authoritative_read(switch):
    r=PaddleReader();original=r.request
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        if switch=='binding':r.binding=replace(B,binding_id='another_binding')
        else:r.api_version='unaccepted-version'
        return result
    r.request=changed
    o=PaddleVerificationGateway(B,r,clock=lambda:NOW).observe_subscription(paddle_request(),event=paddle_event())
    assert o.outcome is not C.VerificationOutcome.VERIFIED and o.customer is None and o.settlement is None
