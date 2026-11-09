"""Executable dormant composition. Dependencies are scoped server capabilities.

No credential discovery, runtime provisioning or provider/default selection. Every
repository command commits before network work. A durable submission marker is
never reset, even after a crash, timeout, withdrawal or negative provider search.
"""
from dataclasses import replace
import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from psycopg2.extras import Json
from src.ai.billing import payment_contracts as C, customer_operations as U
from src.ai.billing import verification_observations as V
from src.ai.billing.trial_coordinator import TrialCoordinator, _binding, customer_identity, observation_identity
from src.ai.billing.authenticated_consent import CollectionBlocked
from src.ai.billing.recurring_consent import ConsentRepository


class DispatchRepository(ConsentRepository):
    def compensation(self, operation, action, subscription=None):
        return self._call('SELECT public.billing_journey_compensate(%s,%s,%s)',(str(operation),action,subscription)).unpack()

    def cancellation(self, operation, action):
        return self._call('SELECT public.billing_journey_cancellation(%s,%s)',(str(operation),action)).unpack()

    def command(self, operation, action, *, acceptance=None, customer=None, request=None, session=None):
        result = self._call('SELECT public.billing_journey_dispatch(%s,%s,%s,%s,%s,%s)',
            (str(operation), str(acceptance) if acceptance else None, str(customer) if customer else None,
             Json(request) if request is not None else None, action, session)).unpack()
        return result or None


