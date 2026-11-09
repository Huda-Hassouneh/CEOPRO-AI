"""Dormant Customer coordination. Never grants rights or invokes legacy Checkout.

Only trusted server adapters may supply provider evidence. SQL enforces scope,
versions and transitions; it cannot authenticate an external API response.
Each command commits before network work. No row lock spans a provider call.
"""
from dataclasses import asdict
from datetime import datetime
import uuid

from psycopg2.extras import Json

from src.ai.billing.payment_bindings import _setup
from src.ai.billing.payment_contracts import (
    CapabilityState, CustomerPayload, CustomerRecoveryResult, CustomerRecoveryStatus, FrozenCustomerRequest,
    GatewayBinding, GatewayEnvironment, PaymentProviderError, ProviderOperationOutcome,
    ProviderReference,
)


class CustomerOperationError(ValueError):
    """Safe category only: never a provider body, request or personal data."""


def binding_from(row):
    b = row['binding']
    return GatewayBinding(b['provider'], GatewayEnvironment(b['environment']),
                          b['merchant_account_id'], b['binding_id'])


def frozen_from(row):
    return FrozenCustomerRequest(
        row['tenant_id'], row['operation_id'], binding_from(row), row['idempotency_key'],
        CustomerPayload(row['logical_request'].encode('utf-8')),
        CustomerPayload(row['transport_request'].encode('utf-8')),
        row['encoder_version'], row['api_version'],
        CapabilityState.SUPPORTED if row['replay_supported'] else CapabilityState.UNKNOWN,
        row['replay_window_seconds'], row['dispatch_timeout_seconds'],
    )


class CustomerRepository:
    def __init__(self, conn):
        _setup(conn)  # Rejects the legacy administrative fallback.
        self.conn = conn

    def _call(self, statement, params):
        try:
            with self.conn.cursor() as cur:
                cur.execute(statement, params)
                result = cur.fetchone()[0]
            self.conn.commit()
            return result
        except BaseException:
            self.conn.rollback()
            raise

    def read(self, operation_id):
        return self._call('SELECT public.billing_customer_operation(%s)', (str(operation_id),))

    def begin(self, intent, request):
        return self._call('SELECT public.billing_customer_begin(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (
            intent.operation_id, intent.binding.binding_id, intent.request_identity,
            request.logical.canonical.decode('utf-8'), request.transport.canonical.decode('utf-8'),
            request.encoder_version, request.api_version, request.replay_support is CapabilityState.SUPPORTED,
            request.replay_window_seconds, request.dispatch_timeout_seconds,
        ))

    def command(self, row, action, token, payload=None):
        return self._call('SELECT public.billing_customer_command(%s,%s,%s,%s,%s)', (
            row['operation_id'], row['version'], action, str(token), Json(payload or {}),
        ))


def _check_request(intent, request):
    if (request.binding != intent.binding or request.tenant_id != intent.tenant_id
        or request.operation_id != intent.operation_id
        or request.idempotency_key != 'keel-customer-' + intent.operation_id
        or request.logical != intent.logical_request()):
        raise CustomerOperationError('customer_request_conflict')


def _evidence(request, snapshot):
    if (snapshot.deleted or snapshot.reference.binding != request.binding
        or snapshot.tenant_id != request.tenant_id or snapshot.operation_id != request.operation_id):
        raise CustomerOperationError('customer_evidence_conflict')
    return dict(binding=asdict(request.binding), tenant_id=request.tenant_id,
                operation_id=request.operation_id, customer_id=snapshot.reference.opaque_id,
                evidence_kind=snapshot.evidence_kind, evidence_id=snapshot.evidence_id)


