"""Dormant trusted-service persistence, not a provider verifier or billing grant.

The service supplies an already authenticated notification or trusted adapter
result. DTO validation cannot establish that origin. The NOLOGIN database role
has no production credential/configuration, and no existing runtime imports us.
Every command commits before any future network read; no activation locks exist.
"""
from dataclasses import asdict
from decimal import Decimal
import uuid

import psycopg2
from psycopg2.extras import Json
from src.ai.billing import payment_contracts as C


class ObservationError(ValueError):
    """Safe category, never a raw provider/database payload."""


def reference(value):
    return value.opaque_id if value is not None else None


def instant(value):
    return value.isoformat() if value is not None else None


def request_document(request):
    if type(request) not in (C.TrialObservationRequest, C.SubscriptionObservationRequest):
        raise ObservationError('observation_request_type')
    C._observation_scope(request.binding, request.customer, request.subscription)
    trial = type(request) is C.TrialObservationRequest
    result = dict(kind='trial_checkout' if trial else 'subscription',tenant_id=request.tenant_id,
        binding=asdict(request.binding),customer=reference(request.customer),customer_operation_id=request.customer_operation_id,
        subscription=reference(request.subscription),attempt_id=None,checkout=None,terms_digest=None,trial_terms=None)
    if trial:
        if request.reservation_id != request.checkout_attempt_id or request.expected_terms is None:
            raise ObservationError('observation_exact_frozen_context_required')
        terms = request.approved_terms
        expected = request.expected_terms
        result.update(attempt_id=request.checkout_attempt_id,checkout=reference(request.checkout),terms_digest=request.approved_terms_digest,
            trial_terms=dict(plan_key=terms.plan_key,catalog_revision_id=terms.catalog_revision_id,interval_months=terms.interval_months,
                currency=terms.currency,trial_duration_days=terms.trial_duration_days,amount=str(expected.amount.amount),
                quantity=expected.quantity,price=reference(expected.price)))
    return result


def trial_request(context):
    """Context comes from the restricted SQL reader, never today's catalog.

    terms_digest uses PostgreSQL-17 jsonb text/UTF8 SHA256 (not Python JSON
    encoding). The digest covers the ENTIRE immutable reservation snapshot.
    """
    b=context['binding']; binding=C.GatewayBinding(b['provider'],C.GatewayEnvironment(b['environment']),b['merchant_account_id'],b['binding_id'])
    def ref(value): return C.ProviderReference(binding.provider,value,binding=binding) if value is not None else None
    t=context['trial_terms']
    return C.TrialObservationRequest(C.ApprovedTrialTerms(context['tenant_id'],t['plan_key'],t['catalog_revision_id'],
        t['interval_months'],t['currency'],t['trial_duration_days'],binding),context['terms_digest'],context['attempt_id'],context['attempt_id'],
        ref(context['checkout']),ref(context['customer']),context['customer_operation_id'],ref(context['subscription']),
        expected_terms=C.ObservedRecurringTerms(C.Money(Decimal(t['amount']),t['currency']),t['interval_months'],t['quantity'],ref(t['price'])))