class SubscriptionJourney:
    """One workflow from reservation through B4; no alternate rights writer.

    Production deliberately installs no instance/factory. Synthetic tests supply
    approved fixture policies and separate restricted sockets for each boundary.
    Custom trial confirmation and paid lifecycle reconciliation remain unsupported
    by B4 and are refused, never routed through legacy activation.
    """
    def __init__(self, collection, dispatches, customers, customer_gateway, checkout_gateway,
                 observations, observer_for_binding, *, attestor=None, confirmer=None,
                 contact=None, return_urls=None, lifecycle=None):
        self.collection, self.reservations = collection, collection.reservations
        self.dispatches, self.customers = dispatches, customers
        self.customer_gateway, self.checkout_gateway = customer_gateway, checkout_gateway
        self.observations, self.observer_for_binding = observations, observer_for_binding
        self.attestor, self.confirmer = attestor, confirmer
        self.contact, self.return_urls = contact, return_urls
        self.lifecycle = lifecycle

    def start(self, operation, plan, period):
        # operation is derived at the authenticated boundary, not a provider ID.
        result = TrialCoordinator(self.reservations).start(operation, plan, period)
        return dict(operation_id=str(operation), state=result.state.value, reason=result.reason)

    def _urls(self,row):
        r=row['reservation'];result=[]
        for url in self.return_urls(row):
            parts=urlsplit(url)
            query=dict(parse_qsl(parts.query,keep_blank_values=True))
            query.update(trial_operation=r['attempt_id'],plan=r['plan_key'],period=r['period_code'])
            result.append(urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment)))
        return tuple(result)

    def _accepted(self, operation, language):
        row = self.collection._owned(operation)
        document, values = self.collection._policy(row, language)
        pid = uuid.uuid5(operation, 'consent-presentation:'+str(document.policy_id))
        snapshot = self.collection.consents.read(operation, pid).unpack()
        self.collection._registry(document, values, snapshot['policy'])
        protected = C.CustomerPayload.freeze({k:snapshot[k] for k in ('acceptance','presentation','invalidation')})
        accepted = TrialCoordinator(self.reservations, consent_reader=lambda _: protected)._acceptance(row)
        if accepted is None:
            raise CollectionBlocked('accepted_consent_required')
        return row, accepted, dict(values, trial_start_mode=document.trial_start_mode)

    @staticmethod
    def _result(operation, state, reason, **values):
        return dict(operation_id=str(operation), state=state, reason=reason, **values)

    def advance(self, operation, language):
        """Authenticated explicit action/reconciliation; never invoked by GET."""
        row = self.collection._owned(operation)
        if row['reservation']['state']=='confirmed':
            return self._result(operation, 'confirmed', 'trusted_confirmation_recorded')
        row, accepted, policy = self._accepted(operation, language)
        binding = _binding(row)
        if row['reservation']['state']!='pending':
            raise CollectionBlocked('reservation_terminal')
        # Existing B4 scope is deliberately retained. No inline Custom repricing.
        # Reservation SQL only admits approved self-serve catalog prices. Custom
        # quotes have a distinct contract and cannot enter this B4 trial path.
        d = self.dispatches.command(operation, 'read')
        if d and d['expired_at']:
            return self._result(operation,'expired','provider_checkout_expired')
        gateway = self.checkout_gateway(binding)
        if gateway.binding != binding:
            raise CollectionBlocked('original_checkout_binding_required')
        if d is None:
            gateway.check_policy(policy)
            # Contact and return URLs come from authenticated server repositories,
            # never request JSON. The policy gate precedes Customer creation.
            if self.contact is None or self.return_urls is None:
                raise CollectionBlocked('trusted_contact_and_return_urls_required')
            email, name = self.contact(row)
            customer = U.resolve(self.customers, C.CustomerIntent(row['reservation']['tenant_id'],
                str(customer_identity(row)), 'recurring-trial-v1', binding, email, name), self.customer_gateway)
            request = gateway.prepare(row, customer, policy, self._urls(row))
            d = self.dispatches.command(operation, 'prepare', acceptance=accepted['acceptance_id'],
                customer=customer_identity(row), request=request)
        args = dict(acceptance=d['acceptance_id'], customer=d['customer_operation_id'])
        if not d['provider_checkout_id']:
            election = self.dispatches.command(operation, 'elect', **args)
            # Exactly one caller may POST. Every later caller is GET-only, even
            # if the original sender crashed before reaching the provider.
            if election['elected']:
                try:
                    session = gateway.submit(d, authorize=lambda: self.dispatches.command(operation, 'authorize', **args))
                except Exception:
                    return self._result(operation, 'pending', 'checkout_outcome_unknown')
            else:
                try:
                    session = gateway.recover(d)
                except Exception:
                    session = None
                if session is None:
                    return self._result(operation, 'pending', 'checkout_recovery_required')
            # Adapter must authenticate exact frozen request/Customer/metadata.
            gateway.validate(session, d)
            d = self.dispatches.command(operation, 'session', session=session.reference.opaque_id, **args)
        session = gateway.retrieve(d)
        gateway.validate(session, d)
        if session.state is C.CheckoutState.OPEN:
            return self._result(operation, 'checkout_ready', 'provider_checkout_open', url=session.url, provider=binding.provider)
        if session.state is C.CheckoutState.EXPIRED:
            self.dispatches.command(operation,'expired',**args)
            return self._result(operation, 'expired', 'provider_checkout_expired')
        return self.reconcile(operation, language)

    def checkout_details(self, operation, language):
        """Authenticated read-only payment page handoff. Never provider discovery.
        Consent/actor/current billing authority are rechecked by protected reads.
        """
        row, accepted, policy = self._accepted(operation, language)
        if row['reservation']['state']!='pending':raise CollectionBlocked('reservation_terminal')
        binding=_binding(row)
        d=self.dispatches.command(operation,'read')
        if (binding.environment is not C.GatewayEnvironment.TEST
                or d and (d['expired_at'] or d['acceptance_id']!=accepted['acceptance_id'])):
            raise CollectionBlocked('original_checkout_required')
        result=dict(operation_id=str(operation),provider=binding.provider,environment='test',
            binding_id=binding.binding_id, transaction_id=d['provider_checkout_id'] if d else None)
        bundle=getattr(self.collection.policies,'bundle_digest',None)
        if bundle is not None:result['policy_bundle_digest']=bundle
        return result

    def reconcile(self, operation, language):
        row, accepted, policy = self._accepted(operation, language)
        request = V.trial_request(self.observations.context(operation))
        if request.binding != _binding(row) or request.tenant_id != self.collection.tenant:
            raise CollectionBlocked('original_observation_required')
        oid = observation_identity(operation)
        op = self.observations.begin(oid, request)
        self.collection.consents.associate(uuid.UUID(accepted['acceptance_id']), oid)
        # A prior conflict must never be cleared, but it must not suppress fresh
        # read-only evidence capture. Record the lookup, then retain the conflict
        # fence below before subscription association, attestation or confirmation.
        observer = self.observer_for_binding(request.binding,
            lambda req, sub: self.observations.setup_source(oid, sub) if req == request else None)
        if observer.binding != request.binding:
            raise CollectionBlocked('original_observer_required')
        claim = self.observations.claim(self.observations.read(oid))
        observed = observer.observe_trial_checkout(request)
        if (observed.request != request or observed.outcome is C.VerificationOutcome.VERIFIED
                or observed.provenance.source is not C.ObservationSource.AUTHORITATIVE_LOOKUP
                or observed.provenance.stored_observation_id is not None):
            raise CollectionBlocked('provider_cannot_supply_local_consent')
        self.observations.record(claim, uuid.uuid4(), observed)
        if self.observations.read(oid)['has_conflict']:
            return self._result(operation, 'conflict', 'immutable_provider_history_conflict')
        if observed.subscription is not None and observed.outcome is C.VerificationOutcome.PENDING:
            d=self.dispatches.command(operation,'read')
            self.dispatches.command(operation,'subscription',acceptance=d['acceptance_id'],customer=d['customer_operation_id'],session=observed.subscription.opaque_id)
        if observed.outcome not in (C.VerificationOutcome.PENDING,):
            return self._result(operation, 'pending', 'provider_evidence_incomplete')
        if not observed.capabilities.supports_card_backed_trial():
            return self._result(operation, 'blocked', 'provider_capabilities_unproved')
        authority = observed.recurring_authorization
        if authority is None or authority.readiness is not C.PaymentMethodReadiness.REUSABLE_AUTHORITY_CONFIRMED:
            return self._result(operation, 'pending', 'recurring_readiness_unproved')
        if self.attestor is None or self.confirmer is None:
            return self._result(operation, 'blocked', 'trusted_confirmation_service_unavailable')
        # Only local consent fields change. Contract validation and B4 SQL enforce
        # complete capabilities, all provider facts, history, freshness, authority,
        # global exclusivity and the atomic withdrawal fence again at consumption.
        verified = replace(observed, outcome=C.VerificationOutcome.VERIFIED,
            recurring_authorization=replace(authority, consent=C.RecurringConsentState.RECORDED,
                consent_reference=C.ProviderReference(request.binding.provider, policy['agreement_reference'], binding=request.binding),
                consent_terms_revision=policy['agreement_revision']))
        completed, expires = observer.checkout_window(request, observed)
        claim = self.observations.claim(self.observations.read(oid))
        attestation = self.attestor.attest(claim, verified, uuid.UUID(accepted['acceptance_id']),
            checkout_completed_at=completed, checkout_expires_at=expires).unpack()
        result = self.confirmer.confirm(attestation['attestation_id']).unpack()
        from src.ai.core.entitlements import forget
        forget(self.collection.tenant)
        return self._result(operation, 'confirmed', 'trusted_confirmation_recorded', confirmation_id=result['confirmation_id'])

    def cancel(self, operation):
        row = self.collection._owned(operation)
        if row['reservation']['state']!='confirmed':
            raise CollectionBlocked('use_consent_withdrawal')
        gateway=self.checkout_gateway(_binding(row))
        if gateway.binding!=_binding(row): raise CollectionBlocked('original_binding_required')
        gateway.check_cancellation()
        # A cancellation is a durable, one-way stop-renewal request, never local
        # revocation or a refund. An ambiguous write is recovered by GET only.
        receipt=self.dispatches.cancellation(operation,'elect')
        c=receipt['confirmation']
        if receipt['cancellation'].get('confirmed_at'):
            return self._result(operation,'cancellation_recorded','period_end_preserved')
        try:
            result=gateway.cancel(c,submit=receipt['elected'],
                authorize=lambda:self.dispatches.cancellation(operation,'read'))
        except Exception:
            return self._result(operation,'pending','cancellation_recovery_required')
        if result is not True:
            return self._result(operation,'pending','cancellation_recovery_required')
        self.dispatches.cancellation(operation,'record')
        return self._result(operation,'cancellation_recorded','period_end_preserved')

    def progress(self,operation):
        row=self.collection._owned(operation)
        d=self.dispatches.command(operation,'read')
        state='consent_required'
        if row['reservation']['state']=='confirmed':state='confirmed'
        elif row['reservation']['state']!='pending':state='blocked'
        elif row['checkout']['state']=='expired' or d and d['expired_at']:state='expired'
        elif d and d['submitted_at']:
            op=self.observations.read(observation_identity(operation))
            state='conflict' if op and op['has_conflict'] else 'pending'
        binding=_binding(row)
        return self._result(operation,state,'durable_checkpoint_only',provider=binding.provider,
            binding_id=binding.binding_id,environment=binding.environment.value)

    def cleanup(self,operation):
        """Best-effort remote compensation after pre-confirmation withdrawal.

        The local B4 fence remains decisive even if a sender is paused beyond a
        provider lookup. Repeating cleanup can discover and expire its late
        Checkout, but cannot prove remote non-creation or authorize resubmission.
        """
        row=self.collection._owned(operation)
        if row['reservation']['state']=='confirmed':raise CollectionBlocked('subscription_cancellation_required')
        d=self.dispatches.command(operation,'read')
        if d is None:return self._result(operation,'withdrawn','no_dispatch_recorded')
        snapshot=self.collection.consents.read(operation,uuid.UUID(d['presentation_id'])).unpack()
        if snapshot['invalidation'] is None:raise CollectionBlocked('withdrawal_required')
        gateway=self.checkout_gateway(_binding(row))
        if gateway.binding!=_binding(row):raise CollectionBlocked('original_binding_required')
        session=gateway.retrieve(d) if d['provider_checkout_id'] else gateway.recover(d)
        if session is None:return self._result(operation,'pending','late_checkout_recovery_required')
        gateway.validate(session,d)
        if session.state is C.CheckoutState.OPEN:
            gateway.expire(session,d,authorize=lambda:self.dispatches.command(operation,'read'))
            return self._result(operation,'withdrawn','provider_checkout_expired')
        if session.state is C.CheckoutState.COMPLETE:
            if session.subscription is None or not hasattr(gateway,'compensate'):
                return self._result(operation,'blocked','provider_subscription_compensation_required')
            receipt=self.dispatches.compensation(operation,'elect')
            try:
                done=gateway.compensate(session,d,submit=receipt['elected'],
                    authorize=lambda:self.dispatches.compensation(operation,'read'))
            except Exception:done=False
            if not done:return self._result(operation,'pending','provider_subscription_compensation_required')
            self.dispatches.compensation(operation,'record',session.subscription.opaque_id)
            return self._result(operation,'withdrawn','provider_trial_compensated')
        return self._result(operation,'withdrawn','provider_checkout_expired')
