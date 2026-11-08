"""Mocked B1 composition only. No native DB/provider or real consent acceptance."""
import ast
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from src.ai.billing import payment_contracts as C, trial_coordinator as J
from src.ai.billing import verification_observations as V, customer_operations as U


@pytest.fixture
def scenario():
    identity, tenant, actor, policy, acceptance = [uuid.uuid4() for _ in range(5)]
    binding = C.GatewayBinding('stripe', C.GatewayEnvironment.TEST, 'merchant_original', 'binding_original')
    b = dict(provider=binding.provider, environment=binding.environment.value,
             merchant_account_id=binding.merchant_account_id, binding_id=binding.binding_id)
    terms = dict(binding=b, currency='USD', approved_amount='59', interval_months=1, trial_duration_days=14)
    row = dict(reservation=dict(attempt_id=str(identity), tenant_id=str(tenant), started_by_user_id=str(actor),
        binding_id=binding.binding_id, approved_terms=terms, plan_key='growth', period_code='monthly', state='pending'),
        checkout=dict(attempt_id=str(identity), gateway_binding_id=binding.binding_id,
            first_submitted_at=None, provider_session_id=None))
    presentation = dict(presentation_id=str(policy), tenant_id=str(tenant), actor_id=str(actor), attempt_id=str(identity),
        binding_id=binding.binding_id, approved_terms=terms, status='presented')
    accepted = dict(presentation_id=str(policy), acceptance_id=str(acceptance), tenant_id=str(tenant),
        actor_id=str(actor), attempt_id=str(identity), binding_id=binding.binding_id)
    consent = dict(acceptance=accepted, presentation=presentation, invalidation=None)
    repository = Mock()
    repository.load.side_effect = lambda _: deepcopy(row)
    repository.reserve.side_effect = lambda *args: deepcopy(row)
    consents = Mock()
    reader = Mock(side_effect=lambda _: C.CustomerPayload.freeze(consent))
    observation_repo = Mock()
    context = dict(tenant_id=str(tenant), binding=b, terms_digest='sha256:'+'a'*64, attempt_id=str(identity),
        customer='customer_original', customer_operation_id=str(J.customer_identity(row)), checkout='checkout_original', subscription=None,
        trial_terms=dict(plan_key='growth', catalog_revision_id='catalog_original', interval_months=1, currency='USD',
                         trial_duration_days=14, amount='59', quantity=1, price='price_original'))
    observation_repo.context.side_effect=lambda _: deepcopy(context)
    operation = dict(operation_id=str(J.observation_identity(identity)), has_conflict=False, version=1)
    observation_repo.begin.side_effect=lambda oid, request: dict(operation, request=V.request_document(request))
    observation_repo.read.side_effect=lambda _: dict(operation)
    observation_repo.claim.side_effect=lambda value: dict(value, claim_token=str(uuid.uuid4()))
    request = V.trial_request(context)
    now = datetime.now(timezone.utc)
    ref = lambda name: C.ProviderReference(binding.provider, name, binding=binding)
    observed = C.ProviderVerificationObservation(request, C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,
        request.checkout, now, 'synthetic-b1', 'synthetic-api'), C.VerificationOutcome.PENDING,
        customer=request.customer, checkout=request.checkout, subscription=ref('subscription_original'),
        checkout_state=C.CheckoutState.COMPLETE, subscription_state=C.SubscriptionState.TRIALING,
        terms=request.expected_terms, trial=C.ObservedTrialWindow(now, now+timedelta(days=14), now+timedelta(days=14)))
    observer = Mock(binding=binding)
    observer.observe_trial_checkout.return_value=observed
    factory = Mock(return_value=observer)
    coordinator = J.TrialCoordinator(repository, consent_repository=consents, consent_reader=reader,
        customer_repository=Mock(), customer_gateway=Mock(), observation_repository=observation_repo, observer_for_binding=factory)
    return SimpleNamespace(**locals())


def submitted(s):
    s.row['checkout'].update(first_submitted_at='database timestamp', provider_session_id='checkout_original')


