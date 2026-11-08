"""Dormant shared lifecycle; provider evidence, consent and SQL authority stay separate.

No credentials/default provider, registration or network work in SQL transactions.
Initial rights always originate in B4. Custom amendments/refunds remain separate.
"""
import uuid
from src.ai.billing import payment_contracts as C
from src.ai.billing.trial_confirmation import TrialConfirmationRepository
from src.ai.billing.paddle_gateway import notification_digest


class LifecycleRepository(TrialConfirmationRepository):
    def context(self, subscription):
        return self._call('SELECT public.billing_lifecycle_context(%s)', (str(subscription),)).unpack()

    def attest_lifecycle(self, subscription, observation, receipt, version):
        return self._call('SELECT public.billing_lifecycle_attest(%s,%s,%s,%s,%s)',
            (str(uuid.uuid4()), str(subscription), str(observation), str(receipt), version)).unpack()

    def apply(self, attestation):
        return self._call('SELECT public.billing_lifecycle_apply(%s)', (str(attestation),)).unpack()


class SubscriptionLifecycle:
    def __init__(self, observations, attestor, confirmer, observer_for_binding):
        self.observations, self.attestor, self.confirmer = observations, attestor, confirmer
        self.observer_for_binding = observer_for_binding

    def reconcile(self, subscription, event):
        if type(event) is not C.VerifiedPaymentEvent or event.binding is None:
            raise ValueError('Bound authenticated notification required')
        if event.kind is C.PaymentEventKind.UNKNOWN:
            raise ValueError('Unsupported lifecycle notification requires review')
        ctx = self.confirmer.context(subscription)
        s, b = ctx['subscription'], ctx['binding']
        subscription = s['subscription_id']
        binding = C.GatewayBinding(b['provider'], C.GatewayEnvironment(b['environment']), b['merchant_account_id'], b['binding_id'])
        if event.binding != binding or event.provider != binding.provider:
            raise ValueError('Original event binding required')
        ref = lambda x: C.ProviderReference(binding.provider, x, binding=binding)
        request = C.SubscriptionObservationRequest(s['tenant_id'], binding,
            ref(s['provider_customer_id']), ref(s['provider_subscription_id']))
        if (event.customer is not None and event.customer != request.customer
                or event.subscription is not None and event.subscription != request.subscription):
            raise ValueError('Original lifecycle identity required')
        operation = uuid.uuid5(uuid.UUID(str(subscription)), 'subscription-lifecycle-v1')
        op = self.observations.begin(operation, request)
        receipt = self.observations.notification(op, event.event_id,
            notification_digest(event), event.occurred_at)
        observer = self.observer_for_binding(binding)
        if observer.binding != binding:
            raise ValueError('Original observer required')
        claim = self.observations.claim(self.observations.read(operation))
        observed = observer.observe_subscription(request, event=event)
        if (observed.request != request or observed.provenance.source is not C.ObservationSource.AUTHORITATIVE_LOOKUP
                or observed.provenance.stored_observation_id is not None):
            raise ValueError('Fresh authoritative lifecycle observation required')
        identity = uuid.uuid4()
        self.observations.record(claim, identity, observed)
        if observed.outcome is not C.VerificationOutcome.VERIFIED:
            return dict(state='pending',reason='provider_lifecycle_evidence_incomplete')
        a = self.attestor.attest_lifecycle(subscription, identity, receipt['receipt_id'], s['lifecycle_version'])
        result = self.confirmer.apply(a['attestation_id'])
        from src.ai.core.entitlements import forget
        forget(s['tenant_id'])
        return result


class StripeLifecycleAdapter:
    """Reuse B2 strict financial/namespace reader, never the loose legacy snapshots."""
    def __init__(self, verifier):
        if verifier.binding.provider != 'stripe' or verifier.binding.environment is not C.GatewayEnvironment.TEST:
            raise ValueError('Original TEST Stripe verifier required')
        self.binding, self.verifier = verifier.binding, verifier

    def observe_subscription(self, request, *, event=None):
        observed = self.verifier.observe_subscription(request)
        if event is not None and event.invoice and observed.settlement and event.invoice != observed.settlement.invoice:
            # A stale invoice notification cannot authorize a different settlement.
            raise ValueError('Original settlement notification required')
        return observed
