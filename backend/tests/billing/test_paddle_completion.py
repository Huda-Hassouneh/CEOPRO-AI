"""Synthetic Customer/Checkout API proof. No provider acceptance."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import uuid
import pytest
from src.ai.billing import payment_contracts as C
from src.ai.billing.paddle_gateway import PaddleDurableCustomerGateway,BoundPaddleTransport,PaddleJourneyGateway
from .test_multi_gateway_adapters import B,ref

class CustomerReader:
    api_version='1'
    def __init__(self,binding=B):self.binding=binding;self.calls=[];self.values=[];self.lost=False;self.pages=None
    def verify_namespace(self):pass
    def request(self,method,path,body=None,*,params=None):
        self.calls.append((method,path,deepcopy(body),deepcopy(params)))
        if method=='POST':
            value=dict(deepcopy(body),id='ctm_'+uuid.uuid4().hex,status='active');self.values.append(value)
            if self.lost:raise TimeoutError('synthetic lost response')
            return deepcopy(value)
        if path=='/customers':
            if self.pages is not None:return deepcopy(self.pages[1 if params.get('after') else 0])
            return dict(items=deepcopy(self.values),has_more=False)
        return deepcopy(next(v for v in self.values if v['id']==path.rsplit('/',1)[1]))


def intent(binding=B):return C.CustomerIntent('tenant',str(uuid.uuid4()),'original',binding,'synthetic@example.test','Synthetic business')

def receipt(r,deadline):
    return dict(state='submitted',dispatch_count=1,operation_id=r.operation_id,tenant_id=r.tenant_id,
        binding=dict(provider='paddle',environment='test',merchant_account_id=r.binding.merchant_account_id,binding_id=r.binding.binding_id),
        idempotency_key=r.idempotency_key,transport_request=r.transport.canonical.decode(),replay_deadline=deadline.isoformat())


def test_customer_first_send_and_lost_reply_discovery_preserve_frozen_lineage():
    t=CustomerReader();g=PaddleDurableCustomerGateway(B,t,merchant_reviewed=True);r=g.prepare_customer(intent())
    assert t.calls==[] and r.replay_support is C.CapabilityState.UNKNOWN
    deadline=datetime.now(timezone.utc)+timedelta(seconds=30)
    t.lost=True
    with pytest.raises(TimeoutError):g.submit_customer(r,deadline=deadline,authorize=lambda:receipt(r,deadline))
    found=g.recover_customer(r)
    assert found.status is C.CustomerRecoveryStatus.MATCH and found.snapshot.reference.opaque_id==t.values[0]['id']
    assert sum(c[0]=='POST' for c in t.calls)==1
    t.values=[]
    assert g.recover_customer(r).status is C.CustomerRecoveryStatus.INCONCLUSIVE
    assert sum(c[0]=='POST' for c in t.calls)==1


@pytest.mark.parametrize('problem',['scope','terms','repeated','expired','approval','namespace','api'])
def test_customer_refuses_forged_or_replayed_authority_before_post(problem):
    t=CustomerReader();g=PaddleDurableCustomerGateway(B,t,merchant_reviewed=problem!='approval');r=g.prepare_customer(intent())
    end=datetime.now(timezone.utc)+timedelta(seconds=30);a=receipt(r,end)
    if problem=='scope':a['binding']['binding_id']='foreign'
    if problem=='terms':a['transport_request']='{}'
    if problem=='repeated':a['dispatch_count']=2
    if problem=='expired':end=datetime.now(timezone.utc)-timedelta(seconds=1)
    if problem=='namespace':t.binding=replace(B,binding_id='foreign')
    if problem=='api':t.api_version='2'
    with pytest.raises(ValueError):g.submit_customer(r,deadline=end,authorize=lambda:a)
    assert not any(c[0]=='POST' for c in t.calls)


@pytest.mark.parametrize('problem',['duplicate','foreign','archived','empty','later_page','truncated','cursor_loop'])
def test_customer_discovery_never_guesses_tenant_or_noncreation(problem):
    t=CustomerReader();g=PaddleDurableCustomerGateway(B,t,merchant_reviewed=True);r=g.prepare_customer(intent())
    end=datetime.now(timezone.utc)+timedelta(seconds=30)
    g.submit_customer(r,deadline=end,authorize=lambda:receipt(r,end));v=t.values[0]
    if problem=='duplicate':t.values.append(dict(v,id='ctm_other'))
    if problem=='foreign':v['custom_data']['tenant_id']='foreign'
    if problem=='archived':v['status']='archived'
    if problem=='empty':t.values=[]
    if problem=='later_page':t.pages=[dict(items=[dict(v,id='ctm_unrelated',custom_data={})],has_more=True),dict(items=[v],has_more=False)]
    if problem=='truncated':t.pages=[dict(items=[],has_more=True)]
    if problem=='cursor_loop':t.pages=[dict(items=[dict(v,id='ctm_unrelated',custom_data={})],has_more=True)]*2
    if problem in ('foreign','archived','truncated','cursor_loop'):
        with pytest.raises(ValueError):g.recover_customer(r)
    else:
        found=g.recover_customer(r)
        assert found.status is {'duplicate':C.CustomerRecoveryStatus.CONFLICT,'empty':C.CustomerRecoveryStatus.INCONCLUSIVE,'later_page':C.CustomerRecoveryStatus.MATCH}[problem]
    assert sum(c[0]=='POST' for c in t.calls)==1


def test_transport_accepts_documented_created_response_and_scoped_paginated_lists():
    responses=iter([dict(data={'id':'ctm_created'}),dict(data=[],meta=dict(pagination=dict(has_more=False)))])
    calls=[]
    def request(*a,**kw):calls.append((a,kw));return SimpleNamespace(status_code=201 if len(calls)==1 else 200,json=lambda:next(responses))
    t=BoundPaddleTransport(B,'pdl_sdbx_apikey_SYNTHETIC',client=SimpleNamespace(request=request))
    assert t.request('POST','/customers',{})=={'id':'ctm_created'}
    assert t.request('GET','/customers',params={'per_page':200})==dict(items=[],has_more=False)
    assert all(v[1]['follow_redirects'] is False for v in calls)
    with pytest.raises(ValueError):t.request('GET','/customers',params={'url':'https://foreign'})


@pytest.mark.parametrize('count',[0,1,2])
def test_checkout_discovery_rereads_unique_original_transaction_without_post(count):
    from unittest.mock import Mock
    t=CustomerReader();g=PaddleJourneyGateway(B,t)
    original=t.request
    def read(method,path,body=None,*,params=None):
        if path=='/transactions':
            assert params['customer_id']=='ctm_original'
            return dict(items=[dict(id='txn_'+str(i),custom_data={'keel_journey_operation':'operation'}) for i in range(count)],has_more=False)
        assert path=='/transactions/txn_0' and method=='GET'
        return dict(id='txn_0')
    t.request=read;g._snapshot=Mock(return_value='validated original snapshot')
    result=g.recover(dict(attempt_id='operation',provider_customer_id='ctm_original',provider_checkout_id=None))
    assert result==('validated original snapshot' if count==1 else None)
    assert g._snapshot.call_count==(1 if count==1 else 0)


@pytest.mark.parametrize('problem',['valid','attached_card','foreign_customer','foreign_subscription','wrong_terms','wrong_trial','paid_initial'])
def test_paddle_trial_facts_do_not_fabricate_reusable_recurring_authority(problem):
    from decimal import Decimal
    from .test_multi_gateway_adapters import PaddleReader,NOW
    from src.ai.billing.paddle_gateway import PaddleVerificationGateway
    t=PaddleReader();t.s['status']='trialing';start=NOW;end=NOW+timedelta(days=14)
    t.s['items'][0]['trial_dates']=dict(starts_at=start.isoformat(),ends_at=end.isoformat())
    terms=C.ObservedRecurringTerms(C.Money(Decimal('59'),'USD'),1,1,ref('pri_test'))
    r=C.TrialObservationRequest(C.ApprovedTrialTerms('tenant','growth','catalog',1,'USD',14,B),'sha256:'+'a'*64,
        'reservation','operation',ref('txn_test'),ref('ctm_test'),'customer_operation',ref('sub_test'),expected_terms=terms)
    t.t.update(custom_data=dict(tenant_id='tenant',keel_journey_operation='operation'),origin='api')
    for key in t.t['details']['totals']:t.t['details']['totals'][key]='0'
    if problem=='attached_card':t.s['default_payment_method_id']='paymtd_attached_only'
    if problem=='foreign_customer':t.t['customer_id']='foreign'
    if problem=='foreign_subscription':t.t['subscription_id']='foreign'
    if problem=='wrong_terms':t.s['items'][0]['price']['unit_price']['amount']='6000'
    if problem=='wrong_trial':t.s['items'][0]['trial_dates']['ends_at']=(end+timedelta(days=1)).isoformat()
    if problem=='paid_initial':t.t['details']['totals']['total']='1'
    o=PaddleVerificationGateway(B,t,clock=lambda:NOW).observe_trial_checkout(r)
    assert o.outcome is not C.VerificationOutcome.VERIFIED and not o.capabilities.supports_card_backed_trial()
    if problem in ('valid','attached_card'):
        assert o.outcome is C.VerificationOutcome.PENDING and o.subscription==ref('sub_test') and o.trial.ends_at==end
        assert o.recurring_authorization.readiness is C.PaymentMethodReadiness.UNKNOWN
    else:assert o.outcome is C.VerificationOutcome.CONFLICT and o.subscription is None


@pytest.mark.parametrize('problem',['valid','remote','live','approval','binding','provider','policy'])
def test_acceptance_driver_is_approval_gated_and_checks_original_server_scope(problem):
    from scripts.gateway_sandbox_acceptance import run
    from unittest.mock import Mock
    manifest=dict(base_url='http://127.0.0.1:19473',operation_id=str(uuid.uuid4()),provider='paddle',environment='test',synthetic_business=True,
        binding_id='original',provider_operations_authorization='SYNTHETIC review',merchant_approval_reference='SYNTHETIC review',legal_approval_reference='SYNTHETIC review',policy_bundle_digest='sha256:'+'a'*64)
    if problem=='remote':manifest['base_url']='https://production.example.test'
    if problem=='live':manifest['environment']='live'
    if problem=='approval':manifest['legal_approval_reference']=''
    c=Mock();c.get.return_value.json.return_value=dict(operation_id=manifest['operation_id'],provider='stripe' if problem=='provider' else 'paddle',environment='test',binding_id='foreign' if problem=='binding' else 'original',policy_bundle_digest='sha256:'+('b' if problem=='policy' else 'a')*64)
    c.post.return_value.json.return_value=dict(state='pending',reason='provider_evidence_incomplete',private='must not print')
    if problem=='valid':assert run(manifest,'advance',c)==dict(state='pending',reason='provider_evidence_incomplete')
    else:
        with pytest.raises(ValueError):run(manifest,'advance',c)
        c.post.assert_not_called()
    if problem in ('remote','live','approval'):c.get.assert_not_called()


def test_acceptance_handoff_exposes_only_server_pinned_policy_digest():
    from src.ai.billing.subscription_journey import SubscriptionJourney
    from unittest.mock import Mock
    flow=SubscriptionJourney.__new__(SubscriptionJourney)
    flow.collection=SimpleNamespace(policies=SimpleNamespace(bundle_digest='sha256:'+'a'*64))
    row={'reservation':{'state':'pending','binding_id':B.binding_id,'approved_terms':{'binding':dict(provider='paddle',environment='test',merchant_account_id=B.merchant_account_id,binding_id=B.binding_id)}}}
    flow._accepted=Mock(return_value=(row,{'acceptance_id':'accepted'},{}))
    flow.dispatches=Mock();flow.dispatches.command.return_value=None
    result=flow.checkout_details(uuid.uuid4(),'en')
    assert result['policy_bundle_digest']=='sha256:'+'a'*64 and result['transaction_id'] is None
    flow.dispatches.command.assert_called_once()


@pytest.mark.parametrize('action',['cleanup','cancellation'])
@pytest.mark.parametrize('problem',['provider','binding','environment','operation','missing','revoked','valid_withdrawn'])
def test_cleanup_and_cancellation_check_authenticated_original_scope_before_post(action,problem):
    from scripts.gateway_sandbox_acceptance import run
    from unittest.mock import Mock
    v=dict(base_url='http://127.0.0.1:19473',operation_id=str(uuid.uuid4()),provider='paddle',environment='test',synthetic_business=True,
        binding_id='original',provider_operations_authorization='SYNTHETIC review',merchant_approval_reference='SYNTHETIC',legal_approval_reference='SYNTHETIC',policy_bundle_digest='sha256:'+'a'*64)
    c=Mock();scope=dict(operation_id=v['operation_id'],provider='paddle',environment='test',binding_id='original',state='pending')
    # The protected progress scope deliberately contains neither approved policy
    # nor accepted-consent evidence. Withdrawal cannot prevent safe cleanup.
    if problem=='provider':scope['provider']='stripe'
    if problem=='binding':scope['binding_id']='foreign'
    if problem=='environment':scope['environment']='live'
    if problem=='operation':scope['operation_id']=str(uuid.uuid4())
    if problem=='missing':scope={}
    if problem=='revoked':c.get.return_value.raise_for_status.side_effect=ValueError('Current billing authority revoked')
    c.get.return_value.json.return_value=scope
    c.post.return_value.json.return_value=dict(state='withdrawn',reason='provider_checkout_expired')
    if problem=='valid_withdrawn':
        assert run(v,action,c)==dict(state='withdrawn',reason='provider_checkout_expired')
        c.post.assert_called_once_with('/billing/trial-journeys/'+v['operation_id']+'/'+action,json={})
    else:
        with pytest.raises(ValueError):run(v,action,c)
        c.post.assert_not_called()
    c.get.assert_called_once_with('/billing/trial-journeys/'+v['operation_id']+'/progress')