def test_default_coordinator_is_disabled_without_trusted_collection_boundary(scenario):
    s=scenario; coordinator=J.TrialCoordinator(s.repository)
    assert coordinator.start(s.identity,'growth','monthly').state is J.JourneyState.RESERVED
    assert coordinator.present(s.identity,s.policy).state is J.JourneyState.BLOCKED
    assert coordinator.advance(s.identity).reason == 'protected_consent_read_required'
    s.observer.observe_trial_checkout.assert_not_called()


def test_stable_original_reservation_replay_never_selects_current_terms(scenario,monkeypatch):
    s=scenario; connection=Mock()
    repo=object.__new__(J.ReservationRepository); repo.connection=connection
    repo.load=Mock(return_value=deepcopy(s.row))
    approved=Mock(side_effect=AssertionError('Current default/catalog must not be used'))
    reserve=Mock()
    monkeypatch.setattr(J.reservations,'approved_terms',approved)
    monkeypatch.setattr(J.reservations,'reserve',reserve)
    assert repo.reserve(s.identity,'growth','monthly') == s.row
    assert repo.reserve(s.identity,'growth','monthly') == s.row
    assert all(call.args[1:]==(s.identity,s.terms) for call in reserve.call_args_list)
    with pytest.raises(ValueError,match='original_terms_conflict'):
        repo.reserve(s.identity,'growth','annual')
    assert reserve.call_count==2


def test_customer_retries_delegate_same_identity_and_original_binding(scenario,monkeypatch):
    s=scenario; seen=[]
    def resolve(repository,intent,factory):
        seen.append(intent)
        if len(seen)==1:
            raise U.CustomerOperationError('customer_outcome_unknown')
        return C.ProviderReference('stripe','customer_original',binding=s.binding)
    monkeypatch.setattr(U,'resolve',resolve)
    assert s.coordinator.advance(s.identity,email='synthetic@example.test',company_name='Synthetic').state is J.JourneyState.PENDING
    assert s.coordinator.advance(s.identity,email='synthetic@example.test',company_name='Synthetic').reason == 'bound_checkout_dispatch_required'
    assert seen[0]==seen[1] and seen[0].binding==s.binding
    other=deepcopy(s.row); other['reservation']['attempt_id']=str(uuid.uuid4())
    assert J.customer_identity(other)==J.customer_identity(s.row)
    assert s.row['checkout']['first_submitted_at'] is None  # B1 never sends Checkout.


def test_ambiguous_checkout_blocks_customer_recreation_or_new_checkout(scenario,monkeypatch):
    s=scenario; s.row['checkout']['first_submitted_at']='database timestamp'
    resolve=Mock(side_effect=AssertionError('No Customer recovery side effect'))
    monkeypatch.setattr(U,'resolve',resolve)
    for _ in range(2):
        assert s.coordinator.advance(s.identity).reason == 'checkout_recovery_boundary_required'
    resolve.assert_not_called(); s.reader.assert_not_called(); s.factory.assert_not_called()


@pytest.mark.parametrize('change',['boolean','missing','withdrawn','actor','tenant','binding','terms'])
def test_untrusted_or_conflicting_consent_never_reaches_provider(scenario,monkeypatch,change):
    s=scenario; resolve=Mock(); monkeypatch.setattr(U,'resolve',resolve)
    if change=='boolean': s.reader.side_effect=lambda _:True
    elif change=='missing': s.consent['acceptance']=None
    elif change=='withdrawn': s.consent['invalidation']={'reason':'withdrawn'}
    elif change=='terms': s.consent['presentation']['approved_terms']=dict(s.terms,approved_amount='0')
    else:
        key={'actor':'actor_id','tenant':'tenant_id','binding':'binding_id'}[change]
        s.consent['acceptance'][key]='different'
    result=s.coordinator.advance(s.identity,email='synthetic@example.test',company_name='Synthetic')
    assert result.state in (J.JourneyState.BLOCKED,J.JourneyState.CONFLICT)
    resolve.assert_not_called(); s.factory.assert_not_called()


