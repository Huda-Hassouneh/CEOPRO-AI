"""Network-free regression for actual Paddle omission and sticky B3 conflicts."""
from unittest.mock import Mock,patch
from decimal import Decimal
from types import SimpleNamespace
import uuid
import pytest
from src.ai.billing import payment_contracts as C
from src.ai.billing.subscription_journey import SubscriptionJourney
from src.ai.billing.paddle_gateway import PaddleVerificationGateway
from .test_multi_gateway_adapters import B,ref,PaddleReader,paddle_request,paddle_event,NOW


@pytest.mark.parametrize('relation',['omitted','empty','null','object','nonempty'])
def test_requested_adjustments_relation_uses_documented_omission_only(relation):
    reader=PaddleReader();calls=[];original=reader.request
    if relation=='omitted':del reader.t['adjustments']
    elif relation=='null':reader.t['adjustments']=None
    elif relation=='object':reader.t['adjustments']={}
    elif relation=='nonempty':reader.t['adjustments']=[dict(action='refund')]
    def request(method,path,body=None,*,params=None):
        calls.append((method,path,params));return original(method,path,body,params=params)
    reader.request=request
    observed=PaddleVerificationGateway(B,reader,clock=lambda:NOW).observe_subscription(paddle_request(),event=paddle_event())
    assert ('GET','/transactions/txn_test',{'include':'adjustments'}) in calls
    if relation in ('omitted','empty'):
        assert observed.outcome is C.VerificationOutcome.VERIFIED
        assert observed.settlement.amount_paid==C.Money(Decimal('59'),'USD')
    else:assert observed.outcome is not C.VerificationOutcome.VERIFIED and observed.settlement is None


def test_conflicted_journey_records_fresh_evidence_but_cannot_promote_it():
    flow=SubscriptionJourney.__new__(SubscriptionJourney)
    row=dict(reservation=dict(binding_id=B.binding_id,approved_terms=dict(binding=dict(provider='paddle',environment='test',
        merchant_account_id=B.merchant_account_id,binding_id=B.binding_id))))
    flow.collection=SimpleNamespace(tenant='tenant',consents=Mock())
    flow._accepted=Mock(return_value=(row,dict(acceptance_id=str(uuid.uuid4())),{}))
    request=SimpleNamespace(binding=B,tenant_id='tenant')
    flow.observations=Mock();flow.observations.read.return_value=dict(has_conflict=True)
    observed=SimpleNamespace(request=request,outcome=C.VerificationOutcome.PENDING,
        provenance=SimpleNamespace(source=C.ObservationSource.AUTHORITATIVE_LOOKUP,stored_observation_id=None))
    observer=Mock(binding=B);observer.observe_trial_checkout.return_value=observed
    flow.observer_for_binding=Mock(return_value=observer)
    flow.dispatches=Mock();flow.attestor=Mock();flow.confirmer=Mock()
    with patch('src.ai.billing.subscription_journey.V.trial_request',return_value=request):
        result=flow.reconcile(uuid.uuid4(),'en')
    assert result['state']=='conflict' and result['reason']=='immutable_provider_history_conflict'
    flow.observations.record.assert_called_once()
    assert flow.observations.record.call_args.args[2] is observed
    flow.dispatches.command.assert_not_called()
    flow.attestor.attest.assert_not_called();flow.confirmer.confirm.assert_not_called()
