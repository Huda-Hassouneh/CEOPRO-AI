"""Fail-closed cohort guard. Never returns a protected event to legacy billing."""
from src.ai.billing.payment_contracts import VerifiedPaymentEvent
from dataclasses import replace
from datetime import datetime
import uuid


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

    @staticmethod
    def _capture_scope(row,operation,event,receipt,digest):
        """Require the committed B3 receipt, not a successful decoder alone."""
        if (receipt['operation_id']!=str(operation)
                or receipt['tenant_id']!=row['reservation']['tenant_id']
                or receipt['binding_id']!=event.binding.binding_id
                or receipt['provider_event_id']!=event.event_id
                or receipt['body_digest']!=digest
                or datetime.fromisoformat(receipt['occurred_at'])!=event.occurred_at
                or not receipt.get('authenticated_at')):
            raise ValueError('Committed original notification receipt required')
        uuid.UUID(receipt['receipt_id'])

    @staticmethod
    def _ack(receipt,state,reason):
        # Receipt acknowledgement is not business success or payment authority.
        return dict(journey=True,captured=True,confirmed=False,state=state,reason=reason,
                    event_id=receipt['provider_event_id'],receipt_id=receipt['receipt_id'])

    @staticmethod
    def _anchored(d,event):
        # Only an exact original Checkout, or an already persisted subscription,
        # can acknowledge an unconfirmed journey. Metadata alone is insufficient.
        if event.customer is None:return False
        exact_checkout=(event.checkout and event.checkout.opaque_id==d['provider_checkout_id']
            or event.provider=='paddle' and event.invoice and event.invoice.opaque_id==d['provider_checkout_id'])
        exact_subscription=(event.subscription and d['provider_subscription_id']
            and event.subscription.opaque_id==d['provider_subscription_id'])
        return bool(exact_checkout or exact_subscription)

    @staticmethod
    def _paddle_followup(row,d,event):
        """Signed subsequent billing is receipt evidence, never a new Checkout.

        A persisted original subscription and Customer must both match. This
        exception only quarantines unconfirmed subscription billing; it cannot
        enter trial reconciliation or the confirmed lifecycle application path.
        """
        from src.ai.billing.payment_contracts import GatewayEnvironment, PaymentEventKind
        data=event.raw_evidence.get('data') or {}
        return bool(row['reservation']['state']=='pending' and event.provider=='paddle'
            and event.binding.environment is GatewayEnvironment.TEST
            and event.kind in (PaymentEventKind.INVOICE_SETTLED,PaymentEventKind.INVOICE_FAILED)
            and event.checkout is None and event.invoice and event.customer and event.subscription
            and event.invoice.opaque_id!=d['provider_checkout_id']
            and event.customer.opaque_id==d['provider_customer_id']
            and event.subscription.opaque_id==d['provider_subscription_id']
            and data.get('id')==event.invoice.opaque_id
            and data.get('customer_id')==event.customer.opaque_id
            and data.get('subscription_id')==event.subscription.opaque_id
            and data.get('origin') in ('subscription_update','subscription_recurring'))

    @staticmethod
    def _quarantine(journey,operation,oid,d,event,receipt):
        if not JourneyWebhookReconciler._anchored(d,event):return None
        durable=journey.observations.read(oid)
        if durable['has_conflict'] is True:
            return JourneyWebhookReconciler._ack(receipt,'quarantined','immutable_provider_history_conflict')
        snapshot=journey.collection.consents.read(operation,uuid.UUID(d['presentation_id'])).unpack()
        if snapshot['invalidation'] is not None:
            return JourneyWebhookReconciler._ack(receipt,'quarantined','consent_invalidated')
        return None

    def __call__(self,event):
        if type(event) is not VerifiedPaymentEvent or event.binding is None:
            raise ValueError('Original event binding required')
        with self.resolve(event) as (journey,operation,language):
            row=journey.collection._owned(operation)
            from src.ai.billing.trial_coordinator import _binding
            if _binding(row)!=event.binding:
                raise ValueError('Original event binding required')
            d=journey.dispatches.command(operation,'read')
            followup=d is not None and self._paddle_followup(row,d,event)
            if (d is None or event.customer and event.customer.opaque_id!=d['provider_customer_id']
                    or event.checkout and event.checkout.opaque_id!=d['provider_checkout_id']
                    or event.provider=='paddle' and event.invoice and row['reservation']['state']!='confirmed' and event.invoice.opaque_id!=d['provider_checkout_id'] and not followup
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
            data=event.raw_evidence.get('data') or {}
            metadata=data.get('custom_data') or (data.get('object') or {}).get('metadata') or {}
            if (metadata.get('tenant_id') not in (None,row['reservation']['tenant_id'])
                    or metadata.get('keel_journey_operation') not in (None,str(operation))):
                raise ValueError('Original notification metadata required')
            # B3 owns immutable authenticated receipt identity independently of
            # provider observations and local consent. Exact retries return the
            # same receipt; changed body/time under an event ID fails closed.
            from src.ai.billing.trial_coordinator import observation_identity
            from src.ai.billing.verification_observations import trial_request
            oid=observation_identity(operation)
            op=journey.observations.read(oid)
            if followup and (op is None or not op.get('last_observation_id')):
                raise ValueError('Persisted original subscription evidence required')
            if op is None:
                if row['reservation']['state']=='confirmed':
                    raise ValueError('Original observation required')
                op=journey.observations.begin(oid,trial_request(journey.observations.context(operation)))
            from src.ai.billing.paddle_gateway import notification_digest
            digest=notification_digest(event)
            receipt=journey.observations.notification(op,event.event_id,digest,event.occurred_at)
            if row['reservation']['state']=='confirmed':
                from src.ai.billing.payment_contracts import PaymentEventKind
                if event.kind is PaymentEventKind.CHECKOUT_COMPLETED and event.checkout and event.customer:
                    return dict(duplicate=True,journey=True)
                raise ValueError('Original completed Checkout retry required')
            self._capture_scope(row,oid,event,receipt,digest)
            captured=self._quarantine(journey,operation,oid,d,event,receipt)
            if captured is not None:return captured
            if followup:
                return self._ack(receipt,'quarantined','unconfirmed_subscription_lifecycle')
            result=journey.reconcile(operation,language)
            if result['state']!='confirmed':
                captured=self._quarantine(journey,operation,oid,d,event,receipt)
                if captured is not None:return captured
                # Only deliberate readiness/authority gates after durable pending
                # evidence may stop delivery retries. Transient/unsupported reads,
                # unpersisted evidence and exceptions still request retry (500).
                if (self._anchored(d,event) and result.get('reason') in ('provider_capabilities_unproved','recurring_readiness_unproved',
                        'trusted_confirmation_service_unavailable') and result['state'] in ('pending','blocked')):
                    durable=journey.observations.read(oid)
                    if durable['state']=='observed' and durable['has_conflict'] is False and durable['last_observation_id']:
                        return self._ack(receipt,'pending',result['reason'])
                raise ValueError('Trusted confirmation pending')
            return dict(duplicate=False,journey=True)
