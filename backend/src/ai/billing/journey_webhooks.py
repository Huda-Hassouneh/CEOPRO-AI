"""Fail-closed cohort guard. Never returns a protected event to legacy billing."""
from src.ai.billing.payment_contracts import VerifiedPaymentEvent
from dataclasses import replace


class BoundStripeJourneyWebhookDecoder:
    """Explicit merchant endpoint secret/binding installation; no default lookup.

    A signing secret's merchant scope must be established at provisioning. It
    cannot be inferred from client metadata, an event ID or the current gateway.
    """
    def __init__(self,binding,signing_secret):
        from src.ai.billing.payment_contracts import GatewayEnvironment
        from src.ai.billing.payment_runtime import webhook_decoder
        if binding.provider!='stripe' or binding.environment is not GatewayEnvironment.TEST:
            raise ValueError('Original TEST webhook binding required')
        self.binding=binding;self._decoder=webhook_decoder(signing_secret)

    def decode(self,payload,signature):
        from src.ai.billing.payment_contracts import ProviderReference, InvalidPaymentWebhook
        e=self._decoder.decode(payload,signature)
        raw=e.raw_evidence
        if (raw.get('livemode') is not False or raw.get('account') not in (None,self.binding.merchant_account_id)
                or (raw.get('data') or {}).get('object',{}).get('livemode') not in (None,False)):
            raise InvalidPaymentWebhook('Webhook namespace conflict')
        def ref(value):return ProviderReference('stripe',value.opaque_id,binding=self.binding) if value else None
        snapshot=e.checkout_snapshot
        if snapshot is not None:
            snapshot=replace(snapshot,reference=ref(snapshot.reference),customer=ref(snapshot.customer),
                subscription=ref(snapshot.subscription),invoice=ref(snapshot.invoice))
        return replace(e,binding=self.binding,customer=ref(e.customer),subscription=ref(e.subscription),
            checkout=ref(e.checkout),invoice=ref(e.invoice),schedule=ref(e.schedule),checkout_snapshot=snapshot)


def marked(metadata):
    return metadata.get('billing_kind')=='keel_recurring_journey' or 'keel_journey_operation' in metadata


def protected(connection, *, customer=None, checkout=None, subscription=None, metadata=None):
    # A marker alone can quarantine, never authorize activation. Lookup errors
    # propagate so migration/permission/outage failures cannot select legacy.
    with connection.cursor() as q:
        q.execute('SELECT public.billing_journey_is_protected(%s,%s,%s)',(customer,checkout,subscription))
        found=q.fetchone()[0]
    return bool(found) or marked(metadata or {})


def classify(connection,event):
    if type(event) is not VerifiedPaymentEvent:
        raise TypeError('Signature-verified event required')
    session=event.checkout_snapshot
    return protected(connection,
        customer=event.customer.opaque_id if event.customer else (session.customer.opaque_id if session and session.customer else None),
        checkout=event.checkout.opaque_id if event.checkout else (session.reference.opaque_id if session else None),
        subscription=event.subscription.opaque_id if event.subscription else None,
        metadata=session.metadata if session else ((event.raw_evidence.get('data') or {}).get('custom_data') or (event.raw_evidence.get('data',{}).get('object',{}).get('metadata') or {})))


class JourneyWebhookReconciler:
    """Explicit trusted resolver owns exact binding, actor-scoped socket lifetime.

    The notification is a wakeup only. Confirmation consumes fresh B3 evidence,
    original consent and B4 authority. No runtime resolver is installed here.
    Paid lifecycle/cancellation notifications stay quarantined until their
    supported trusted settlement/cancellation contract is implemented/approved.
    """
    def __init__(self, resolve): self.resolve=resolve

    def __call__(self,event):
        if event.binding is None:
            raise ValueError('Original event binding required')
        with self.resolve(event) as (journey,operation,language):
            row=journey.collection._owned(operation)
            from src.ai.billing.trial_coordinator import _binding
            if _binding(row)!=event.binding:
                raise ValueError('Original event binding required')
            d=journey.dispatches.command(operation,'read')
            if (d is None or event.customer and event.customer.opaque_id!=d['provider_customer_id']
                    or event.checkout and event.checkout.opaque_id!=d['provider_checkout_id']
                    or event.provider=='paddle' and event.invoice and row['reservation']['state']!='confirmed' and event.invoice.opaque_id!=d['provider_checkout_id']
                    or event.subscription and d['provider_subscription_id'] and event.subscription.opaque_id!=d['provider_subscription_id']):
                raise ValueError('Original event identity required')
            from src.ai.billing.payment_contracts import PaymentEventKind
            if row['reservation']['state']=='confirmed' and event.kind is not PaymentEventKind.CHECKOUT_COMPLETED:
                if journey.lifecycle is None:raise ValueError('Trusted lifecycle reconciliation required')
                # Receipt ownership moves to the exact subscription operation;
                # never claim the same provider event on the old trial operation.
                result=journey.lifecycle.reconcile(row['reservation']['confirmation_id'],event)
                if 'version' not in result or 'subscription_id' not in result:
                    raise ValueError('Trusted lifecycle confirmation pending')
                return result
            # B3 owns immutable authenticated receipt identity independently of
            # provider observations and local consent. Exact retries return the
            # same receipt; changed body/time under an event ID fails closed.
            from src.ai.billing.trial_coordinator import observation_identity
            from src.ai.billing.verification_observations import trial_request
            oid=observation_identity(operation)
            op=journey.observations.read(oid)
            if op is None:
                if row['reservation']['state']=='confirmed':
                    raise ValueError('Original observation required')
                op=journey.observations.begin(oid,trial_request(journey.observations.context(operation)))
            from src.ai.billing.paddle_gateway import notification_digest
            journey.observations.notification(op,event.event_id,
                notification_digest(event),event.occurred_at)
            if row['reservation']['state']=='confirmed':
                from src.ai.billing.payment_contracts import PaymentEventKind
                if event.kind is PaymentEventKind.CHECKOUT_COMPLETED and event.checkout and event.customer:
                    return dict(duplicate=True,journey=True)
                raise ValueError('Original completed Checkout retry required')
            result=journey.reconcile(operation,language)
            if result['state']!='confirmed':
                raise ValueError('Trusted confirmation pending')
            return dict(duplicate=False,journey=True)
