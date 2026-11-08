"""Dormant B1 composition; no runtime registration, credential lookup or activation.

Explicit server-owned dependencies only. Consent collection/read authorization and
bound, fenced Checkout dispatch are B2 integration boundaries, not Boolean flags.
Every concrete repository call ends its transaction before any provider work.
"""
from dataclasses import dataclass, field
from enum import Enum
import uuid

import psycopg2
from src.ai.billing import payment_contracts as C, trial_checkouts as reservations
from src.ai.billing import customer_operations as customers, verification_observations as observations
from src.ai.billing.payment_bindings import _setup


class JourneyState(str, Enum):
    RESERVED = 'reserved'
    CONSENT_REQUIRED = 'consent_required'
    BLOCKED = 'blocked'
    PENDING = 'pending'
    CONFLICT = 'conflict'
    RECORDED_CONFIRMATION = 'recorded_confirmation'


@dataclass(frozen=True)
class JourneyResult:
    operation_id: uuid.UUID
    state: JourneyState
    reason: str
    evidence: C.CustomerPayload | None = field(default=None, repr=False)


def _identity(value):
    if type(value) is not uuid.UUID:
        raise ValueError('server_owned_journey_uuid_required')
    return value


def _binding(row):
    b = row['reservation']['approved_terms']['binding']
    binding = C.GatewayBinding(b['provider'], C.GatewayEnvironment(b['environment']),
                               b['merchant_account_id'], b['binding_id'])
    if binding.binding_id != row['reservation']['binding_id']:
        raise ValueError('original_binding_conflict')
    return binding


def customer_identity(row):
    # One deterministic Customer operation per tenant/original binding, including
    # across released attempts. Existing foreign/mapped operations are not adopted.
    return uuid.uuid5(uuid.UUID(row['reservation']['tenant_id']),
                      'keel-recurring-customer-v1:'+_binding(row).binding_id)


def observation_identity(operation_id):
    return uuid.uuid5(_identity(operation_id), 'keel-trial-observation-v1')


class ReservationRepository:
    """Existing setup socket/RLS only; no new SQL command or grant.

    The future authenticated boundary owns connection tenant/user context. Staff,
    revoked principals and other initiating users cannot load a coordinator row.
    """
    def __init__(self, connection):
        _setup(connection)
        self.connection = connection

    def load(self, operation_id):
        _identity(operation_id)
        try:
            _setup(self.connection)
            with self.connection.cursor() as cur:
                cur.execute("""SELECT jsonb_build_object('reservation',to_jsonb(r),'checkout',to_jsonb(a))
                    FROM public.billing_trial_checkouts r JOIN public.billing_checkout_attempts a USING(attempt_id,tenant_id)
                    WHERE r.attempt_id=%s AND r.tenant_id=public.get_current_tenant()
                    AND r.started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
                    AND EXISTS(SELECT FROM public.tenant_users tu WHERE tu.tenant_id=r.tenant_id
                        AND tu.user_id=r.started_by_user_id AND tu.role_key IN ('owner','admin','accountant')
                        AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL)""", (str(operation_id),))
                value = cur.fetchone()
            self.connection.commit()
            return value[0] if value else None
        except BaseException:
            self.connection.rollback()
            raise

    def reserve(self, operation_id, plan_key, period_code):
        existing = self.load(operation_id)
        try:
            if existing is not None:
                r = existing['reservation']
                if r['plan_key'] != plan_key or r['period_code'] != period_code:
                    raise ValueError('original_terms_conflict')
                terms = r['approved_terms']  # Never reselect today's catalog/binding.
            else:
                terms = reservations.approved_terms(self.connection, plan_key, period_code)
            reservations.reserve(self.connection, operation_id, terms)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return self.load(operation_id)