def resolve(repository, intent, gateway_for_binding):
    """Explicit dormant entrypoint; resolver receives the persisted binding.

    Replays never re-encode pending requests. Gateway construction must not submit
    any write. Claim expiry only authorizes recovery, never a replacement key.
    """
    row = repository.read(intent.operation_id)
    if row is None:
        gateway = gateway_for_binding(intent.binding)
        if gateway.binding != intent.binding:
            raise CustomerOperationError('customer_binding_conflict')
        request = gateway.prepare_customer(intent)
        _check_request(intent, request)
        row = repository.begin(intent, request)
    request = frozen_from(row)
    _check_request(intent, request)
    if row['request_identity'] != intent.request_identity:
        raise CustomerOperationError('customer_request_conflict')
    if row['state'] == 'succeeded':
        return ProviderReference(request.binding.provider, row['provider_customer_id'], binding=request.binding)
    if row['state'] in ('rejected', 'cancelled'):
        raise CustomerOperationError('customer_operation_terminal')
    token = uuid.uuid4()
    row = repository.command(row, 'claim', token)
    gateway = gateway_for_binding(request.binding)
    if gateway.binding != request.binding:
        repository.command(row, 'reconcile', token, {'code': 'conflict'})
        raise CustomerOperationError('customer_binding_conflict')
    if row['first_submitted_at'] is not None:
        try:
            recovery = gateway.recover_customer(request)
        except (PaymentProviderError, AttributeError, NotImplementedError, TypeError, ValueError):
            repository.command(row, 'reconcile', token, {'code': 'unavailable'})
            raise CustomerOperationError('customer_recovery_unavailable') from None
        if not isinstance(recovery, CustomerRecoveryResult):
            repository.command(row, 'reconcile', token, {'code': 'conflict'})
            raise CustomerOperationError('customer_recovery_malformed')
        if (recovery.binding != request.binding or recovery.tenant_id != request.tenant_id
            or recovery.operation_id != request.operation_id):
            repository.command(row, 'reconcile', token, {'code': 'conflict'})
            raise CustomerOperationError('customer_evidence_conflict')
        if recovery.status is CustomerRecoveryStatus.MATCH:
            snapshot = recovery.snapshot
            row = repository.command(row, 'confirm', token, _evidence(request, snapshot))
            return ProviderReference(request.binding.provider, row['provider_customer_id'], binding=request.binding)
        if recovery.status is CustomerRecoveryStatus.VERIFIED_NON_CREATION:
            repository.command(row, 'non_creation', token, dict(
                binding=asdict(request.binding), tenant_id=request.tenant_id,
                operation_id=request.operation_id, evidence_id=recovery.evidence_id,
            ))
            raise CustomerOperationError('customer_verified_non_creation')
        if recovery.status is CustomerRecoveryStatus.CONFLICT:
            repository.command(row, 'reconcile', token, {'code': 'conflict'})
            raise CustomerOperationError('customer_recovery_conflict')
        # A local lease/deadline cannot fence a paused external sender. Until a
        # provider supplies a defensible dispatch-expiry guarantee, an existing
        # submission marker permits reads/reconciliation ONLY, never another
        # create call (even with the same key and an apparently safe deadline).
        repository.command(row, 'reconcile', token, {'code': 'inconclusive'})
        raise CustomerOperationError('customer_reconciliation_required')
    if row['state'] == 'reconciliation_required':
        repository.command(row, 'reconcile', token, {'code': 'inconclusive'})
        raise CustomerOperationError('customer_reconciliation_required')
    row = repository.command(row, 'dispatch', token)
    if row['state'] != 'submitted':
        raise CustomerOperationError('customer_' + row['last_error'])
    # This is the first dispatch only. Transport checks are conservative refusal
    # checks, not proof of arrival before a remote deadline. Never auto-resubmit.
    deadline = datetime.fromisoformat(row['replay_deadline'])
    try:
        snapshot = gateway.submit_customer(request, deadline=deadline,
            authorize=lambda: repository.command(row, 'authorize', token))
    except Exception as error:
        code = error.outcome.value if isinstance(error, PaymentProviderError) else 'outcome_unknown'
        if code not in ('rejected', 'unavailable', 'outcome_unknown', 'not_found', 'unsupported_capability'):
            code = 'outcome_unknown'
        repository.command(row, 'fail', token, {'code': code})
        raise CustomerOperationError('customer_' + code) from None
    try:
        payload = _evidence(request, snapshot)
    except (CustomerOperationError, AttributeError, ValueError):
        repository.command(row, 'reconcile', token, {'code': 'conflict'})
        raise CustomerOperationError('customer_evidence_conflict') from None
    # A failed confirmation is NOT a provider rejection. Lost commit replies are
    # recovered by read(), and stale positive responses require fresh recovery.
    row = repository.command(row, 'confirm', token, payload)
    return ProviderReference(request.binding.provider, row['provider_customer_id'], binding=request.binding)


def cancel_unsubmitted(repository, operation_id):
    row = repository.read(operation_id)
    if row is None:
        raise CustomerOperationError('customer_operation_unavailable')
    token = uuid.uuid4()
    row = repository.command(row, 'claim', token)
    return repository.command(row, 'cancel', token)
