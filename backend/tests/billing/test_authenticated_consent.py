"""Synthetic approval source only; no customer/provider/legal acceptance."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from unittest.mock import Mock
from uuid import UUID, uuid4
import pytest
from src.ai.billing import authenticated_consent as A, payment_contracts as C
from src.ai.billing import recurring_consent as R
from .test_trial_journey_preview import preview
from .test_trial_coordinator import scenario


@pytest.fixture
def collection(scenario):
    s = scenario
    s.row['reservation']['trial_duration_days'] = 14
    s.row['checkout']['tenant_id'] = str(s.tenant)
    values = dict(agreement_reference='SYNTHETIC-NOT-LEGAL', agreement_revision='synthetic-v1',language_tag='en',
        agreement_digest='sha256:'+hashlib.sha256(b'SYNTHETIC-NOT-LEGAL').hexdigest(),
        cancellation_reference='synthetic',renewal_disclosure_reference='synthetic',trial_start_rule_reference='synthetic',
        retention_policy_reference='synthetic',approval_reference='ISOLATED TEST ONLY')
    document = A.PolicyDocument(s.policy,'SYNTHETIC-NOT-LEGAL','synthetic-operator','synthetic-refund',tuple(sorted(values.items())),trial_start_mode='provider_confirmed_trial_start')
    registry = dict(values,policy_id=str(s.policy),status='approved')
    presented = dict(s.presentation, policy_id=str(s.policy), terms_digest='sha256:'+'a'*64,
        challenge='x'*72, expires_at='synthetic-db-expiry', policy=registry)
    import uuid
    identity=uuid.uuid5(s.identity, 'consent-presentation:'+str(s.policy))
    s.consents.present.return_value = C.CustomerPayload.freeze(dict(presented,presentation_id=str(identity)))
    s.consents.read.return_value = C.CustomerPayload.freeze(dict(presentation=presented,policy=registry,acceptance=None,invalidation=None))
    s.consents.accept.return_value = C.CustomerPayload.freeze(dict(s.accepted, accepted_at='database-clock'))
    s.consents.invalidate.return_value = C.CustomerPayload.freeze(dict(recorded_at='database-clock'))
    flow = A.ConsentCollection(str(s.tenant),str(s.actor),s.repository,s.consents,
        policies=Mock(return_value=document),business_eligibility=Mock(return_value=True))
    return s, flow, document, presented


def test_missing_catalog_never_calls_protected_present_or_accept(collection):
    s,flow,_,_ = collection;flow.policies = None
    assert flow.prepare(s.identity,'en')['missing_approvals'] == list(A.MISSING_APPROVALS)
    with pytest.raises(A.CollectionBlocked,match='policy_not_approved'): flow.present(s.identity,'en')
    with pytest.raises(A.CollectionBlocked,match='policy_not_approved'): flow.accept(s.identity,'en',s.policy,'x'*72,True)
    s.consents.present.assert_not_called();s.consents.accept.assert_not_called();s.consents.read.assert_not_called()


def test_explicit_synthetic_presentation_acceptance_and_withdrawal_delegate_original_ids(collection):
    s,flow,_,_ = collection
    assert flow.prepare(s.identity,'en')['state']=='prepared'
    presented = flow.present(s.identity,'en')
    assert presented['challenge']=='x'*72
    assert flow.accept(s.identity,'en',s.policy,'x'*72,True)['accepted_at']=='database-clock'
    identity = s.consents.accept.call_args.args[0]
    assert identity.terms_digest=='sha256:'+'a'*64
    assert flow.withdraw(s.identity,s.policy)['state']=='withdrawn'
    s.consents.invalidate.assert_called_once_with(s.policy,R.ConsentState.WITHDRAWN)


@pytest.mark.parametrize('checked',[False,1,'true',None])
def test_unchecked_or_fabricated_boolean_is_not_authorization(collection,checked):
    s,flow,_,_ = collection
    with pytest.raises(A.CollectionBlocked,match='unchecked'): flow.accept(s.identity,'en',s.policy,'x'*72,checked)
    s.consents.read.assert_not_called();s.consents.accept.assert_not_called()


@pytest.mark.parametrize('change',['actor','tenant','binding','terms','invalidation','revision'])
def test_protected_snapshot_conflicts_fail_closed(collection,change):
    s,flow,_,presented = collection
    value = s.consents.read.return_value.unpack()
    if change=='invalidation': value['invalidation']={'reason':'withdrawn'}
    elif change=='revision': value['policy']['agreement_revision']='different'
    elif change=='terms': value['presentation']['approved_terms']['currency']='EUR'
    elif change=='binding': value['presentation']['binding_id']='other'
    else: value['presentation']['actor_id' if change=='actor' else 'tenant_id']=str(uuid4())
    s.consents.read.return_value=C.CustomerPayload.freeze(value)
    with pytest.raises(A.CollectionBlocked): flow.accept(s.identity,'en',s.policy,'x'*72,True)
    s.consents.accept.assert_not_called()


def test_business_scope_and_language_are_not_guessed(collection):
    s,flow,_,_ = collection
    flow.business_eligibility.return_value=False
    assert flow.prepare(s.identity,'en')['blocker']=='business_eligibility_required'
    flow.business_eligibility.return_value=True
    with pytest.raises(A.CollectionBlocked,match='policy_version'): flow.present(s.identity,'ar')
    s.row['reservation']['trial_duration_days']=7
    with pytest.raises(A.CollectionBlocked,match='business_eligibility'):flow.present(s.identity,'en')


@pytest.mark.parametrize('mode',[None,'checkout_completion','browser_redirect'])
def test_consent_requires_provider_confirmed_trial_start_rule(collection,mode):
    from dataclasses import replace
    s,flow,document,_=collection
    flow.policies.return_value=replace(document,trial_start_mode=mode)
    assert flow.prepare(s.identity,'en')['blocker']=='approved_trial_start_rule_required'
    with pytest.raises(A.CollectionBlocked,match='approved_trial_start_rule_required'):
        flow.present(s.identity,'en')
    s.consents.present.assert_not_called()


@pytest.mark.parametrize('kind',['expiry','replay','revoked'])
def test_a1_refusals_are_preserved(collection,kind):
    s,flow,_,_ = collection
    s.consents.accept.side_effect=R.ConsentError('consent_'+('42501' if kind=='revoked' else '22023'))
    with pytest.raises(R.ConsentError):flow.accept(s.identity,'en',s.policy,'x'*72,True)


def url(p,suffix): return '/billing/trial-journeys/'+p['operation']+'/consent/'+suffix


def test_http_preparation_has_missing_approvals_and_frozen_terms(client,preview,monkeypatch):
    monkeypatch.setenv('RECURRING_CONSENT_ENABLED','true')
    result=client.get(url(preview,'preparation'),headers=preview['headers'])
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    value=result.json();assert value['state']=='pending_policy'
    assert value['agreement_text'] is None and value['policy_revision'] is None
    assert value['commercial_terms']['renewal_amount']=='12345678901234.123456789'
    assert value['provider_consent']=='unresolved_provider_requirement'
    choice=dict(language='en',presentation_id=str(uuid4()),challenge='x'*72,checked=True)
    assert client.post(url(preview,'accept'),json=choice,headers=preview['headers']).status_code==409
    assert client.post(url(preview,'present'),json={'language':'en'},headers=preview['headers']).status_code==409


def test_disabled_unauthenticated_and_unauthorized_consent_are_hidden(client,preview,monkeypatch):
    monkeypatch.delenv('RECURRING_CONSENT_ENABLED',raising=False)
    assert client.get(url(preview,'preparation')).status_code==401
    assert client.get(url(preview,'preparation'),headers=preview['headers']).status_code==404
    monkeypatch.setenv('RECURRING_CONSENT_ENABLED','true');preview['load'].side_effect=lambda _:None
    assert client.get(url(preview,'preparation'),headers=preview['headers']).status_code==404


def test_request_cannot_supply_actor_terms_timestamp_or_nonboolean_consent(client,preview,monkeypatch):
    monkeypatch.setenv('RECURRING_CONSENT_ENABLED','true')
    base=dict(language='en',presentation_id=str(uuid4()),challenge='x'*72,checked=True)
    for field,value in [('actor_id',str(uuid4())),('accepted_at','now'),('approved_amount','0'),('checked','true')]:
        response=client.post(url(preview,'accept'),json=dict(base,**{field:value}),headers=preview['headers'])
        assert response.status_code==422
    assert client.post(url(preview,'accept'),json=dict(base,checked=False),headers=preview['headers']).status_code==409


def test_injected_server_boundary_receives_authenticated_context_and_closes(client,preview,monkeypatch):
    monkeypatch.setenv('RECURRING_CONSENT_ENABLED','true');flow=Mock()
    flow.accept.return_value={'state':'accepted','accepted_at':'synthetic-db-clock'}
    closed=[]
    @contextmanager
    def factory(ctx):
        assert (ctx.tenant_id,ctx.user_id)==(preview['tenant'],preview['actor'])
        try: yield flow
        finally: closed.append(True)
    client.app.state.recurring_consent_factory=factory
    response=client.post(url(preview,'accept'),json=dict(language='en',presentation_id=str(uuid4()),challenge='x'*72,checked=True),headers=preview['headers'])
    assert response.status_code==200 and closed==[True]
    del client.app.state.recurring_consent_factory


def test_revoked_billing_principal_and_factory_errors_fail_closed(client,preview,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv('RECURRING_CONSENT_ENABLED','true')
    preview['principal'].side_effect=HTTPException(403,'revoked')
    assert client.get(url(preview,'preparation'),headers=preview['headers']).status_code==403
    preview['factory'].assert_not_called()