class TrialCoordinator:
    """Unregistered internal driver. Nothing resolves dependencies from runtime.

    consent_reader is intentionally absent by default. B2 must supply a protected,
    authenticated read of A1 acceptance + presentation + invalidation, as a
    CustomerPayload with those three keys. It is a trusted server boundary, never
    request JSON or a client-supplied acceptance/authorization Boolean. It must
    recheck authorization and validity; B1 supplies no implementation or credential.
    No Checkout sender, attestor or confirmer is accepted by this class.
    """
    def __init__(self, reservation_repository, *, consent_repository=None, consent_reader=None,
                 customer_repository=None, customer_gateway=None, observation_repository=None,
                 observer_for_binding=None):
        self.reservations = reservation_repository
        self.consents, self.consent_reader = consent_repository, consent_reader
        self.customers, self.customer_gateway = customer_repository, customer_gateway
        self.observations, self.observer_for_binding = observation_repository, observer_for_binding

    @staticmethod
    def _result(operation_id, state, reason, evidence=None):
        return JourneyResult(operation_id, state, reason,
                             C.CustomerPayload.freeze(evidence) if evidence is not None else None)

    def _run(self, operation_id, action):
        _identity(operation_id)
        try:
            return action()
        except psycopg2.Error as error:
            code = error.pgcode
            state = JourneyState.CONFLICT if code in ('22023','23505') else JourneyState.BLOCKED
            return self._result(operation_id, state, 'database_'+(code or 'unavailable'))
        except (customers.CustomerOperationError, observations.ObservationError, ValueError) as error:
            # Never return raw provider/database exceptions, payloads or challenges.
            category = str(error)
            if category == 'owned_reservation_required':
                state = JourneyState.BLOCKED
            elif category.endswith(('42501','55P03','55000')):
                state = JourneyState.BLOCKED if category.endswith('42501') else JourneyState.PENDING
            elif category=='observation_unavailable':
                state = JourneyState.PENDING
            elif isinstance(error, customers.CustomerOperationError) and category in (
                'customer_outcome_unknown','customer_unavailable','customer_reconciliation_required',
                'customer_recovery_unavailable'):
                state = JourneyState.PENDING
            else:
                state = JourneyState.CONFLICT
            return self._result(operation_id, state, 'boundary_refused')
        except Exception:
            return self._result(operation_id, JourneyState.BLOCKED, 'integration_boundary_unavailable')

    def _load(self, operation_id):
        row = self.reservations.load(operation_id)
        if row is None or row['reservation']['attempt_id'] != str(operation_id):
            raise ValueError('owned_reservation_required')
        if row['checkout']['attempt_id'] != str(operation_id) or row['checkout']['gateway_binding_id'] != _binding(row).binding_id:
            raise ValueError('checkout_scope_conflict')
        return row

    def start(self, operation_id, plan_key, period_code):
        def action():
            row = self.reservations.reserve(operation_id, plan_key, period_code)
            if row is None:
                raise ValueError('owned_reservation_required')
            return self._result(operation_id, JourneyState.RESERVED, 'immutable_reservation', row)
        return self._run(operation_id, action)

    def status(self, operation_id):
        """Read durable checkpoints only. This result is never authorization."""
        def action():
            row = self._load(operation_id); r, checkout = row['reservation'], row['checkout']
            if r['state']=='confirmed':
                return self._result(operation_id, JourneyState.RECORDED_CONFIRMATION, 'existing_b4_record')
            if r['state']!='pending':
                return self._result(operation_id, JourneyState.BLOCKED, 'reservation_terminal')
            if checkout['first_submitted_at'] is not None and checkout['provider_session_id'] is None:
                return self._result(operation_id, JourneyState.PENDING, 'checkout_recovery_boundary_required')
            if checkout['provider_session_id'] is not None:
                value = self.observations.read(observation_identity(operation_id)) if self.observations is not None else None
                if value is not None and value['has_conflict']:
                    return self._result(operation_id, JourneyState.CONFLICT, 'provider_history_conflict')
                return self._result(operation_id, JourneyState.PENDING, 'trusted_observation_refresh_required')
            if self.customers is not None:
                value = self.customers.read(customer_identity(row))
                if value is not None:
                    if value['state']=='succeeded':
                        return self._result(operation_id, JourneyState.BLOCKED, 'bound_checkout_dispatch_required')
                    if value['state'] in ('rejected','cancelled'):
                        return self._result(operation_id, JourneyState.BLOCKED, 'customer_operation_terminal')
                    return self._result(operation_id, JourneyState.PENDING, 'durable_customer_recovery_required')
            return self._result(operation_id, JourneyState.CONSENT_REQUIRED, 'protected_consent_read_required')
        return self._run(operation_id, action)

    def present(self, operation_id, policy_id):
        def action():
            self._load(operation_id)
            if self.consents is None:
                return self._result(operation_id, JourneyState.BLOCKED, 'consent_collection_boundary_required')
            _identity(policy_id)
            identity = uuid.uuid5(operation_id, 'consent-presentation:'+str(policy_id))
            # A1 owns challenge generation/expiry and policy authorization. A lost
            # presentation response cannot safely redeliver its one-time challenge;
            # repeated IDs fail closed until B2 adds a reviewed read/retry lifecycle.
            value = self.consents.present(operation_id, policy_id, presentation_id=identity).unpack()
            state = JourneyState.CONSENT_REQUIRED if value['status']=='presented' else JourneyState.BLOCKED
            return self._result(operation_id, state, 'authenticated_collection_required', value)
        return self._run(operation_id, action)

    def _acceptance(self, row):
        if self.consent_reader is None:
            return None
        r = row['reservation']
        value = self.consent_reader(uuid.UUID(r['attempt_id']))
        if type(value) is not C.CustomerPayload:
            raise ValueError('protected_consent_snapshot_required')
        value = value.unpack()
        if set(value) != {'acceptance','presentation','invalidation'}:
            raise ValueError('complete_consent_snapshot_required')
        a, p = value['acceptance'], value['presentation']
        if a is None:
            return None
        if value['invalidation'] is not None or p['status']!='presented' or a['presentation_id']!=p['presentation_id']:
            raise ValueError('consent_invalidated')
        for key, expected in (('attempt_id',r['attempt_id']), ('tenant_id',r['tenant_id']),
                              ('binding_id',r['binding_id']), ('actor_id',r['started_by_user_id'])):
            if a[key]!=expected or p[key]!=expected:
                raise ValueError('consent_scope_conflict')
        if p['approved_terms'] != r['approved_terms']:
            raise ValueError('consent_terms_conflict')
        _identity(uuid.UUID(a['acceptance_id']))
        return a

    def advance(self, operation_id, *, email=None, company_name=None):
        def action():
            row = self._load(operation_id); r, checkout = row['reservation'], row['checkout']
            if r['state']=='confirmed':
                return self._result(operation_id, JourneyState.RECORDED_CONFIRMATION, 'existing_b4_record')
            if r['state']!='pending':
                return self._result(operation_id, JourneyState.BLOCKED, 'reservation_terminal')
            if checkout['first_submitted_at'] is not None and checkout['provider_session_id'] is None:
                return self._result(operation_id, JourneyState.PENDING, 'checkout_recovery_boundary_required')
            accepted = self._acceptance(row)
            if accepted is None:
                return self._result(operation_id, JourneyState.BLOCKED, 'protected_consent_read_required')
            binding = _binding(row)
            if checkout['provider_session_id'] is None:
                if self.customers is None or self.customer_gateway is None or not email or not company_name:
                    return self._result(operation_id, JourneyState.BLOCKED, 'durable_customer_boundary_required')
                intent = C.CustomerIntent(r['tenant_id'], str(customer_identity(row)), 'recurring-trial-v1', binding, email, company_name)
                customers.resolve(self.customers, intent, self.customer_gateway)
                # Existing generic Checkout transport lacks original-binding/trial
                # policy support and protected single-sender election. Never send,
                # regenerate keys or adopt legacy sessions to fill those gaps.
                return self._result(operation_id, JourneyState.BLOCKED, 'bound_checkout_dispatch_required')
            if self.observations is None or self.consents is None or self.observer_for_binding is None:
                return self._result(operation_id, JourneyState.BLOCKED, 'trusted_observation_boundary_required')
            request = observations.trial_request(self.observations.context(operation_id))
            if request.binding!=binding or request.tenant_id!=r['tenant_id'] or request.checkout.opaque_id!=checkout['provider_session_id']:
                raise ValueError('original_observation_conflict')
            operation = self.observations.begin(observation_identity(operation_id), request)
            self.consents.associate(uuid.UUID(accepted['acceptance_id']), uuid.UUID(operation['operation_id']))
            operation = self.observations.read(operation['operation_id'])
            if operation['has_conflict']:
                return self._result(operation_id, JourneyState.CONFLICT, 'provider_history_conflict')
            claim = self.observations.claim(operation)  # Repository commits before GET.
            observer = self.observer_for_binding(binding)
            if observer.binding!=binding:
                raise ValueError('original_observer_binding_required')
            observed = observer.observe_trial_checkout(request)
            C._observation_type(observed, C.ProviderVerificationObservation)
            if (observed.request!=request or observed.outcome is C.VerificationOutcome.VERIFIED
                or observed.provenance.source is not C.ObservationSource.AUTHORITATIVE_LOOKUP
                or observed.provenance.stored_observation_id is not None):
                raise ValueError('provider_observation_cannot_supply_local_consent')
            self.observations.record(claim, uuid.uuid4(), observed)
            current = self.observations.read(operation['operation_id'])
            if current['has_conflict'] or observed.outcome is C.VerificationOutcome.CONFLICT:
                return self._result(operation_id, JourneyState.CONFLICT, 'provider_history_conflict')
            if observed.outcome is C.VerificationOutcome.UNSUPPORTED:
                return self._result(operation_id, JourneyState.BLOCKED, 'provider_capability_unproved')
            if observed.outcome is C.VerificationOutcome.UNAVAILABLE:
                return self._result(operation_id, JourneyState.PENDING, 'provider_unavailable')
            authority = observed.recurring_authorization
            if authority is None or authority.readiness is not C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED:
                return self._result(operation_id, JourneyState.PENDING, 'recurring_readiness_unproved')
            if not observed.capabilities.supports_card_backed_trial():
                return self._result(operation_id, JourneyState.BLOCKED, 'provider_capability_unproved')
            return self._result(operation_id, JourneyState.BLOCKED, 'trusted_confirmation_handoff_required')
        return self._run(operation_id, action)