def evidence_document(observation):
    C._observation_type(observation,C.ProviderVerificationObservation)
    # Reconstruct through accepted validation, preserving exact types/UTC copies.
    observation=C.ProviderVerificationObservation(**{f.name:getattr(observation,f.name) for f in C.fields(C.ProviderVerificationObservation)})
    terms,trial,method,authority,settlement=(observation.terms,observation.trial,observation.payment_method,observation.recurring_authorization,observation.settlement)
    return dict(customer=reference(observation.customer),checkout=reference(observation.checkout),subscription=reference(observation.subscription),
        checkout_state=observation.checkout_state.value,subscription_state=observation.subscription_state.value,
        terms=None if terms is None else dict(amount=str(terms.amount.amount),currency=terms.amount.currency,interval_months=terms.interval_months,quantity=terms.quantity,price=reference(terms.price)),
        trial=None if trial is None else dict(started_at=instant(trial.started_at),ends_at=instant(trial.ends_at),cutoff=instant(trial.cutoff)),
        payment_method=None if method is None else dict(source=reference(method.source),payment_method=reference(method.payment_method),readiness=method.readiness.value,observed_at=instant(method.observed_at)),
        recurring_authority=None if authority is None else dict(source=reference(authority.source),kind=authority.kind.value,readiness=authority.readiness.value,
            consent=authority.consent.value,consent_reference=reference(authority.consent_reference),consent_terms_revision=authority.consent_terms_revision),
        settlement=None if settlement is None else dict(invoice=reference(settlement.invoice),amount_paid=str(settlement.amount_paid.amount),currency=settlement.amount_paid.currency,
            payment_state=settlement.payment_state.value,confirmed=settlement.settlement_confirmed,initial=settlement.initial_subscription_invoice,
            purpose=settlement.purpose.value,paid_at=instant(settlement.paid_at),coverage=[[instant(a),instant(b)] for a,b in settlement.coverage]),
        period_start=instant(observation.period_start),period_end=instant(observation.period_end),cancel_at_period_end=observation.cancel_at_period_end,
        cancelled_at=instant(observation.cancelled_at),capabilities={f.name:getattr(observation.capabilities,f.name).value for f in C.fields(C.GatewayCapabilities)})


class ObservationRepository:
    """No environment lookup or administrative fallback. Trusted socket required."""
    def __init__(self, conn):
        with conn.cursor() as cur:
            cur.execute('SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
            if cur.fetchone()!=('ceopro_billing_observer','ceopro_billing_observer',False,False):
                raise ObservationError('restricted_observation_socket_required')
        self.conn=conn

    def _call(self, statement, parameters):
        error=None
        try:
            with self.conn.cursor() as cur:
                cur.execute(statement,parameters);result=cur.fetchone()[0]
            self.conn.commit()
            return result
        except psycopg2.Error as exc:
            error=exc.pgcode or 'unavailable'
            self.conn.rollback()
        except BaseException:
            self.conn.rollback();raise
        raise ObservationError('observation_'+error)

    def context(self, attempt_id):
        return self._call('SELECT public.billing_observation_trial_context(%s)',(str(attempt_id),))

    def begin(self, operation_id, request):
        return self._call('SELECT public.billing_observation_begin(%s,%s)',(str(operation_id),Json(request_document(request))))

    def read(self, operation_id):
        return self._call('SELECT public.billing_observation_read(%s)',(str(operation_id),))

    def claim(self, row, token=None):
        return self._call('SELECT public.billing_observation_claim(%s,%s,%s)',(row['operation_id'],row['version'],str(token or uuid.uuid4())))

    def notification(self, row, event_id, body_digest, occurred_at, *, receipt_id=None):
        """Trusted signature boundary ONLY. No raw body, signature or verified flag."""
        C._terms_digest(body_digest)
        return self._call('SELECT public.billing_observation_notification(%s,%s,%s,%s,%s)',
            (row['operation_id'],str(receipt_id or uuid.uuid4()),event_id,body_digest,C._observation_time(occurred_at)))

    def record(self, row, observation_id, observation, *, receipt_id=None):
        C._observation_type(observation,C.ProviderVerificationObservation)
        if request_document(observation.request)!=row['request']:
            raise ObservationError('observation_request_conflict')
        p=observation.provenance
        if p.stored_observation_id is not None:
            raise ObservationError('stored_observation_is_not_new_provider_evidence')
        result=self._call('SELECT public.billing_observation_record(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (row['operation_id'],row['version'],row['claim_token'],str(observation_id),p.source.value,receipt_id,
             p.reference.opaque_id,p.observed_at,p.adapter_version,p.api_version,observation.outcome.value,Json(evidence_document(observation)),Json(request_document(observation.request))))
        return C.CustomerPayload.freeze(result)  # Immutable stored evidence; unpack returns a deep copy.
