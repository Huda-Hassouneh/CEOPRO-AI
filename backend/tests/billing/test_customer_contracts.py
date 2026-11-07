"""Offline optional capability and bound Stripe tests; never real provider calls."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import ast
import json
from pathlib import Path
import uuid

import pytest

from src.ai.billing import stripe_api
from src.ai.billing.payment_contracts import (
    CapabilityState, CustomerIntent, CustomerPayload, CustomerRecoveryResult, CustomerRecoveryStatus,
    CustomerSnapshot, GatewayBinding, GatewayEnvironment, PaymentProviderError, ProviderReference,
)
from src.ai.billing.stripe_gateway import StripeDurableCustomerGateway


BINDING = GatewayBinding('stripe', GatewayEnvironment.TEST, 'acct_synthetic', 'synthetic-test-binding')


def intent(binding=BINDING):
    return CustomerIntent(str(uuid.uuid4()), str(uuid.uuid4()), 'synthetic-request', binding,
                          'synthetic@example.test', 'Synthetic company')


class Transport:
    api_version = '2026-01-28.clover'
    timeout = 5
    replay_window_seconds = 3600
    max_network_retries = 0
    backoff_seconds = 0

    def __init__(self, binding=BINDING):
        self.binding = binding
        self.calls = []
        self.values = []
        self.namespace_error = False
        self._sdk = SimpleNamespace(v1=SimpleNamespace(customers=SimpleNamespace(create=self._create)))

    def verify_namespace(self):
        self.calls.append('namespace')
        if self.namespace_error:
            raise ValueError('Synthetic namespace conflict')

    create = stripe_api.BoundCustomerTransport.create
    _validate_policy = stripe_api.BoundCustomerTransport._validate_policy
    _check_budget = stripe_api.BoundCustomerTransport._check_budget

    def _create(self, payload, *, options):
        assert options['max_network_retries'] == 0
        self.calls.append(('create', options['idempotency_key']))
        return dict(id='cus_synthetic', livemode=False, metadata=payload['metadata'])

    def retrieve(self, identifier):
        self.calls.append('retrieve')
        return self.values[0]

    def search(self, tenant_id, operation_id):
        self.calls.append('search')
        return self.values


def authorization(request, deadline, *, dispatch_count=1):
    return dict(dispatch_count=dispatch_count, state='submitted', operation_id=request.operation_id,
        tenant_id=request.tenant_id, idempotency_key=request.idempotency_key,
        binding=dict(binding_id=request.binding.binding_id, provider=request.binding.provider,
            environment=request.binding.environment.value, merchant_account_id=request.binding.merchant_account_id),
        replay_deadline=deadline.isoformat())


def test_nested_payload_is_canonical_defensively_copied_and_secret_safe():
    data = {'z': [1, {'nested': 'original'}], 'a': 'value'}
    frozen = CustomerPayload.freeze(data)
    data['z'][1]['nested'] = 'changed'
    unpacked = frozen.unpack(); unpacked['z'].clear()
    assert frozen.unpack()['z'][1]['nested'] == 'original'
    assert frozen.canonical == b'{"a":"value","z":[1,{"nested":"original"}]}'
    assert 'original' not in repr(frozen)
    with pytest.raises(FrozenInstanceError):
        frozen.canonical = b'{}'
    for value in ({'password': 'forbidden'}, {'x': [{'authorization': 'forbidden'}]}, {'card': {}}, {'x': float('nan')}):
        with pytest.raises(ValueError): CustomerPayload.freeze(value)
    with pytest.raises(ValueError): CustomerPayload(b'{ "a":1}')


@pytest.mark.parametrize('binding', [
    GatewayBinding('another', GatewayEnvironment.TEST, 'acct_synthetic', 'other-provider'),
    GatewayBinding('stripe', GatewayEnvironment.LIVE, 'acct_synthetic', 'live-binding'),
    GatewayBinding('stripe', GatewayEnvironment.TEST, 'acct_other', 'other-merchant'),
])
def test_same_customer_id_is_distinct_across_scope(binding):
    assert ProviderReference('stripe', 'same', binding=BINDING) != ProviderReference(binding.provider, 'same', binding=binding)


def test_legacy_protocol_and_create_signature_remain_unchanged():
    import inspect
    from src.ai.billing.payment_contracts import SubscriptionPaymentGateway
    from src.ai.billing.stripe_gateway import StripeGateway
    for name in ('prepare_customer', 'submit_customer', 'retrieve_customer', 'recover_customer'):
        assert name not in SubscriptionPaymentGateway.__dict__
        assert not hasattr(StripeGateway, name)
    assert list(inspect.signature(StripeGateway.create_customer).parameters) == [
        'self', 'email', 'company_name', 'tenant_reference', 'idempotency_key']


def test_prepare_is_offline_and_pending_request_ignores_later_configuration():
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent())
    assert transport.calls == []
    transport.api_version = 'changed'
    assert request.api_version == '2026-01-28.clover'
    with pytest.raises(PaymentProviderError): gateway.submit_customer(request, deadline=datetime.now(timezone.utc)+timedelta(hours=1), authorize=lambda: None)
    assert not transport.calls


@pytest.mark.parametrize('case', ['expired', 'namespace', 'unsupported', 'mismatch', 'malformed'])
def test_bound_submission_fails_closed(case):
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent()); deadline = datetime.now(timezone.utc)+timedelta(hours=1)
    if case == 'expired': deadline = datetime.now(timezone.utc)
    if case == 'namespace': transport.namespace_error = True
    if case == 'unsupported': request = replace(request, replay_support=CapabilityState.UNKNOWN)
    if case == 'mismatch': request = replace(request, binding=GatewayBinding('stripe', GatewayEnvironment.LIVE, 'acct_synthetic', 'live'))
    sdk_calls, validation_errors = [], []
    if case == 'malformed':
        malformed = {'id': 'wrong-without-provenance'}
        def sdk_create(payload, *, options):
            sdk_calls.append((payload, options))
            return malformed
        transport._sdk.v1.customers.create = sdk_create
        original_snapshot = gateway._snapshot
        def validate_snapshot(data, frozen, kind):
            assert data is malformed and frozen is request and kind == 'create_response'
            # Execute the real validator. A signature TypeError cannot satisfy
            # this assertion or populate validation_errors.
            with pytest.raises(PaymentProviderError) as validation_error:
                original_snapshot(data, frozen, kind)
            validation_errors.append(validation_error.value)
            raise validation_error.value
        gateway._snapshot = validate_snapshot
    with pytest.raises(PaymentProviderError) as error:
        gateway.submit_customer(request, deadline=deadline, authorize=lambda: authorization(request, deadline))
    if case == 'malformed':
        assert error.value.outcome.value == 'outcome_unknown'
        assert validation_errors == [error.value]
        assert len(sdk_calls) == 1
        assert sdk_calls[0] == (request.transport.unpack(), {
            'idempotency_key': request.idempotency_key, 'max_network_retries': 0})
        # A replay authorization must still be refused before a second SDK call.
        with pytest.raises(PaymentProviderError):
            gateway.submit_customer(request, deadline=deadline,
                authorize=lambda: authorization(request, deadline, dispatch_count=2))
        assert len(sdk_calls) == len(validation_errors) == 1
    else:
        assert not any(isinstance(c, tuple) for c in transport.calls)


def test_success_empty_search_conflict_and_authoritative_retrieval():
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent())
    deadline = datetime.now(timezone.utc)+timedelta(hours=1)
    snapshot = gateway.submit_customer(request, deadline=deadline, authorize=lambda: authorization(request, deadline))
    assert snapshot.reference.binding == BINDING
    assert gateway.recover_customer(request).status is CustomerRecoveryStatus.INCONCLUSIVE
    data = dict(id='cus_synthetic', livemode=False, metadata=request.transport.unpack()['metadata'])
    transport.values = [data]
    assert gateway.recover_customer(request).snapshot.reference == snapshot.reference
    assert 'retrieve' in transport.calls
    transport.values = [data, dict(data,id='duplicate')]
    assert gateway.recover_customer(request).status is CustomerRecoveryStatus.CONFLICT


def test_last_moment_database_fence_failure_prevents_provider_write():
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent())
    def stale_claim(): raise RuntimeError('synthetic stale claim')
    with pytest.raises(PaymentProviderError) as error:
        gateway.submit_customer(request, deadline=datetime.now(timezone.utc)+timedelta(hours=1), authorize=stale_claim)
    assert error.value.outcome.value == 'outcome_unknown'
    assert transport.calls == ['namespace']


def test_bound_transport_is_request_scoped_has_no_sdk_retries_or_secret_repr(monkeypatch):
    seen = []
    monkeypatch.setattr(stripe_api.stripe, 'StripeClient', lambda *a, **k: seen.append((a,k)) or SimpleNamespace())
    transport = stripe_api.BoundCustomerTransport(BINDING, 'sk_test_synthetic_not_a_real_credential', api_version='fixed')
    assert seen[0][1]['max_network_retries'] == 0
    assert seen[0][1]['stripe_version'] == 'fixed'
    http = seen[0][1]['http_client']
    assert http._timeout == (5, 5)  # Connect/read, NOT an end-to-end deadline.
    assert http._session.max_redirects == 0
    assert all(a.max_retries.total == 0 for a in http._session.adapters.values())
    with pytest.raises(AttributeError): transport.timeout = 20
    assert 'sk_test' not in repr(transport)
    with pytest.raises(ValueError): stripe_api.BoundCustomerTransport(BINDING, 'wrong-mode', api_version='fixed')


def test_namespace_checks_actual_account_and_mode(monkeypatch):
    account = {'id': BINDING.merchant_account_id}
    balance = {'livemode': False}
    sdk = SimpleNamespace(raw_request=lambda *a: account,
                          v1=SimpleNamespace(balance=SimpleNamespace(retrieve=lambda: balance)))
    monkeypatch.setattr(stripe_api.stripe, 'StripeClient', lambda *a,**kw:sdk)
    transport = stripe_api.BoundCustomerTransport(BINDING, 'sk_test_synthetic', api_version='fixed')
    transport.verify_namespace()
    account['id']='another'
    with pytest.raises(ValueError): transport.verify_namespace()
    account['id']=BINDING.merchant_account_id; balance['livemode']=True
    with pytest.raises(ValueError): transport.verify_namespace()


def test_recovery_result_cannot_claim_unscoped_or_unproven_match():
    operation = intent()
    with pytest.raises(ValueError): CustomerRecoveryResult(CustomerRecoveryStatus.MATCH, BINDING, operation.tenant_id, operation.operation_id)
    with pytest.raises(ValueError): CustomerRecoveryResult(CustomerRecoveryStatus.VERIFIED_NON_CREATION, BINDING, operation.tenant_id, operation.operation_id)
    with pytest.raises(ValueError): CustomerSnapshot(ProviderReference('stripe','unscoped'),operation.tenant_id,operation.operation_id,'retrieved','source')


def test_dormant_coordinator_is_not_imported_or_called_from_production_flows():
    root = Path(__file__).resolve().parents[2] / 'src' / 'ai'
    for name in ('billing/service.py','billing/store.py','billing/webhooks.py','billing/payment_runtime.py',
                 'routers/auth.py','routers/billing.py'):
        tree = ast.parse((root/name).read_text(encoding='utf-8-sig'))
        assert not any(isinstance(n,ast.Name) and n.id=='customer_operations' for n in ast.walk(tree))
        assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(
            'customer_operations' in a.name for a in n.names) for n in ast.walk(tree))


def test_verifier_refuses_remote_or_ambiguous_docker_endpoints():
    from scripts.verify_customer_operations import local_docker_endpoint
    assert local_docker_endpoint('npipe:////./pipe/dockerDesktopLinuxEngine')
    assert local_docker_endpoint('unix:///var/run/docker.sock')
    for host in ('tcp://127.0.0.1:2375','ssh://remote','npipe:////remote/pipe/docker_engine','unix://remote/socket'):
        assert not local_docker_endpoint(host)


@pytest.mark.parametrize('policy', ['timeout', 'replay_window_seconds', 'api_version',
                                  'max_network_retries', 'backoff_seconds'])
def test_recovery_rejects_changed_frozen_transport_policy(policy):
    transport = Transport(); transport.timeout = 1
    gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent())
    setattr(transport, policy, {'timeout': 20, 'replay_window_seconds': 7200,
        'api_version': 'changed', 'max_network_retries': 1, 'backoff_seconds': 1}[policy])
    with pytest.raises(PaymentProviderError): gateway.recover_customer(request)
    assert transport.calls == []
    assert request.dispatch_timeout_seconds == 1


def test_deadline_expires_during_namespace_preparation(monkeypatch):
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    clock = SimpleNamespace(now=now)
    monkeypatch.setattr(stripe_api, 'datetime', SimpleNamespace(now=lambda tz: clock.now))
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent()); deadline = now + timedelta(seconds=30)
    transport.verify_namespace = lambda: setattr(clock, 'now', deadline + timedelta(seconds=1))
    with pytest.raises(PaymentProviderError):
        gateway.submit_customer(request, deadline=deadline, authorize=lambda: pytest.fail('Expired before authorization'))
    assert transport.calls == []


@pytest.mark.parametrize('replay', [False, True])
def test_pause_after_authorization_past_deadline_never_sends(monkeypatch, replay):
    # Deterministic scheduling point AFTER authorization, BEFORE SDK dispatch.
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    clock = SimpleNamespace(now=now)
    monkeypatch.setattr(stripe_api, 'datetime', SimpleNamespace(
        now=lambda tz: clock.now, fromisoformat=datetime.fromisoformat))
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent()); deadline = now + timedelta(seconds=30)
    receipts = []
    def authorize_then_pause():
        receipts.append(authorization(request, deadline, dispatch_count=2 if replay else 1))
        clock.now = deadline + timedelta(seconds=1)
        return receipts[-1]
    with pytest.raises(PaymentProviderError):
        gateway.submit_customer(request, deadline=deadline, authorize=authorize_then_pause)
    assert len(receipts) == 1 and not any(isinstance(c, tuple) for c in transport.calls)
    assert receipts[0]['idempotency_key'] == request.idempotency_key
    assert receipts[0]['binding']['binding_id'] == request.binding.binding_id


def test_even_unexpired_database_authorization_cannot_enable_automatic_replay():
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent()); deadline = datetime.now(timezone.utc)+timedelta(hours=1)
    with pytest.raises(PaymentProviderError):
        gateway.submit_customer(request, deadline=deadline,
            authorize=lambda: authorization(request, deadline, dispatch_count=2))
    assert transport.calls == ['namespace']


def test_insufficient_remaining_budget_never_authorizes_or_sends(monkeypatch):
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    monkeypatch.setattr(stripe_api, 'datetime', SimpleNamespace(now=lambda tz: now))
    transport = Transport(); gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent())
    with pytest.raises(PaymentProviderError):
        gateway.submit_customer(request, deadline=now+timedelta(seconds=7),
            authorize=lambda: pytest.fail('Insufficient dispatch budget'))
    assert transport.calls == ['namespace']


@pytest.mark.parametrize('failure', ['retryable_503', 'connection', 'redirect'])
def test_real_sdk_never_retries_redirects_or_sleeps_after_uncertainty(monkeypatch, failure):
    # Real installed SDK/Requests stack, intercepted at HTTPAdapter.send: ZERO network.
    import requests
    import stripe._http_client as http_client
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    clock = SimpleNamespace(now=now)
    monkeypatch.setattr(stripe_api, 'datetime', SimpleNamespace(
        now=lambda tz: clock.now, fromisoformat=datetime.fromisoformat))
    monkeypatch.setattr(http_client.time, 'sleep', lambda *a: pytest.fail('SDK retry/backoff forbidden'))
    sends = []
    def send(session, prepared, **kwargs):
        sends.append(prepared)
        clock.now = now + timedelta(hours=2)  # Expiry while the first request is uncertain.
        if failure == 'connection': raise requests.ConnectionError('Synthetic lost response')
        response = requests.Response(); response.request = prepared; response.url = prepared.url
        response.status_code = 307 if failure == 'redirect' else 503
        response.headers.update({'Stripe-Should-Retry': 'true', 'Retry-After': '2',
                                 'Location': 'https://example.test/forbidden-redirect'})
        response._content = b'{"error":{"type":"api_error","message":"Synthetic unavailable"}}'
        response._content_consumed = True
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    transport = stripe_api.BoundCustomerTransport(BINDING, 'sk_test_synthetic_not_real',
        api_version='2026-01-28.clover', replay_window_seconds=3600)
    monkeypatch.setattr(transport, 'verify_namespace', lambda: None)
    gateway = StripeDurableCustomerGateway(BINDING, transport)
    request = gateway.prepare_customer(intent()); deadline = now + timedelta(hours=1)
    with pytest.raises(PaymentProviderError) as error:
        gateway.submit_customer(request, deadline=deadline, authorize=lambda: authorization(request, deadline))
    assert error.value.outcome.value == 'outcome_unknown'
    assert len(sends) == 1
    assert sends[0].headers['Idempotency-Key'] == request.idempotency_key
