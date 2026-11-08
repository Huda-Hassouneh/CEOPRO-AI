"""Offline adversarial edges, authenticated routes and provider-association tests."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, MagicMock
from uuid import UUID, uuid4
import pytest
from src.ai.billing import payment_contracts as C
from src.ai.billing import webhooks
from src.ai.billing.stripe_verification import StripeVerificationGateway
from src.ai.billing.journey_webhooks import protected
from src.ai.billing.journey_policies import ApprovedPolicyCatalog
from src.ai.billing.authenticated_consent import CollectionBlocked, PolicyDocument
from .test_stripe_verification import Reader, trial_request, NOW
from .test_trial_journey_preview import preview


def test_durable_setup_fallback_freshly_verifies_exact_off_session_authority():
    reader=Reader();reader.data['subscription','sub_A']['pending_setup_intent']=None
    source=Mock(return_value='seti_A')
    observed=StripeVerificationGateway(reader.binding,reader,lambda:NOW,_setup_source=source).observe_trial_checkout(trial_request())
    assert source.call_args.args==(trial_request(),C.ProviderReference('stripe','sub_A',binding=reader.binding))
    assert ('setup_intent','seti_A') in reader.calls
    assert observed.recurring_authorization.readiness is C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED
    assert observed.outcome is C.VerificationOutcome.PENDING
    assert not observed.capabilities.supports_card_backed_trial()


@pytest.mark.parametrize('change',['attached_only','wrong_customer','wrong_method','on_session','pending','canceled'])
def test_setup_history_never_overrides_current_provider_truth(change):
    r=Reader();r.data['subscription','sub_A']['pending_setup_intent']=None
    setup=r.data['setup_intent','seti_A'];source=lambda *a:'seti_A'
    if change=='attached_only':source=lambda *a:None
    elif change=='wrong_customer':setup['customer']='cus_wrong'
    elif change=='wrong_method':setup['payment_method']='pm_wrong'
    elif change=='on_session':setup['usage']='on_session'
    elif change=='pending':setup['status']='processing'
    else:setup['status']='canceled'
    o=StripeVerificationGateway(r.binding,r,lambda:NOW,_setup_source=source).observe_trial_checkout(trial_request())
    assert o.outcome is not C.VerificationOutcome.VERIFIED
    assert o.recurring_authorization is None or o.recurring_authorization.readiness is not C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED


def event():
    return C.VerifiedPaymentEvent('stripe','evt_synthetic',C.PaymentEventKind.UNKNOWN,NOW,None,None,None,None,None,b'{}',{})


def test_webhook_lookup_failure_or_protected_cohort_never_reaches_legacy(monkeypatch):
    conn=MagicMock();q=conn.cursor.return_value.__enter__.return_value
    legacy=Mock();monkeypatch.setattr(webhooks,'_handle_locked',legacy)
    q.fetchone.return_value=(True,)
    with pytest.raises(webhooks.WebhookRetry,match='reconciliation unavailable'):webhooks.handle_event(conn,event())
    legacy.assert_not_called()
    q.execute.side_effect=RuntimeError('synthetic missing lookup/DB outage')
    with pytest.raises(webhooks.WebhookRetry,match='classification unavailable'):webhooks.handle_event(conn,event())
    legacy.assert_not_called()


def test_marked_unknown_event_is_quarantined_and_failed_handler_cannot_fall_through(monkeypatch):
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
    legacy=Mock();monkeypatch.setattr(webhooks,'_handle_locked',legacy)
    e=replace(event(),raw_evidence={'data':{'object':{'metadata':{'billing_kind':'keel_recurring_journey'}}}})
    handler=Mock(side_effect=ValueError('missing consent'))
    with pytest.raises(webhooks.WebhookRetry):webhooks.handle_event(conn,e,journey_handler=handler)
    legacy.assert_not_called();handler.assert_called_once_with(e)
    assert protected(conn,metadata={'keel_journey_operation':'malformed'})


def test_unmarked_unrelated_event_retains_legacy_dispatch(monkeypatch):
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
    legacy=Mock(return_value={'duplicate':True});monkeypatch.setattr(webhooks,'_handle_locked',legacy)
    assert webhooks.handle_event(conn,event())=={'duplicate':True}
    legacy.assert_called_once()


def test_new_routes_default_off_authenticated_and_reject_injected_identity(client,preview,monkeypatch):
    endpoint='/billing/trial-journeys';body=dict(request_key=str(uuid4()),plan_key='growth',period_code='monthly')
    assert client.post(endpoint,json=body).status_code==401
    assert client.post(endpoint,json=body,headers=preview['headers']).status_code==404
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    assert client.post(endpoint,json=body,headers=preview['headers']).status_code==503
    for key in ('tenant_id','actor_id','binding_id','approved_amount','accepted_at'):
        assert client.post(endpoint,json=dict(body,**{key:'injected'}),headers=preview['headers']).status_code==422


def test_factory_lifetime_and_server_owned_stable_operation(client,preview,monkeypatch):
    from src.ai import db
    connection=MagicMock();connection.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,)
    monkeypatch.setattr(db,'app_role_connection',lambda *a:connection)
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true');closed=[];flow=Mock()
    flow.start.side_effect=lambda op,*a:dict(operation_id=str(op),state='reserved')
    @contextmanager
    def factory(ctx):
        assert (ctx.tenant_id,ctx.user_id)==(preview['tenant'],preview['actor'])
        try:yield flow
        finally:closed.append(True)
    client.app.state.subscription_journey_factory=factory
    try:
        body=dict(request_key=str(uuid4()),plan_key='growth',period_code='monthly')
        a=client.post('/billing/trial-journeys',json=body,headers=preview['headers'])
        b=client.post('/billing/trial-journeys',json=body,headers=preview['headers'])
        assert a.status_code==b.status_code==200 and a.json()==b.json() and closed==[True,True]
        assert a.headers['cache-control']=='no-store'
        assert flow.start.call_args.args[0]!=UUID(body['request_key'])
    finally:del client.app.state.subscription_journey_factory


def test_unverified_or_legacy_account_cannot_enter_new_journey(client,preview,monkeypatch):
    from src.ai import db
    from src.ai.core.security import create_access_token
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    body=dict(request_key=str(uuid4()),plan_key='growth',period_code='monthly')
    token,_=create_access_token(preview['tenant'],preview['actor'],email_verified=False)
    assert client.post('/billing/trial-journeys',json=body,headers={'Authorization':'Bearer '+token}).status_code==403
    factory=Mock();client.app.state.subscription_journey_factory=factory
    connection=MagicMock();connection.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
    monkeypatch.setattr(db,'app_role_connection',lambda *a:connection)
    try:
        assert client.post('/billing/trial-journeys',json=body,headers=preview['headers']).status_code==409
        factory.assert_not_called()
    finally:del client.app.state.subscription_journey_factory


def test_no_installed_policy_services_or_activation_credentials():
    root=Path(__file__).resolve().parents[2]/'src'
    source=(root/'ai/billing/subscription_journey.py').read_text(encoding='utf-8')
    assert all(s not in source for s in ('os.environ','system_connection','SET ROLE','INSERT INTO','usage_ledger'))
    registry=(root/'infrastructure/database/migrations/20261208000000_subscription_journey_dispatch.sql').read_text()
    assert 'INSERT INTO public.billing_consent_policy_versions' not in registry
    assert 'GRANT EXECUTE ON FUNCTION public.billing_confirmation_' not in registry
    assert 'CREATE ROLE ceopro_journey_router NOLOGIN' in registry


def test_immutable_catalog_requires_exact_whole_bundle_digest():
    d=PolicyDocument(uuid4(),'SYNTHETIC','operator-v1','refund-v1',tuple((k,'synthetic') for k in (
        'agreement_reference','agreement_revision','language_tag','cancellation_reference','renewal_disclosure_reference',
        'trial_start_rule_reference','retention_policy_reference','approval_reference'))+(('agreement_digest','sha256:'+hashlib.sha256(b'SYNTHETIC').hexdigest()),))
    with pytest.raises(CollectionBlocked,match='digest'):ApprovedPolicyCatalog([d],pinned_bundle_digest='sha256:'+'0'*64)


@pytest.mark.parametrize('fact',['price','quantity','trial','customer','key','promotion','binding'])
def test_persisted_transport_cannot_substitute_frozen_commercial_scope(fact):
    from src.ai.billing.stripe_journey import StripeJourneyGateway
    from .test_stripe_verification import BINDING
    transport=Mock(binding=BINDING);g=StripeJourneyGateway(BINDING,transport,provider_consent_reviewed=True)
    b=dict(provider='stripe',environment='test',binding_id=BINDING.binding_id,merchant_account_id=BINDING.merchant_account_id)
    terms=dict(binding=b,tenant_id='tenant',provider_price_id='price_original',trial_duration_days=14)
    row=dict(reservation=dict(approved_terms=terms,binding_id=BINDING.binding_id,tenant_id='tenant',attempt_id='attempt',provider_price_id='price_original',trial_duration_days=14))
    request=g.prepare(row,C.ProviderReference('stripe','cus_original',binding=BINDING),{'trial_start_mode':'checkout_completion'},('https://keel.example.test/success','https://keel.example.test/cancel'))
    d=dict(attempt_id='attempt',tenant_id='tenant',binding_id=BINDING.binding_id,provider_customer_id='cus_original',request=request)
    g.check_request(d)
    p=request['transport']
    if fact=='price':p['line_items'][0]['price']='price_substituted'
    elif fact=='quantity':p['line_items'][0]['quantity']=2
    elif fact=='trial':p['subscription_data']['trial_period_days']=30
    elif fact=='customer':p['customer']='cus_wrong'
    elif fact=='key':request['idempotency_key']='replacement_key'
    elif fact=='promotion':p['discounts']=[{'coupon':'unapproved'}]
    else:d['binding_id']='new_default'
    with pytest.raises(CollectionBlocked):g.submit(d,authorize=Mock())
    transport.verify_namespace.assert_not_called();transport.checkout_create.assert_not_called()


def test_live_journey_adapter_is_refused_before_any_provider_work():
    from src.ai.billing.stripe_journey import StripeJourneyGateway
    live=C.GatewayBinding('stripe',C.GatewayEnvironment.LIVE,'merchant_live','binding_live')
    transport=Mock(binding=live)
    with pytest.raises(CollectionBlocked,match='live_journey_not_authorized'):
        StripeJourneyGateway(live,transport,provider_consent_reviewed=True,cancellation_supported=True)
    transport.verify_namespace.assert_not_called()


@pytest.mark.parametrize('problem',['wrong_secret','live_event','wrong_account','valid'])
def test_bound_webhook_decoder_checks_signature_and_original_namespace(problem):
    import time
    from src.ai.billing.journey_webhooks import BoundStripeJourneyWebhookDecoder
    from .test_contract import signed
    from .test_stripe_verification import BINDING
    secret='whsec_SYNTHETIC_JOURNEY_NOT_REAL'
    raw=dict(id='evt_synthetic_decoder',object='event',type='customer.subscription.updated',created=int(time.time()),
        livemode=problem=='live_event',data=dict(object=dict(id='sub_A',customer='cus_A',livemode=False)))
    if problem=='wrong_account':raw['account']='acct_unrelated'
    payload=json.dumps(raw).encode();signature=signed(payload,secret if problem!='wrong_secret' else 'whsec_OTHER_SYNTHETIC')
    decoder=BoundStripeJourneyWebhookDecoder(BINDING,secret)
    if problem=='valid':
        value=decoder.decode(payload,signature)
        assert value.binding==value.customer.binding==value.subscription.binding==BINDING
    else:
        with pytest.raises(C.InvalidPaymentWebhook):decoder.decode(payload,signature)


def test_payment_handoff_route_is_authenticated_default_off_and_no_store(client,preview,monkeypatch):
    from src.ai import db
    url='/billing/trial-journeys/'+preview['operation']+'/checkout'
    assert client.get(url).status_code==401
    assert client.get(url,headers=preview['headers']).status_code==404
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    connection=MagicMock();connection.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,)
    monkeypatch.setattr(db,'app_role_connection',lambda *a:connection)
    flow=Mock();flow.checkout_details.return_value=dict(operation_id=preview['operation'],provider='paddle',environment='test',transaction_id='txn_original')
    @contextmanager
    def factory(ctx):yield flow
    client.app.state.subscription_journey_factory=factory
    try:
        reply=client.get(url,headers=preview['headers'])
        assert reply.status_code==200 and reply.headers['cache-control']=='no-store'
        flow.checkout_details.assert_called_once_with(UUID(preview['operation']),'en')
        flow.advance.assert_not_called()
        assert client.get(url+'?language=unapproved',headers=preview['headers']).status_code==422
    finally:del client.app.state.subscription_journey_factory


@pytest.mark.parametrize('problem',['withdrawn','tenant','actor','revoked','forged_operation'])
def test_acceptance_cleanup_uses_authenticated_progress_after_withdrawal(client,preview,monkeypatch,problem):
    from copy import deepcopy
    from types import SimpleNamespace
    from src.ai import db
    from src.ai.billing.subscription_journey import SubscriptionJourney
    from src.ai.billing.authenticated_consent import ConsentCollection
    from src.ai.billing.recurring_consent import ConsentError
    from src.ai.billing.trial_coordinator import _binding
    from scripts.gateway_sandbox_acceptance import run
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    connection=MagicMock();connection.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,)
    monkeypatch.setattr(db,'app_role_connection',lambda *a:connection)
    row=deepcopy(preview['row']);binding=_binding(row)
    reservations=SimpleNamespace(load=Mock(return_value=row))
    consents=Mock();consents.read.return_value=C.CustomerPayload.freeze({'invalidation':{'reason':'withdrawn'}})
    flow=SubscriptionJourney.__new__(SubscriptionJourney)
    flow.collection=ConsentCollection(preview['tenant'],preview['actor'],reservations,consents)
    # No policy resolver exists: an accepted/non-withdrawn policy must never be
    # required just to read identity and compensate a withdrawn original journey.
    flow.dispatches=Mock();flow.dispatches.command.return_value=dict(presentation_id=str(uuid4()),provider_checkout_id='cs_original',expired_at=None,submitted_at=None)
    session=C.CheckoutSnapshot(C.ProviderReference('stripe','cs_original',binding=binding),C.CheckoutState.OPEN,C.PaymentState.UNKNOWN,
        C.ProviderReference('stripe','cus_original',binding=binding),None,None,preview['operation'],{},True)
    gateway=Mock(binding=binding);gateway.retrieve.return_value=session
    gateway.expire.side_effect=lambda s,d,authorize:authorize()
    flow.checkout_gateway=Mock(return_value=gateway)
    if problem=='tenant':row['reservation']['tenant_id']=str(uuid4())
    if problem=='actor':row['reservation']['started_by_user_id']=str(uuid4())
    if problem=='revoked':flow.dispatches.command.side_effect=ConsentError('consent_42501')
    @contextmanager
    def factory(ctx):
        assert (ctx.tenant_id,ctx.user_id)==(preview['tenant'],preview['actor'])
        yield flow
    client.app.state.subscription_journey_factory=factory
    from httpx import Response,Request,HTTPStatusError
    def local(method,path,**kwargs):
        response=client.request(method,path,headers=preview['headers'],**kwargs)
        # Starlette's installed TestClient uses httpx2; normalize responses to
        # the driver's actual httpx type while retaining the real ASGI status.
        return Response(response.status_code,json=response.json(),request=Request(method,'http://testserver'+path))
    http=SimpleNamespace(get=Mock(side_effect=lambda path:local('GET',path)),
        post=Mock(side_effect=lambda path,json:local('POST',path,json=json)))
    v=dict(base_url='http://127.0.0.1:19473',operation_id=str(uuid4()) if problem=='forged_operation' else preview['operation'],provider='stripe',environment='test',synthetic_business=True,
        binding_id=binding.binding_id,provider_operations_authorization='SYNTHETIC review',merchant_approval_reference='SYNTHETIC',legal_approval_reference='SYNTHETIC',policy_bundle_digest='sha256:'+'a'*64)
    try:
        url='/billing/trial-journeys/'+v['operation_id']+'/progress'
        assert client.get(url).status_code==401
        if problem=='withdrawn':
            assert run(v,'cleanup',http)==dict(state='withdrawn',reason='provider_checkout_expired')
            http.post.assert_called_once();gateway.expire.assert_called_once()
        else:
            with pytest.raises(HTTPStatusError) as error:run(v,'cleanup',http)
            assert error.value.response.status_code==(403 if problem=='revoked' else 409)
            http.post.assert_not_called();flow.checkout_gateway.assert_not_called()
        assert flow.collection.policies is None
    finally:del client.app.state.subscription_journey_factory