def test_presentation_identity_stable_and_challenge_not_in_repr(scenario):
    s=scenario; s.consents.present.return_value=C.CustomerPayload.freeze({'status':'presented','challenge':'private-challenge'})
    first=s.coordinator.present(s.identity,s.policy)
    s.coordinator.present(s.identity,s.policy)
    assert s.consents.present.call_args_list[0]==s.consents.present.call_args_list[1]
    assert 'private-challenge' not in repr(first)
    s.consents.present.side_effect=ValueError('duplicate presentation')
    assert s.coordinator.present(s.identity,s.policy).state is J.JourneyState.CONFLICT


def test_observation_reuses_identity_associates_before_read_and_never_activates(scenario):
    s=scenario; submitted(s)
    for _ in range(2):
        result=s.coordinator.advance(s.identity)
        assert result.reason=='recurring_readiness_unproved'
    assert all(call.args[0]==J.observation_identity(s.identity) for call in s.observation_repo.begin.call_args_list)
    s.consents.associate.assert_called_with(s.acceptance,J.observation_identity(s.identity))
    s.factory.assert_called_with(s.binding)
    assert not hasattr(J.TrialCoordinator,'confirm') and not hasattr(J.TrialCoordinator,'accept')


@pytest.mark.parametrize('failure,state',[('42501',J.JourneyState.BLOCKED),('55000',J.JourneyState.PENDING)])
def test_authorization_and_stale_claims_fail_closed_before_provider(scenario,failure,state):
    s=scenario; submitted(s)
    s.observation_repo.claim.side_effect=V.ObservationError('observation_'+failure)
    assert s.coordinator.advance(s.identity).state is state
    s.observer.observe_trial_checkout.assert_not_called()
    s.observation_repo.record.assert_not_called()


@pytest.mark.parametrize('change',['binding','request','stored','verified'])
def test_provider_cannot_replace_scope_or_manufacture_local_consent(scenario,change):
    s=scenario; submitted(s)
    value=s.observed
    if change=='binding': s.observer.binding=replace(s.binding,binding_id='different')
    elif change=='request': value=replace(value,request=replace(value.request,customer_operation_id='other'))
    elif change=='stored': value=replace(value,provenance=replace(value.provenance,stored_observation_id='stored'))
    else:
        authority=C.RecurringAuthorizationEvidence(value.customer,value.subscription,C.RecurringAuthorizationKind.PROVIDER_AGREEMENT,
            C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED,C.RecurringConsentState.RECORDED,value.subscription,'synthetic-revision')
        caps=C.GatewayCapabilities(**{f.name:C.CapabilityState.SUPPORTED for f in fields(C.GatewayCapabilities)})
        value=replace(value,capabilities=caps,recurring_authorization=authority,outcome=C.VerificationOutcome.VERIFIED)
    s.observer.observe_trial_checkout.return_value=value
    assert s.coordinator.advance(s.identity).state is J.JourneyState.CONFLICT
    s.observation_repo.record.assert_not_called()


@pytest.mark.parametrize('outcome,state',[(C.VerificationOutcome.UNAVAILABLE,J.JourneyState.PENDING),
    (C.VerificationOutcome.UNSUPPORTED,J.JourneyState.BLOCKED),(C.VerificationOutcome.CONFLICT,J.JourneyState.CONFLICT)])
def test_provider_nonverified_outcomes_are_not_upgraded(scenario,outcome,state):
    s=scenario; submitted(s)
    s.observer.observe_trial_checkout.return_value=replace(s.observed,outcome=outcome)
    assert s.coordinator.advance(s.identity).state is state
    assert s.observation_repo.record.call_args.args[2].outcome is outcome


def test_complete_provider_prerequisites_still_cannot_activate(scenario):
    s=scenario; submitted(s)
    authority=C.RecurringAuthorizationEvidence(s.observed.customer,s.observed.subscription,C.RecurringAuthorizationKind.PROVIDER_AGREEMENT,
        C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED)
    ready=replace(s.observed,recurring_authorization=authority)
    s.observer.observe_trial_checkout.return_value=ready
    assert s.coordinator.advance(s.identity).reason=='provider_capability_unproved'
    s.observer.observe_trial_checkout.return_value=replace(ready,capabilities=C.GatewayCapabilities(**{
        f.name:C.CapabilityState.SUPPORTED for f in fields(C.GatewayCapabilities)}))
    assert s.coordinator.advance(s.identity).reason=='trusted_confirmation_handoff_required'


