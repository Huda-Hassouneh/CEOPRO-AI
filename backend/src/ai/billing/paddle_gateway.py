"""Paddle Billing v1, TEST only; explicit bound transport, no runtime installation.

API semantics: developer.paddle.com/api-reference/{subscriptions,transactions}.
Paddle is MoR: tax/discount/credit/proration/FX/refund behavior is NOT Stripe's.
The supported money subset is intentionally narrow. Readiness/merchant acceptance
and Customer POST replay capabilities are unproved and never declared supported.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import re
import time
from src.ai.billing import payment_contracts as C


def instant(value):
    if not isinstance(value,str): raise ValueError('Provider timestamp required')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    C._require_aware_time(result)
    return result.astimezone(timezone.utc)


def money(value,currency):
    # Other exponents and tax-inclusive agreements require separate acceptance.
    if currency not in ('USD','EUR','GBP') or type(value) is not str or not re.fullmatch(r'[0-9]+',value):
        raise ValueError('Unsupported precise Paddle money')
    return C.Money(Decimal(value)/100,currency)


def free_card_trial(value,days=14):
    """Normalize documented free-trial fields without accepting paid/cardless trials.

    Older API fixtures contain only interval/frequency. Current Paddle may also
    return explicit requires_payment_method, null unit_price and empty overrides.
    """
    return (type(value) is dict and not set(value)-{'interval','frequency','requires_payment_method','unit_price','unit_price_overrides'}
        and value.get('interval')=='day' and type(value.get('frequency')) is int and value['frequency']==days
        and value.get('requires_payment_method',True) is True and value.get('unit_price') is None
        and value.get('unit_price_overrides',[])==[])


def unique_object(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('Ambiguous JSON')
        result[k]=v
    return result


def _bound_namespace(binding,reader):
    if reader.binding!=binding or reader.api_version!='1':raise ValueError('Original Paddle transport required')
    reader.verify_namespace()
    if reader.binding!=binding or reader.api_version!='1':raise ValueError('Paddle namespace changed')


def _bound_request(binding,reader,method,path,body=None,*,params=None):
    if reader.binding!=binding or reader.api_version!='1':raise ValueError('Original Paddle transport required')
    value=reader.request(method,path,body,params=params)
    if reader.binding!=binding or reader.api_version!='1':raise ValueError('Paddle namespace changed')
    return deepcopy(value)


class PaddleWebhookDecoder:
    signature_header='Paddle-Signature'
    def __init__(self,binding,secret,*,clock=time.time):
        if binding.provider!='paddle' or binding.environment is not C.GatewayEnvironment.TEST or not secret:
            raise ValueError('Explicit TEST Paddle endpoint required')
        self.binding,self._secret,self._clock=binding,secret.encode(),clock

    def decode(self,payload,signature):
        try:
            if type(payload) is not bytes or len(payload)>1048576:raise ValueError()
            parts=[p.strip().split('=',1) for p in signature.split(';')]
            stamps=[v for k,v in parts if k=='ts'];digests=[v for k,v in parts if k=='h1']
            if len(stamps)!=1 or not stamps[0].isdigit() or abs(self._clock()-int(stamps[0]))>5:raise ValueError()
            expected=hmac.new(self._secret,stamps[0].encode()+b':'+payload,hashlib.sha256).hexdigest()
            if not any(hmac.compare_digest(expected,d) for d in digests):raise ValueError()
            raw=json.loads(payload,object_pairs_hook=unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
            eid,kind,when,data=raw['event_id'],raw['event_type'],instant(raw['occurred_at']),raw['data']
            if not isinstance(eid,str) or not eid.startswith('evt_') or not isinstance(data,dict):raise ValueError()
            ref=lambda v:C.ProviderReference('paddle',v,binding=self.binding) if v else None
            sub=ref(data['id']) if kind.startswith('subscription.') else ref(data.get('subscription_id'))
            transaction=ref(data['id']) if kind.startswith('transaction.') else None
            mapped=(C.PaymentEventKind.INVOICE_SETTLED if kind=='transaction.completed' else
                C.PaymentEventKind.INVOICE_FAILED if kind in ('transaction.payment_failed','transaction.past_due') else
                C.PaymentEventKind.SUBSCRIPTION_CHANGED if kind.startswith('subscription.') else C.PaymentEventKind.UNKNOWN)
            return C.VerifiedPaymentEvent('paddle',eid,mapped,when,ref(data.get('customer_id')),sub,
                None,transaction,None,payload,raw,binding=self.binding)
        except Exception:
            raise C.InvalidPaymentWebhook('Invalid Paddle notification') from None


def notification_digest(event):
    # Delivery notification_id may vary for the same immutable event. Preserve
    # original signed bytes in the DTO, commit the entire immutable event core.
    if event.provider!='paddle':return 'sha256:'+hashlib.sha256(event.raw_payload).hexdigest()
    core={k:event.raw_evidence[k] for k in ('event_id','event_type','occurred_at','data')}
    return 'sha256:'+hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class BoundPaddleTransport:
    api_version='1'
    origin='https://sandbox-api.paddle.com'
    def __init__(self,binding,api_key,*,client=None):
        if binding.provider!='paddle' or binding.environment is not C.GatewayEnvironment.TEST or not api_key.startswith('pdl_sdbx_apikey_'):
            raise ValueError('Original sandbox credential required')
        import httpx
        self.binding=binding
        self._key=api_key
        self._client=client or httpx.Client(timeout=5,follow_redirects=False)

    def request(self,method,path,body=None,*,params=None):
        listing = method == 'GET' and path in ('/customers','/transactions')
        if method not in ('GET','POST','PATCH') or not re.fullmatch(r'/(account|customers|customers/[a-zA-Z0-9_]+|transactions|prices/[a-zA-Z0-9_]+|subscriptions/[a-zA-Z0-9_]+(?:/cancel)?|transactions/[a-zA-Z0-9_]+)',path):
            raise ValueError('Unsupported Paddle operation')
        if listing:
            allowed={'after','per_page','status','email'} if path=='/customers' else {'after','per_page','customer_id'}
            if not params or set(params)-allowed:raise ValueError('Unsupported Paddle list query')
        elif params is not None and (params!={'include':'adjustments'} or not path.startswith('/transactions/')):
            raise ValueError('Unsupported Paddle query')
        try:
            response=self._client.request(method,self.origin+path,json=body,params=params,
                headers={'Authorization':'Bearer '+self._key,'Paddle-Version':'1'},timeout=5,follow_redirects=False)
            if response.status_code not in ((200,201) if method=='POST' else (200,)):raise ValueError()
            result=response.json();data=result['data']
            if listing:
                more=result['meta']['pagination']['has_more']
                if type(data) is not list or type(more) is not bool:raise ValueError()
                return deepcopy(dict(items=data,has_more=more))
            if type(data) is not dict:raise ValueError()
            return deepcopy(data)
        except Exception:
            raise C.PaymentProviderError(C.ProviderOperationOutcome.UNAVAILABLE if method=='GET' else C.ProviderOperationOutcome.OUTCOME_UNKNOWN) from None

    def verify_namespace(self):
        if self.request('GET','/account')['id']!=self.binding.merchant_account_id:
            raise ValueError('Original Paddle account required')


class PaddleVerificationGateway:
    def __init__(self,binding,reader,*,clock=lambda:datetime.now(timezone.utc)):
        if binding.provider!='paddle' or reader.binding!=binding or binding.environment is not C.GatewayEnvironment.TEST:
            raise ValueError('Original TEST Paddle reader required')
        self.binding,self.reader,self.clock=binding,reader,clock

    def _read(self,*args,**kwargs):return _bound_request(self.binding,self.reader,*args,**kwargs)

    def ref(self,value):return C.ProviderReference('paddle',value,binding=self.binding)

    def _subscription(self,request):
        s=self._read('GET','/subscriptions/'+request.subscription.opaque_id)
        if s['id']!=request.subscription.opaque_id or s['customer_id']!=request.customer.opaque_id or s.get('collection_mode')!='automatic':raise ValueError('Subscription lineage conflict')
        items=s['items']
        if len(items)!=1 or s.get('discount') is not None:raise ValueError('Unsupported subscription adjustments')
        item=items[0];p=item['price'];cycle=p['billing_cycle'];quantity=item['quantity']
        if (type(quantity) is not int or quantity!=1 or cycle['interval'] not in ('month','year')
                or type(cycle['frequency']) is not int or cycle['frequency']<=0 or p.get('unit_price_overrides')
                or p.get('quantity',{}).get('minimum',1)>1):raise ValueError('Unsupported recurring price')
        terms=C.ObservedRecurringTerms(money(p['unit_price']['amount'],p['unit_price']['currency_code']),
            cycle['frequency']*(12 if cycle['interval']=='year' else 1),quantity,self.ref(p['id']))
        state={'canceled':'cancelled'}.get(s['status'],s['status'])
        state=C.SubscriptionState(state)
        period=s.get('current_billing_period');start=instant(period['starts_at']) if period else None;end=instant(period['ends_at']) if period else None
        change=s.get('scheduled_change')
        if change and (change['action']!='cancel' or end is None or instant(change['effective_at'])!=end):raise ValueError('Unsupported scheduled change')
        return s,dict(customer=request.customer,subscription=request.subscription,subscription_state=state,terms=terms,
            period_start=start,period_end=end,cancel_at_period_end=bool(change),
            cancelled_at=instant(s['canceled_at']) if s.get('canceled_at') else None)

    def _settlement(self,request,transaction,terms):
        t=self._read('GET','/transactions/'+transaction.opaque_id,params={'include':'adjustments'})
        if (t['id']!=transaction.opaque_id or t['customer_id']!=request.customer.opaque_id
                or t['subscription_id']!=request.subscription.opaque_id):raise ValueError('Transaction lineage conflict')
        if t['status']!='completed':return None
        totals=t['details']['totals'];currency=t['currency_code']
        if (t.get('collection_mode')!='automatic' or t.get('origin')!='subscription_recurring'
                or t.get('discount_id') or t.get('adjustments',[])!=[] or t.get('revised_at')
                or any(Decimal(totals[k])!=0 for k in ('discount','tax','credit','credit_to_balance'))):
            raise ValueError('Unsupported settlement adjustments')
        items=t['items'];lines=t['details']['line_items']
        if len(items)!=1 or len(lines)!=1 or items[0]['price']['id']!=terms.price.opaque_id or items[0]['quantity']!=1 or lines[0].get('proration') is not None:
            raise ValueError('Transaction terms conflict')
        line=lines[0]
        if (line.get('price_id')!=terms.price.opaque_id or type(line.get('quantity')) is not int or line['quantity']!=1
                or Decimal(line['tax_rate'])!=0
                or money(items[0]['price']['unit_price']['amount'],items[0]['price']['unit_price']['currency_code'])!=terms.amount):
            raise ValueError('Calculated line scope conflict')
        for detail in (line['unit_totals'],line['totals']):
            if (money(detail['subtotal'],currency)!=terms.amount or money(detail['total'],currency)!=terms.amount
                    or Decimal(detail['discount'])!=0 or Decimal(detail['tax'])!=0):
                raise ValueError('Calculated financial facts conflict')
        amount=money(totals['total'],currency)
        if (amount!=terms.amount or money(totals['grand_total'],currency)!=amount
                or money(totals['subtotal'],currency)!=amount):raise ValueError('Exact settlement amount required')
        captured=[p for p in t['payments'] if p['status']=='captured']
        if not captured or sum((money(p['amount'],currency).amount for p in captured),Decimal(0))!=amount.amount or amount.amount<=0:
            raise ValueError('Captured payment required')
        paid=max(instant(p['captured_at']) for p in captured)
        period=t['billing_period']
        return C.ObservedSettlement(transaction,request.customer,request.subscription,amount,C.PaymentState.PAID,True,False,paid,
            ((instant(period['starts_at']),instant(period['ends_at'])),),purpose=C.SettlementPurpose.RENEWAL)

    def observe_subscription(self,request,*,event=None):
        caps=C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED)
        facts={};outcome=C.VerificationOutcome.UNAVAILABLE
        try:
            if type(request) is not C.SubscriptionObservationRequest or request.binding!=self.binding:raise ValueError()
            _bound_namespace(self.binding,self.reader)
            s,facts=self._subscription(request)
            if event is not None and event.invoice is not None:
                if event.binding!=self.binding:raise ValueError()
                facts['settlement']=self._settlement(request,event.invoice,facts['terms'])
            # trialing needs exact original trial boundaries; Paddle's current
            # period alone does not independently establish the agreed trial.
            outcome=C.VerificationOutcome.PENDING if facts['subscription_state'] is C.SubscriptionState.TRIALING else C.VerificationOutcome.VERIFIED
        except (ValueError,KeyError,TypeError,ArithmeticError):
            facts={};outcome=C.VerificationOutcome.CONFLICT
        except Exception:
            facts={};outcome=C.VerificationOutcome.UNAVAILABLE
        return C.ProviderVerificationObservation(request,C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,
            request.subscription,self.clock(),'paddle-billing-v1','1'),outcome,caps,**facts)

    def observe_trial_checkout(self,request):
        # Exact provider associations and trial dates can be observed without
        # claiming reusable off-session authority from a saved/attached card.
        facts={};outcome=C.VerificationOutcome.UNAVAILABLE
        caps=C.GatewayCapabilities(authoritative_reconciliation=C.CapabilityState.SUPPORTED)
        try:
            if type(request) is not C.TrialObservationRequest or request.binding!=self.binding:raise ValueError()
            _bound_namespace(self.binding,self.reader)
            t=self._read('GET','/transactions/'+request.checkout.opaque_id,params={'include':'adjustments'})
            if (t['id']!=request.checkout.opaque_id or t['customer_id']!=request.customer.opaque_id
                    or t.get('collection_mode')!='automatic' or (t.get('custom_data') or {}).get('keel_journey_operation')!=request.checkout_attempt_id
                    or (t.get('custom_data') or {}).get('tenant_id')!=request.tenant_id):raise ValueError('Original trial transaction required')
            state=C.CheckoutState.COMPLETE if t['status']=='completed' else C.CheckoutState.EXPIRED if t['status']=='canceled' else C.CheckoutState.OPEN
            facts=dict(customer=request.customer,checkout=request.checkout,checkout_state=state)
            outcome=C.VerificationOutcome.PENDING
            if state is C.CheckoutState.EXPIRED:outcome=C.VerificationOutcome.CONFLICT
            elif state is C.CheckoutState.COMPLETE:
                sub=self.ref(t['subscription_id'])
                if request.subscription is not None and request.subscription!=sub:raise ValueError('Original subscription required')
                sr=C.SubscriptionObservationRequest(request.tenant_id,self.binding,request.customer,sub)
                subscription,observed=self._subscription(sr)
                terms=observed['terms'];items=t['items'];totals=t['details']['totals']
                if (request.expected_terms is None or terms!=request.expected_terms or t['currency_code']!=terms.amount.currency
                        or len(items)!=1 or items[0]['price']['id']!=terms.price.opaque_id or type(items[0]['quantity']) is not int or items[0]['quantity']!=1
                        or money(items[0]['price']['unit_price']['amount'],items[0]['price']['unit_price']['currency_code'])!=terms.amount
                        # This lookup explicitly requests include=adjustments.
                        # Paddle omits the relation when no adjustments exist;
                        # an explicit null/malformed/nonempty relation is refused.
                        or t.get('discount_id') or t.get('adjustments',[])!=[] or t.get('revised_at')
                        or any(Decimal(totals[k])!=0 for k in ('total','grand_total','subtotal','tax','discount','credit','credit_to_balance'))):
                    raise ValueError('Unsupported initial trial financial facts')
                trial=subscription['items'][0]['trial_dates']
                start,end=instant(trial['starts_at']),instant(trial['ends_at'])
                from datetime import timedelta
                if end-start!=timedelta(days=request.approved_terms.trial_duration_days) or observed['subscription_state'] is not C.SubscriptionState.TRIALING:
                    raise ValueError('Exact original trial required')
                facts.update(observed,trial=C.ObservedTrialWindow(start,end,end))
                # A completed $0 transaction establishes no recurring authority.
                # Paddle's saved-method API exposes Customer association, not an
                # independently verified mandate bound to this subscription.
                facts['recurring_authorization']=C.RecurringAuthorizationEvidence(request.customer,sub)
        except (ValueError,KeyError,TypeError,ArithmeticError):facts={};outcome=C.VerificationOutcome.CONFLICT
        except Exception:facts={};outcome=C.VerificationOutcome.UNAVAILABLE
        return C.ProviderVerificationObservation(request,C.ObservationProvenance(C.ObservationSource.AUTHORITATIVE_LOOKUP,
            request.checkout,self.clock(),'paddle-billing-v1','1'),outcome,caps,**facts)


class PaddleCancellationGateway:
    def __init__(self,binding,transport,*,merchant_reviewed=False):
        if binding.provider!='paddle' or transport.binding!=binding or binding.environment is not C.GatewayEnvironment.TEST:
            raise ValueError('Original TEST Paddle transport required')
        self.binding,self.transport,self.merchant_reviewed=binding,transport,merchant_reviewed

    def _read(self,*args,**kwargs):return _bound_request(self.binding,self.transport,*args,**kwargs)

    def check_cancellation(self):
        if self.merchant_reviewed is not True:raise ValueError('Paddle merchant cancellation acceptance required')

    def cancel(self,confirmation,*,submit,authorize,immediately=False):
        self.check_cancellation();_bound_namespace(self.binding,self.transport)
        path='/subscriptions/'+confirmation['provider_subscription_id']
        def valid(value):
            if value['id']!=confirmation['provider_subscription_id'] or value['customer_id']!=confirmation['provider_customer_id']:raise ValueError('Cancellation lineage conflict')
        current=self._read('GET',path);valid(current)
        if current['status']=='canceled':return True
        change=current.get('scheduled_change')
        if not immediately and change and change['action']=='cancel':return True
        if change:raise ValueError('Existing schedule requires review')
        if not submit:return False
        if not immediately and current['status'] not in ('active','trialing','past_due'):raise ValueError('Period-end cancellation unsupported')
        before=current.get('current_billing_period');authorize()
        updated=self._read('POST',path+'/cancel',{'effective_from':'immediately' if immediately else 'next_billing_period'});valid(updated)
        if immediately:return updated['status']=='canceled'
        change=updated.get('scheduled_change')
        return bool(change and change['action']=='cancel' and updated.get('current_billing_period')==before
            and before and instant(change['effective_at'])==instant(before['ends_at']))

    def compensate(self,session,dispatch,*,submit,authorize):
        # The supplying Checkout adapter must validate its original transaction,
        # Customer and operation before returning this scoped session.
        if session.reference.binding!=self.binding or session.customer!=C.ProviderReference('paddle',dispatch['provider_customer_id'],binding=self.binding) or session.subscription is None:
            raise ValueError('Original completed transaction required')
        _bound_namespace(self.binding,self.transport)
        value=self._read('GET','/subscriptions/'+session.subscription.opaque_id)
        if value.get('customer_id')!=dispatch['provider_customer_id'] or value.get('id')!=session.subscription.opaque_id:raise ValueError('Compensation lineage conflict')
        if value['status'] not in ('trialing','canceled'):raise ValueError('Paid compensation requires refund review')
        return self.cancel(dict(provider_subscription_id=session.subscription.opaque_id,provider_customer_id=dispatch['provider_customer_id']),
            submit=submit,authorize=authorize,immediately=True)


class PaddleJourneyGateway(PaddleCancellationGateway):
    """Single elected transaction sender; no invented provider idempotency header.

    The durable Customer contract and merchant-hosted Paddle.js payment page must
    be independently accepted/provisioned. Neither is installed by this module.
    Empty recovery remains unresolved and NEVER authorizes another POST.
    """
    def __init__(self,binding,transport,*,merchant_reviewed=False,approved_checkout_origin=None,checkout_page_ready=False):
        super().__init__(binding,transport,merchant_reviewed=merchant_reviewed)
        self.approved_checkout_origin=approved_checkout_origin;self.checkout_page_ready=checkout_page_ready

    def check_policy(self,policy):
        if self.merchant_reviewed is not True or self.checkout_page_ready is not True or not self.approved_checkout_origin or policy.get('trial_start_mode')!='provider_confirmed_trial_start':
            raise ValueError('Approved Paddle consent and installed payment page required')

    def prepare(self,row,customer,policy,urls):
        from urllib.parse import urlsplit
        self.check_policy(policy)
        r=row['reservation'];terms=r['approved_terms']
        if customer.binding!=self.binding or terms['binding']['binding_id']!=self.binding.binding_id:raise ValueError('Original Paddle binding required')
        url=urls[0];parts=urlsplit(url)
        if parts.scheme!='https' or parts.username or parts.fragment or parts.scheme+'://'+parts.netloc!=self.approved_checkout_origin:raise ValueError('Approved merchant payment page required')
        _bound_namespace(self.binding,self.transport)
        price=self._read('GET','/prices/'+r['provider_price_id'])
        trial=price.get('trial_period');cycle=price.get('billing_cycle');unit=price.get('unit_price')
        if (price.get('id')!=r['provider_price_id'] or price.get('status')!='active' or not free_card_trial(trial)
                or r['trial_duration_days']!=14 or not cycle or cycle['interval'] not in ('month','year')
                or type(cycle['frequency']) is not int or cycle['frequency']*(12 if cycle['interval']=='year' else 1)!=terms['interval_months']
                or not unit or money(unit['amount'],unit['currency_code'])!=C.Money(Decimal(str(terms['approved_amount'])),terms['currency'])
                or price.get('unit_price_overrides')):raise ValueError('Frozen Paddle catalog price conflict')
        payload=dict(items=[dict(price_id=r['provider_price_id'],quantity=1)],customer_id=customer.opaque_id,
            collection_mode='automatic',checkout=dict(url=url),custom_data=dict(billing_kind='keel_recurring_journey',keel_journey_operation=r['attempt_id'],tenant_id=r['tenant_id']))
        return dict(approved_terms=terms,customer=customer.opaque_id,idempotency_key='keel-trial-checkout-'+r['attempt_id'],transport=payload)

    def validate(self,session,dispatch):
        if (type(session) is not C.CheckoutSnapshot or session.reference.binding!=self.binding or session.customer!=C.ProviderReference('paddle',dispatch['provider_customer_id'],binding=self.binding)
                or session.client_reference!=dispatch['attempt_id'] or not session.is_subscription
                or dispatch.get('provider_checkout_id') not in (None,session.reference.opaque_id)
                or session.subscription is not None and session.subscription.binding!=self.binding):raise ValueError('Original Paddle Checkout lineage required')
        if session.url:
            from urllib.parse import urlsplit,parse_qs
            u=urlsplit(session.url)
            if u.scheme!='https' or u.username or u.scheme+'://'+u.netloc!=self.approved_checkout_origin or parse_qs(u.query).get('_ptxn')!=[session.reference.opaque_id]:raise ValueError('Original merchant Checkout URL required')

    def _snapshot(self,value,d):
        metadata=value.get('custom_data') or {};expected=d['request']['transport']
        items=value.get('items');terms=d['request']['approved_terms']
        if (not isinstance(items,list) or len(items)!=1 or type(items[0].get('quantity')) is not int or items[0]['quantity']!=1
                or (items[0].get('price') or {}).get('id')!=terms['provider_price_id']
                or value.get('currency_code')!=terms['currency'] or value.get('discount_id')):
            raise ValueError('Frozen transaction commercial scope required')
        price=items[0]['price'];cycle=price.get('billing_cycle') or {};unit=price.get('unit_price') or {}
        if (money(unit.get('amount'),unit.get('currency_code'))!=C.Money(Decimal(str(terms['approved_amount'])),terms['currency'])
                or cycle.get('interval') not in ('month','year') or type(cycle.get('frequency')) is not int
                or cycle['frequency']*(12 if cycle['interval']=='year' else 1)!=terms['interval_months']
                or not free_card_trial(price.get('trial_period'))):raise ValueError('Frozen transaction price changed')
        if metadata!=expected['custom_data'] or value.get('collection_mode')!='automatic' or value.get('customer_id')!=d['provider_customer_id']:
            raise ValueError('Original transaction scope required')
        ref=lambda v:C.ProviderReference('paddle',v,binding=self.binding) if v else None
        state=C.CheckoutState.COMPLETE if value['status']=='completed' else C.CheckoutState.EXPIRED if value['status']=='canceled' else C.CheckoutState.OPEN
        snapshot=C.CheckoutSnapshot(ref(value['id']),state,C.PaymentState.UNKNOWN,ref(value['customer_id']),ref(value.get('subscription_id')),
            (value.get('checkout') or {}).get('url'),metadata.get('keel_journey_operation'),metadata,True)
        self.validate(snapshot,d);return snapshot

    def submit(self,d,*,authorize):
        self.check_policy({'trial_start_mode':'provider_confirmed_trial_start'})
        f=d['request']['approved_terms'];p=d['request']['transport']
        if (d['binding_id']!=self.binding.binding_id or f['tenant_id']!=d['tenant_id'] or f['binding']!=dict(provider=self.binding.provider,environment=self.binding.environment.value,merchant_account_id=self.binding.merchant_account_id,binding_id=self.binding.binding_id)
                or d['request']['customer']!=d['provider_customer_id'] or d['request']['idempotency_key']!='keel-trial-checkout-'+d['attempt_id']
                or p!=dict(items=[dict(price_id=f['provider_price_id'],quantity=1)],customer_id=d['provider_customer_id'],collection_mode='automatic',checkout=p.get('checkout'),
                    custom_data=dict(billing_kind='keel_recurring_journey',keel_journey_operation=d['attempt_id'],tenant_id=d['tenant_id']))):raise ValueError('Frozen transaction conflict')
        from urllib.parse import urlsplit
        u=urlsplit(p['checkout']['url'])
        if u.scheme!='https' or u.username or u.fragment or u.scheme+'://'+u.netloc!=self.approved_checkout_origin:raise ValueError('Frozen checkout page conflict')
        _bound_namespace(self.binding,self.transport);receipt=authorize()
        if receipt.get('submitted_at') is None or receipt['request']!=d['request']:raise ValueError('Elected original submission required')
        return self._snapshot(self._read('POST','/transactions',deepcopy(p)),d)

    def retrieve(self,d):
        _bound_namespace(self.binding,self.transport)
        return self._snapshot(self._read('GET','/transactions/'+d['provider_checkout_id']),d)

    def recover(self,d):
        if d.get('provider_checkout_id'):return self.retrieve(d)
        _bound_namespace(self.binding,self.transport)
        # All statuses, every bounded page; metadata discovery is never proof of
        # non-creation. Ambiguous/incomplete scans cannot elect another sender.
        matches=[]
        for value in _pages(self.binding,self.transport,'/transactions',{'customer_id':d['provider_customer_id'],'per_page':30}):
            if (value.get('custom_data') or {}).get('keel_journey_operation')==d['attempt_id']:
                matches.append(value)
        if len(matches)!=1:return None
        value=self._read('GET','/transactions/'+matches[0]['id'])
        if value.get('id')!=matches[0]['id']:raise ValueError('Transaction discovery changed')
        return self._snapshot(value,d)

    def expire(self,session,d,*,authorize):
        self.validate(session,d);_bound_namespace(self.binding,self.transport);authorize()
        result=self._snapshot(self._read('PATCH','/transactions/'+session.reference.opaque_id,{'status':'canceled'}),d)
        if result.state is not C.CheckoutState.EXPIRED:raise ValueError('Paddle cancellation unconfirmed')


def _pages(binding,reader,path,params):
    """Never follow remote next URLs; scoped cursor reads only. Bounded failure
    is unresolved, never permission to create again or accept a partial scan.
    """
    query=dict(params);seen=set()
    for _ in range(100):
        page=_bound_request(binding,reader,'GET',path,params=query)
        if type(page.get('items')) is not list or type(page.get('has_more')) is not bool:raise ValueError('Malformed discovery')
        for value in page['items']:
            identifier=value.get('id')
            if not isinstance(identifier,str) or identifier in seen:raise ValueError('Ambiguous discovery cursor')
            seen.add(identifier)
            yield value
        if not page['has_more']:return
        if not page['items']:raise ValueError('Empty discovery cursor')
        query['after']=page['items'][-1]['id']
    raise ValueError('Discovery incomplete')


class PaddleDurableCustomerGateway:
    """Existing durable Customer coordinator, single POST; recovery is GET-only.

    No provider idempotency guarantee is claimed. Migration 176 permits one
    original Paddle dispatch; an empty list NEVER establishes non-creation.
    """
    encoder_version='paddle-customer-v1-single-send'
    def __init__(self,binding,transport,*,merchant_reviewed=False,clock=lambda:datetime.now(timezone.utc)):
        if binding.provider!='paddle' or binding.environment is not C.GatewayEnvironment.TEST or transport.binding!=binding:
            raise ValueError('Original sandbox Customer transport required')
        self.binding,self.transport,self.merchant_reviewed,self.clock=binding,transport,merchant_reviewed,clock

    def prepare_customer(self,intent):
        if intent.binding!=self.binding:raise ValueError('Original Customer binding required')
        payload=dict(email=intent.email,name=intent.company_name,custom_data=dict(tenant_id=intent.tenant_id,keel_customer_operation_id=intent.operation_id))
        return C.FrozenCustomerRequest(intent.tenant_id,intent.operation_id,self.binding,'keel-customer-'+intent.operation_id,
            intent.logical_request(),C.CustomerPayload.freeze(payload),self.encoder_version,'1',C.CapabilityState.UNKNOWN,0,5)

    def _check(self,r):
        payload=r.transport.unpack();logical=r.logical.unpack()
        if (r.binding!=self.binding or r.encoder_version!=self.encoder_version or r.api_version!='1'
                or r.idempotency_key!='keel-customer-'+r.operation_id or r.replay_support is not C.CapabilityState.UNKNOWN
                or r.replay_window_seconds!=0 or r.dispatch_timeout_seconds!=5
                or payload!=dict(email=logical['email'],name=logical['name'],custom_data=dict(tenant_id=r.tenant_id,keel_customer_operation_id=r.operation_id))):
            raise ValueError('Frozen Customer request conflict')
        _bound_namespace(self.binding,self.transport)

    def _snapshot(self,value,r,kind):
        if (value.get('status')!='active' or not isinstance(value.get('id'),str) or not value['id'].startswith('ctm_')
                or value.get('custom_data')!=r.transport.unpack()['custom_data']
                or value.get('email')!=r.logical.unpack()['email'] or value.get('name')!=r.logical.unpack()['name']):
            raise ValueError('Customer lineage conflict')
        return C.CustomerSnapshot(C.ProviderReference('paddle',value['id'],binding=self.binding),r.tenant_id,r.operation_id,kind,value['id'])

    def submit_customer(self,r,*,deadline,authorize):
        if self.merchant_reviewed is not True:raise ValueError('Merchant Customer acceptance required')
        self._check(r)
        if (deadline-self.clock()).total_seconds()<=7:raise ValueError('Customer dispatch budget expired')
        receipt=authorize()
        if (receipt.get('state')!='submitted' or receipt.get('dispatch_count')!=1
                or receipt.get('operation_id')!=r.operation_id or receipt.get('tenant_id')!=r.tenant_id
                or receipt.get('binding')!=dict(provider='paddle',environment='test',merchant_account_id=self.binding.merchant_account_id,binding_id=self.binding.binding_id)
                or receipt.get('idempotency_key')!=r.idempotency_key
                or receipt.get('transport_request')!=r.transport.canonical.decode('utf-8')
                or instant(receipt['replay_deadline'])!=deadline or (deadline-self.clock()).total_seconds()<=7):
            raise ValueError('Original single-sender authorization required')
        return self._snapshot(_bound_request(self.binding,self.transport,'POST','/customers',r.transport.unpack()),r,'create_response')

    def retrieve_customer(self,reference,r):
        self._check(r)
        if reference.binding!=self.binding:raise ValueError('Original Customer reference required')
        value=_bound_request(self.binding,self.transport,'GET','/customers/'+reference.opaque_id)
        snapshot=self._snapshot(value,r,'retrieved')
        if snapshot.reference!=reference:raise ValueError('Customer reference changed')
        return snapshot

    def recover_customer(self,r):
        self._check(r);matches=[]
        for value in _pages(self.binding,self.transport,'/customers',dict(email=r.logical.unpack()['email'],status='active,archived',per_page=200)):
            metadata=value.get('custom_data') or {}
            if metadata.get('keel_customer_operation_id')==r.operation_id:
                matches.append(value)
        if len(matches)>1:status=C.CustomerRecoveryStatus.CONFLICT;snapshot=None
        elif not matches:status=C.CustomerRecoveryStatus.INCONCLUSIVE;snapshot=None
        else:
            ref=C.ProviderReference('paddle',matches[0]['id'],binding=self.binding)
            snapshot=self.retrieve_customer(ref,r);status=C.CustomerRecoveryStatus.MATCH
        return C.CustomerRecoveryResult(status,self.binding,r.tenant_id,r.operation_id,snapshot)
