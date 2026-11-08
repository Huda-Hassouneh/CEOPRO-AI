"""Dormant original-binding Stripe Checkout; explicit transport, no global SDK.

Only the approved checkout-completion start rule is implemented. No promotions,
inline Custom prices, taxes or provider consent are guessed. Additional provider
consent requirements must be supplied by the merchant-approved adapter policy.
"""
from copy import deepcopy
from urllib.parse import urlsplit
from src.ai.billing import payment_contracts as C
from src.ai.billing.authenticated_consent import CollectionBlocked


class StripeJourneyGateway:
    def __init__(self, binding, transport, *, provider_consent_reviewed=False, cancellation_supported=False):
        if binding.provider != 'stripe' or transport.binding != binding:
            raise CollectionBlocked('original_stripe_transport_required')
        if binding.environment is not C.GatewayEnvironment.TEST:
            raise CollectionBlocked('live_journey_not_authorized')
        self.binding, self.transport = binding, transport
        self.provider_consent_reviewed = provider_consent_reviewed
        self.cancellation_supported = cancellation_supported

    def prepare(self, row, customer, policy, urls):
        from src.ai.billing.trial_coordinator import _binding
        r = row['reservation']
        if (_binding(row) != self.binding or customer.binding != self.binding
                or policy.get('trial_start_mode') != 'checkout_completion'
                or self.provider_consent_reviewed is not True):
            raise CollectionBlocked('approved_trial_start_and_provider_consent_required')
        if any(urlsplit(u).scheme != 'https' or not urlsplit(u).hostname or urlsplit(u).username for u in urls) or len(urls)!=2:
            raise CollectionBlocked('server_https_return_urls_required')
        metadata = dict(billing_kind='keel_recurring_journey', keel_journey_operation=r['attempt_id'], tenant_id=r['tenant_id'])
        payload = dict(mode='subscription', customer=customer.opaque_id, client_reference_id=r['attempt_id'],
            line_items=[dict(price=r['provider_price_id'], quantity=1)], metadata=metadata,
            subscription_data=dict(metadata=metadata, trial_period_days=r['trial_duration_days'],
                trial_settings=dict(end_behavior=dict(missing_payment_method='cancel'))),
            payment_method_collection='always', payment_method_types=['card'], allow_promotion_codes=False,
            success_url=urls[0], cancel_url=urls[1])
        return dict(approved_terms=r['approved_terms'], customer=customer.opaque_id,
            idempotency_key='keel-trial-checkout-'+r['attempt_id'], transport=payload)

    def check_policy(self,policy):
        if self.binding.environment is not C.GatewayEnvironment.TEST:
            raise CollectionBlocked('live_confirmation_not_supported')
        if policy.get('trial_start_mode')!='checkout_completion' or self.provider_consent_reviewed is not True:
            raise CollectionBlocked('approved_trial_start_and_provider_consent_required')

    def validate(self, session, dispatch):
        metadata = dispatch['request']['transport']['metadata']
        if (type(session) is not C.CheckoutSnapshot or session.reference.binding != self.binding
                or session.customer != C.ProviderReference('stripe', dispatch['provider_customer_id'], binding=self.binding)
                or session.client_reference != dispatch['attempt_id'] or not session.is_subscription
                or any(session.metadata.get(k)!=v for k,v in metadata.items())
                or dispatch.get('provider_checkout_id') not in (None, session.reference.opaque_id)
                or session.subscription is not None and session.subscription.binding != self.binding):
            raise CollectionBlocked('provider_checkout_lineage_conflict')
        if session.url and (urlsplit(session.url).scheme != 'https' or urlsplit(session.url).hostname != 'checkout.stripe.com'):
            raise CollectionBlocked('provider_checkout_url_conflict')

    def _snapshot(self, value):
        if value.get('livemode') is not (self.binding.environment is C.GatewayEnvironment.LIVE):
            raise CollectionBlocked('provider_environment_conflict')
        ref = lambda v: C.ProviderReference('stripe', v, binding=self.binding) if v else None
        return C.CheckoutSnapshot(ref(value['id']), C.CheckoutState(value['status']), C.PaymentState.UNKNOWN,
            ref(value.get('customer')), ref(value.get('subscription')), value.get('url'),
            value.get('client_reference_id'), value.get('metadata') or {}, value.get('mode')=='subscription')

    def submit(self, dispatch, *, authorize):
        self.check_request(dispatch)
        self.transport.verify_namespace()
        receipt = authorize()  # Rechecks consent/revocation; commits before POST.
        if receipt['submitted_at'] is None or receipt['request'] != dispatch['request']:
            raise CollectionBlocked('frozen_dispatch_required')
        # The single elected caller alone invokes this method. No automatic SDK
        # retry, no replacement key. Remote compensation remains necessary after
        # withdrawal racing an already authorized network submission.
        value = self.transport.checkout_create(deepcopy(dispatch['request']['transport']), dispatch['request']['idempotency_key'])
        result = self._snapshot(value)
        self.validate(result, dispatch)
        return result

    def retrieve(self, dispatch):
        self.transport.verify_namespace()
        return self._snapshot(self.transport.checkout_retrieve(dispatch['provider_checkout_id']))

    def recover(self, dispatch):
        self.transport.verify_namespace()
        # A zero/multiple-match list proves neither non-creation nor a new send.
        matches = self.transport.checkout_list(dispatch['provider_customer_id'])
        candidates = [v for v in matches if (v.get('metadata') or {}).get('keel_journey_operation')==dispatch['attempt_id']]
        if len(candidates)!=1:
            return None
        result = self._snapshot(self.transport.checkout_retrieve(candidates[0]['id']))
        self.validate(result, dispatch)
        return result

    def expire(self,session,dispatch,*,authorize):
        self.transport.verify_namespace();authorize()
        value=self._snapshot(self.transport.checkout_expire(session.reference.opaque_id,'keel-expire-'+dispatch['attempt_id']))
        self.validate(value,dispatch)
        if value.state is not C.CheckoutState.EXPIRED:raise CollectionBlocked('checkout_expiry_unconfirmed')

    def cancel(self,confirmation,*,submit,authorize):
        if self.cancellation_supported is not True:raise CollectionBlocked('bound_cancellation_unsupported')
        self.transport.verify_namespace()
        sid=confirmation['provider_subscription_id']
        value=self.transport.subscription_retrieve(sid)
        def valid(v):
            if (v.get('id')!=sid or v.get('customer')!=confirmation['provider_customer_id']
                    or v.get('livemode') is not (self.binding.environment is C.GatewayEnvironment.LIVE)):
                raise CollectionBlocked('cancellation_lineage_conflict')
        valid(value)
        if value.get('cancel_at_period_end') is True:return True
        if not submit:return False
        before=value.get('current_period_end')
        # No schedule release or immediate cancellation is silently composed.
        if before is None or value.get('schedule'):raise CollectionBlocked('cancellation_schedule_unsupported')
        authorize()
        updated=self.transport.subscription_cancel(sid,'keel-cancel-'+confirmation['confirmation_id'])
        valid(updated)
        if updated.get('current_period_end')!=before:raise CollectionBlocked('cancellation_period_changed')
        return updated.get('cancel_at_period_end') is True

    def compensate(self,session,dispatch,*,submit,authorize):
        self.check_cancellation();self.validate(session,dispatch);self.transport.verify_namespace()
        if session.state is not C.CheckoutState.COMPLETE or session.subscription is None:
            raise CollectionBlocked('completed_original_checkout_required')
        sid=session.subscription.opaque_id
        def valid(v):
            if v.get('id')!=sid or v.get('customer')!=dispatch['provider_customer_id'] or v.get('livemode') is not False:
                raise CollectionBlocked('compensation_lineage_conflict')
        value=self.transport.subscription_retrieve(sid);valid(value)
        if value.get('status')=='canceled':return True
        if value.get('status')!='trialing' or value.get('schedule'):
            raise CollectionBlocked('paid_or_scheduled_compensation_requires_review')
        if not submit:return False
        authorize()
        result=self.transport.subscription_cancel_immediately(sid,'keel-withdraw-'+dispatch['attempt_id']);valid(result)
        return result.get('status')=='canceled'

    def check_cancellation(self):
        if self.binding.environment is not C.GatewayEnvironment.TEST:
            raise CollectionBlocked('live_cancellation_not_authorized')
        if self.cancellation_supported is not True:raise CollectionBlocked('bound_cancellation_unsupported')

    def check_request(self,dispatch):
        """Revalidate persisted transport before a write; never re-encode it."""
        request=dispatch['request'];terms=request['approved_terms'];p=request['transport']
        b=terms['binding']
        if (b != dict(provider=self.binding.provider,environment=self.binding.environment.value,
                merchant_account_id=self.binding.merchant_account_id,binding_id=self.binding.binding_id)
            or dispatch['binding_id']!=self.binding.binding_id or terms['tenant_id']!=dispatch['tenant_id']
            or request['customer']!=dispatch['provider_customer_id']
            or request['idempotency_key']!='keel-trial-checkout-'+dispatch['attempt_id']):
            raise CollectionBlocked('frozen_checkout_scope_conflict')
        metadata=dict(billing_kind='keel_recurring_journey',keel_journey_operation=dispatch['attempt_id'],tenant_id=dispatch['tenant_id'])
        expected=dict(mode='subscription',customer=dispatch['provider_customer_id'],client_reference_id=dispatch['attempt_id'],
            line_items=[dict(price=terms['provider_price_id'],quantity=1)],metadata=metadata,
            subscription_data=dict(metadata=metadata,trial_period_days=terms['trial_duration_days'],
                trial_settings=dict(end_behavior=dict(missing_payment_method='cancel'))),
            payment_method_collection='always',payment_method_types=['card'],allow_promotion_codes=False,
            success_url=p.get('success_url'),cancel_url=p.get('cancel_url'))
        if p!=expected or terms['trial_duration_days']!=14:
            raise CollectionBlocked('frozen_checkout_transport_conflict')
        for url in (p['success_url'],p['cancel_url']):
            if not isinstance(url,str) or urlsplit(url).scheme!='https' or not urlsplit(url).hostname or urlsplit(url).username:
                raise CollectionBlocked('frozen_return_url_conflict')
