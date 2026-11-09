"""Receipt acknowledgement is independent of B4 success; network-free fixtures."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime,timezone
import hashlib,hmac,json,uuid
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from src.ai.billing import payment_contracts as C
from src.ai.billing.journey_webhooks import JourneyWebhookReconciler
from src.ai.billing.paddle_gateway import PaddleWebhookDecoder,notification_digest
from src.ai.billing.trial_coordinator import observation_identity
from src.ai.routers.subscription_journey import router


def world(provider='paddle',*,conflict=True,withdrawn=False):
    operation=uuid.uuid4();oid=observation_identity(operation);tenant=str(uuid.uuid4())
    b=C.GatewayBinding(provider,C.GatewayEnvironment.TEST,'merchant','original_'+provider)
    ref=lambda value:C.ProviderReference(provider,value,binding=b)
    raw=dict(event_id='evt_original',event_type='transaction.completed',occurred_at='2026-11-09T00:00:00Z',
        notification_id='ntf_delivery',data=dict(id='txn_original',customer_id='ctm_original',subscription_id='sub_original'))
    event=C.VerifiedPaymentEvent(provider,'evt_original',C.PaymentEventKind.INVOICE_SETTLED if provider=='paddle' else C.PaymentEventKind.CHECKOUT_COMPLETED,
        datetime(2026,11,9,tzinfo=timezone.utc),ref('ctm_original'),ref('sub_original'),
        ref('txn_original') if provider=='stripe' else None,ref('txn_original') if provider=='paddle' else None,
        None,json.dumps(raw).encode(),raw,binding=b)
    flow=Mock();flow.collection._owned.return_value=dict(reservation=dict(state='pending',tenant_id=tenant,binding_id=b.binding_id,
        approved_terms=dict(binding=dict(provider=provider,environment='test',merchant_account_id='merchant',binding_id=b.binding_id))))
    flow.dispatches.command.return_value=dict(provider_customer_id='ctm_original',provider_checkout_id='txn_original',
        provider_subscription_id=None,presentation_id=str(uuid.uuid4()))
    durable=dict(operation_id=str(oid),has_conflict=conflict,state='reconciliation_required' if conflict else 'observed',last_observation_id=str(uuid.uuid4()))
    flow.observations.read.return_value=durable
    flow.collection.consents.read.return_value=C.CustomerPayload.freeze(dict(invalidation={'recorded_at':'SYNTHETIC'} if withdrawn else None))
    saved={}
    def capture(op,event_id,digest,occurred):
        receipt=dict(operation_id=str(oid),tenant_id=tenant,binding_id=b.binding_id,provider_event_id=event_id,body_digest=digest,
            occurred_at=occurred.isoformat(),authenticated_at=datetime.now(timezone.utc).isoformat(),receipt_id=str(uuid.uuid4()))
        if event_id in saved:
            if saved[event_id]['body_digest']!=digest:raise ValueError('Immutable event identity conflict')
            return saved[event_id]
        saved[event_id]=receipt;return receipt
    flow.observations.notification.side_effect=capture
    flow.reconcile.return_value=dict(state='pending',reason='provider_evidence_incomplete')
    @contextmanager
    def resolve(_):yield flow,operation,'en'
    return flow,event,JourneyWebhookReconciler(resolve),saved,durable


@pytest.mark.parametrize('provider',['paddle','stripe'])
@pytest.mark.parametrize('marker',['conflict','withdrawn'])
def test_durable_quarantine_acknowledges_receipt_without_business_effects(provider,marker):
    flow,event,handler,saved,_=world(provider,conflict=marker=='conflict',withdrawn=marker=='withdrawn')
    a=handler(event);b=handler(event)
    assert a==b and a['captured'] and a['confirmed'] is False and a['state']=='quarantined'
    assert a['event_id']==event.event_id and a['receipt_id']==saved[event.event_id]['receipt_id']
    assert len(saved)==1
    flow.reconcile.assert_not_called();flow.advance.assert_not_called()
    flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()


@pytest.mark.parametrize('reason',['provider_capabilities_unproved','recurring_readiness_unproved','trusted_confirmation_service_unavailable'])
def test_persisted_pending_evidence_is_acknowledged_without_confirming(reason):
    flow,event,handler,_,_=world(conflict=False)
    flow.reconcile.return_value=dict(state='blocked',reason=reason)
    response=handler(event)
    assert response['state']=='pending' and response['reason']==reason and response['confirmed'] is False


def test_new_durable_conflict_is_acknowledged_only_after_capture():
    flow,event,handler,saved,durable=world(conflict=False)
    def reconcile(*args):
        assert event.event_id in saved
        durable.update(has_conflict=True,state='reconciliation_required')
        return dict(state='conflict',reason='immutable_provider_history_conflict')
    flow.reconcile.side_effect=reconcile
    assert handler(event)['state']=='quarantined'
    flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()


@pytest.mark.parametrize('boundary',['revoked_authority','receipt_read_failure','confirmed_lifecycle_failure'])
def test_ack_never_bypasses_authorization_or_confirmed_lifecycle(boundary):
    flow,event,handler,saved,_=world()
    if boundary=='revoked_authority':flow.collection._owned.side_effect=ValueError('Current authority revoked')
    elif boundary=='receipt_read_failure':flow.observations.read.side_effect=RuntimeError('Restricted database unavailable')
    else:
        flow.collection._owned.return_value['reservation'].update(state='confirmed',confirmation_id=str(uuid.uuid4()))
        flow.lifecycle.reconcile.side_effect=RuntimeError('Trusted lifecycle pending')
    with pytest.raises((ValueError,RuntimeError)):handler(event)
    assert saved=={}


def test_failed_payment_event_stays_quarantined_without_lifecycle_application():
    flow,event,handler,_,_=world()
    raw=dict(event.raw_evidence,event_type='transaction.payment_failed')
    event=replace(event,kind=C.PaymentEventKind.INVOICE_FAILED,raw_evidence=raw)
    response=handler(event)
    assert response['state']=='quarantined' and response['confirmed'] is False
    flow.reconcile.assert_not_called();flow.lifecycle.reconcile.assert_not_called()


@pytest.mark.parametrize('problem',['capture_failed','commit_failed','missing_receipt','tenant','binding','operation','digest','event','time','unauthenticated_receipt',
    'transient_provider','reconcile_exception','no_observation','pending_not_persisted','unsupported','unknown_subscription','missing_customer'])
def test_no_ack_for_unpersisted_unresolved_or_misbound_processing(problem):
    flow,event,handler,_,durable=world(conflict=False)
    if problem in ('capture_failed','commit_failed'):flow.observations.notification.side_effect=RuntimeError(problem)
    elif problem in ('missing_receipt','tenant','binding','operation','digest','event','time','unauthenticated_receipt'):
        original=flow.observations.notification.side_effect
        def malformed(*args):
            row=original(*args)
            if problem=='missing_receipt':return None
            key={'tenant':'tenant_id','binding':'binding_id','operation':'operation_id','digest':'body_digest','event':'provider_event_id','time':'occurred_at','unauthenticated_receipt':'authenticated_at'}[problem]
            row[key]='2026-11-08T00:00:00Z' if problem=='time' else (None if problem=='unauthenticated_receipt' else 'foreign')
            return row
        flow.observations.notification.side_effect=malformed
    elif problem=='reconcile_exception':flow.reconcile.side_effect=RuntimeError('Provider lookup failed')
    elif problem in ('no_observation','pending_not_persisted'):
        flow.reconcile.return_value=dict(state='blocked',reason='provider_capabilities_unproved')
        if problem=='no_observation':durable['last_observation_id']=None
        else:durable['state']='prepared'
    elif problem=='unsupported':flow.reconcile.return_value=dict(state='pending',reason='provider_evidence_incomplete')
    elif problem=='unknown_subscription':
        event=replace(event,invoice=None,kind=C.PaymentEventKind.SUBSCRIPTION_CHANGED)
        durable['has_conflict']=True;flow.reconcile.return_value=dict(state='blocked',reason='provider_capabilities_unproved')
    elif problem=='missing_customer':event=replace(event,customer=None)
    with pytest.raises((ValueError,RuntimeError,TypeError)):handler(event)
    flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()


@pytest.mark.parametrize('identity',['customer','checkout','subscription','binding','tenant_metadata','operation_metadata'])
def test_foreign_positive_identity_never_receives_success(identity):
    flow,event,handler,saved,_=world()
    ref=lambda v:C.ProviderReference('paddle',v,binding=event.binding)
    if identity=='customer':event=replace(event,customer=ref('ctm_foreign'))
    elif identity=='checkout':event=replace(event,invoice=ref('txn_foreign'))
    elif identity=='subscription':
        flow.dispatches.command.return_value['provider_subscription_id']='sub_original'
        event=replace(event,subscription=ref('sub_foreign'))
    elif identity=='binding':
        b=C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,'other','other')
        event=replace(event,binding=b,customer=C.ProviderReference('paddle','ctm_original',binding=b),
            invoice=C.ProviderReference('paddle','txn_original',binding=b),subscription=C.ProviderReference('paddle','sub_original',binding=b))
    else:
        raw=dict(event.raw_evidence);raw['data']=dict(raw['data'],custom_data={
            'tenant_id' if identity=='tenant_metadata' else 'keel_journey_operation':'foreign'})
        event=replace(event,raw_evidence=raw)
    with pytest.raises(ValueError):handler(event)
    assert saved=={}


@pytest.mark.parametrize('problem',['valid','tampered','malformed','stale','unsigned','receipt_failure','changed_event'])
def test_signed_http_acknowledgement_contract(monkeypatch,problem):
    flow,event,handler,saved,_=world();app=FastAPI();app.include_router(router,prefix='/billing')
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    app.state.bound_journey_webhooks={'paddle':(PaddleWebhookDecoder(event.binding,'SYNTHETIC',clock=lambda:1000),handler)}
    raw=event.raw_payload
    def sign(body,ts=1000):return 'ts='+str(ts)+';h1='+hmac.new(b'SYNTHETIC',str(ts).encode()+b':'+body,hashlib.sha256).hexdigest()
    if problem=='receipt_failure':flow.observations.notification.side_effect=RuntimeError('Commit failed')
    with TestClient(app) as client:
        signature=sign(raw,900 if problem=='stale' else 1000)
        if problem=='tampered':raw+=b' '
        if problem=='malformed':raw=b'{';signature=sign(raw)
        headers={} if problem=='unsigned' else {'Paddle-Signature':signature}
        response=client.post('/billing/trial-journeys/webhook/paddle',content=raw,headers=headers)
        expected=500 if problem=='receipt_failure' else 400 if problem in ('tampered','malformed','stale','unsigned') else 200
        assert response.status_code==expected
        if expected==200:
            assert response.json()['received'] and response.json()['confirmed'] is False
            if problem=='changed_event':
                raw=json.loads(raw);raw['data']['currency_code']='EUR';raw=json.dumps(raw).encode()
                assert client.post('/billing/trial-journeys/webhook/paddle',content=raw,headers={'Paddle-Signature':sign(raw)}).status_code==500
            else:
                retry=client.post('/billing/trial-journeys/webhook/paddle',content=raw,headers=headers)
                assert retry.json()==response.json() and len(saved)==1
        # The Paddle decoder is never usable through Stripe's endpoint.
        assert client.post('/billing/trial-journeys/webhook/stripe',content=raw,headers=headers).status_code==503
