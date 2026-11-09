"""Network-free follow-up receipts must never replace original trial evidence."""
from dataclasses import replace
import json
import pytest
from src.ai.billing import payment_contracts as C
from .test_journey_acknowledgement import world

def followup(*,conflict=False,withdrawn=False,failed=False):
    flow,event,handler,saved,durable=world(conflict=conflict,withdrawn=withdrawn)
    flow.dispatches.command.return_value['provider_subscription_id']='sub_original'
    raw=dict(event.raw_evidence,event_type='transaction.payment_failed' if failed else 'transaction.completed')
    raw['data']=dict(raw['data'],id='txn_subsequent',origin='subscription_update')
    event=replace(event,kind=C.PaymentEventKind.INVOICE_FAILED if failed else C.PaymentEventKind.INVOICE_SETTLED,
        invoice=C.ProviderReference('paddle','txn_subsequent',binding=event.binding),raw_evidence=raw,raw_payload=json.dumps(raw).encode())
    return flow,event,handler,saved,durable

@pytest.mark.parametrize('failed',[False,True])
@pytest.mark.parametrize('origin',['subscription_update','subscription_recurring'])
@pytest.mark.parametrize('marker',['pending','conflict','withdrawn'])
def test_exact_followup_is_durably_quarantined_without_reconciliation(failed,origin,marker):
    flow,event,handler,saved,durable=followup(failed=failed,conflict=marker=='conflict',withdrawn=marker=='withdrawn')
    raw=dict(event.raw_evidence);raw['data']=dict(raw['data'],origin=origin);event=replace(event,raw_evidence=raw)
    original=durable.copy();a=handler(event);assert handler(event)==a
    assert a['captured'] is True and a['confirmed'] is False and a['state']=='quarantined' and len(saved)==1
    assert a['reason']=={'pending':'unconfirmed_subscription_lifecycle','conflict':'immutable_provider_history_conflict','withdrawn':'consent_invalidated'}[marker]
    assert durable==original and flow.dispatches.command.return_value['provider_checkout_id']=='txn_original'
    flow.reconcile.assert_not_called();flow.lifecycle.reconcile.assert_not_called();flow.observations.record.assert_not_called()
    flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()

@pytest.mark.parametrize('problem',['unknown_subscription','foreign_subscription','foreign_customer','binding','tenant','operation','origin','signed_transaction','signed_customer','signed_subscription','no_original_evidence','receipt_failure','receipt_digest','changed_event','confirmed'])
def test_followup_exception_never_accepts_unbound_or_unpersisted_evidence(problem):
    flow,event,handler,saved,durable=followup()
    if problem=='unknown_subscription':flow.dispatches.command.return_value['provider_subscription_id']=None
    elif problem=='foreign_subscription':event=replace(event,subscription=C.ProviderReference('paddle','sub_foreign',binding=event.binding))
    elif problem=='foreign_customer':event=replace(event,customer=C.ProviderReference('paddle','ctm_foreign',binding=event.binding))
    elif problem=='binding':
        binding=replace(event.binding,binding_id='foreign')
        event=replace(event,binding=binding,customer=replace(event.customer,binding=binding),
            subscription=replace(event.subscription,binding=binding),invoice=replace(event.invoice,binding=binding))
    elif problem=='no_original_evidence':durable['last_observation_id']=None
    elif problem=='receipt_failure':flow.observations.notification.side_effect=RuntimeError('Commit failed')
    elif problem=='receipt_digest':
        capture=flow.observations.notification.side_effect
        def malformed(*a):return dict(capture(*a),body_digest='foreign')
        flow.observations.notification.side_effect=malformed
    elif problem=='confirmed':
        flow.collection._owned.return_value['reservation'].update(state='confirmed',confirmation_id='confirmed')
        flow.lifecycle.reconcile.side_effect=ValueError('No trusted lifecycle installed')
    elif problem=='changed_event':
        handler(event);raw=dict(event.raw_evidence);raw['data']=dict(raw['data'],currency_code='EUR');event=replace(event,raw_evidence=raw)
    else:
        raw=dict(event.raw_evidence);raw['data']=dict(raw['data'])
        if problem in ('tenant','operation'):raw['data']['custom_data']={'tenant_id' if problem=='tenant' else 'keel_journey_operation':'foreign'}
        else:raw['data'][{'origin':'origin','signed_transaction':'id','signed_customer':'customer_id','signed_subscription':'subscription_id'}[problem]]='foreign'
        event=replace(event,raw_evidence=raw)
    with pytest.raises((ValueError,RuntimeError)):handler(event)
    flow.reconcile.assert_not_called();flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()