def test_private_boundary_errors_are_sanitized_and_no_replacement_identity(scenario):
    s=scenario; s.reader.side_effect=RuntimeError('private-token-private-error')
    result=s.coordinator.advance(s.identity)
    assert result.operation_id==s.identity and result.state is J.JourneyState.BLOCKED
    assert 'private-token' not in repr(result)
    with pytest.raises(ValueError,match='server_owned_journey_uuid_required'):
        s.coordinator.advance(str(s.identity))


def test_only_readonly_preview_can_import_coordinator_and_activation_is_absent():
    root=Path(__file__).resolve().parents[2]/'src'
    for path in root.rglob('*.py'):
        if 'tests' in path.parts or path.name=='trial_coordinator.py': continue
        if path.relative_to(root).as_posix() in ('ai/routers/trial_journey_preview.py','ai/billing/subscription_journey.py','ai/billing/stripe_journey.py','ai/billing/journey_webhooks.py'): continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                assert not (getattr(node,'module','') or '').endswith('trial_coordinator'),str(path)
                assert not any(a.name.endswith('trial_coordinator') for a in node.names),str(path)
    source=(root/'ai/billing/trial_coordinator.py').read_text()
    for forbidden in ('trial_confirmation','os.environ','system_connection','payment_runtime','submit_checkout',
                      'billing_confirmation_apply','billing_setup_trial','usage_ledger','tenant_plan_assignments'):
        assert forbidden not in source


@pytest.mark.parametrize('checkpoint', ['initial','ambiguous','session','confirmed','customer_unknown','customer_succeeded'])
def test_status_reads_persisted_checkpoints_without_advancing(scenario,monkeypatch,checkpoint):
    s=scenario; resolver=Mock(); monkeypatch.setattr(U,'resolve',resolver)
    s.coordinator.customers.read.return_value=None
    if checkpoint=='ambiguous':
        s.row['checkout']['first_submitted_at']='database timestamp'
    elif checkpoint=='session':
        submitted(s)
    elif checkpoint=='confirmed':
        s.row['reservation']['state']='confirmed'
    elif checkpoint.startswith('customer_'):
        s.coordinator.customers.read.return_value={'state':checkpoint.removeprefix('customer_')}
    result=s.coordinator.status(s.identity)
    assert result.operation_id==s.identity
    expected={'initial':'protected_consent_read_required','ambiguous':'checkout_recovery_boundary_required',
        'session':'trusted_observation_refresh_required','confirmed':'existing_b4_record',
        'customer_unknown':'durable_customer_recovery_required','customer_succeeded':'bound_checkout_dispatch_required'}
    assert result.reason==expected[checkpoint]
    resolver.assert_not_called(); s.factory.assert_not_called(); s.reader.assert_not_called()
    s.consents.associate.assert_not_called(); s.observation_repo.claim.assert_not_called()


def test_read_repository_rejects_unrestricted_socket_without_sql_or_fallback():
    connection=Mock(billing_setup_only=False)
    with pytest.raises(ValueError,match='Restricted billing setup connection required'):
        J.ReservationRepository(connection)
    connection.cursor.assert_not_called()


def test_read_repository_ends_transaction_and_denies_unknown_principal(scenario,monkeypatch):
    s=scenario; connection=Mock()
    monkeypatch.setattr(J,'_setup',Mock())
    repo=J.ReservationRepository(connection)
    # Cursor context mirrors DB-API only; no database is contacted.
    from unittest.mock import MagicMock
    cursor=MagicMock(); connection.cursor.return_value=cursor
    cursor.__enter__.return_value.fetchone.return_value=(deepcopy(s.row),)
    assert repo.load(s.identity)==s.row
    connection.commit.assert_called_once()
    J._setup.side_effect=ValueError('revoked socket')
    with pytest.raises(ValueError,match='revoked socket'):
        repo.load(s.identity)
    connection.rollback.assert_called_once()
