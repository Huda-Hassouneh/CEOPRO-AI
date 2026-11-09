"""Actual local restricted runtime sockets and resolver; synthetic APIs only."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime,timezone
from copy import deepcopy
import json,os,uuid,time,hashlib,hmac
from types import SimpleNamespace
from unittest.mock import Mock
import psycopg2
import pytest
from src.ai.billing import sandbox_runtime as R,payment_contracts as C
from src.ai.billing.customer_operations import CustomerOperationError
from .test_subscription_journey_db import journey,parties,accepted
from .test_customer_contracts import Transport as CustomerTransport
from .test_subscription_journey_db import CheckoutTransport
from .test_paddle_completion import CustomerReader
from .test_recurring_consent_db import fingerprint, restricted_runtime
from .test_sandbox_runtime import configuration
from .test_verification_observations_db import role_password

class StripeTransport(CustomerTransport,CheckoutTransport):
    def __init__(self,binding,*args,**kwargs):
        CustomerTransport.__init__(self,binding);CheckoutTransport.__init__(self,binding)
        self.api_version=kwargs['api_version'];self.replay_window_seconds=kwargs['replay_window_seconds'];self.timeout=5
    def checkout_create(self,payload,key):
        self.sent.append((deepcopy(payload),key))
        value=dict(deepcopy(payload),id='cs_'+payload['client_reference_id'],status='open',livemode=False,url='https://checkout.stripe.com/c/synthetic')
        self.sessions[value['id']]=value
        return value

class PaddleTransport(CustomerReader):
    def __init__(self,binding,key):
        super().__init__(binding);self.transactions=[];self._client=SimpleNamespace(close=Mock())
    def request(self,method,path,body=None,*,params=None):
        if path.startswith('/customers'):return super().request(method,path,body,params=params)
        self.calls.append((method,path,deepcopy(body),deepcopy(params)))
        if path.startswith('/prices/'):
            return dict(id=path.rsplit('/',1)[1],status='active',trial_period=dict(interval='day',frequency=14),billing_cycle=dict(interval='month',frequency=1),unit_price=dict(amount=self.amount,currency_code='USD'))
        if path=='/transactions' and method=='POST':
            price=self.request('GET','/prices/'+body['items'][0]['price_id'])
            value=dict(deepcopy(body),id='txn_'+'a'*26,status='ready',currency_code='USD',items=[dict(quantity=1,price=price)])
            value['checkout']['url']+='&_ptxn='+value['id'];self.transactions.append(value);return deepcopy(value)
        if path=='/transactions':return dict(items=deepcopy(self.transactions),has_more=False)
        if path.startswith('/transactions/'):return deepcopy(self.transactions[0])
        raise AssertionError('Unexpected synthetic Paddle operation')


@pytest.mark.parametrize('provider',['stripe','paddle'])
def test_runtime_uses_real_restricted_sockets_for_customer_checkout_and_signed_identity(owner_db,journey,monkeypatch,provider,client,tmp_path):
    s=journey
    if provider=='paddle':
        with owner_db.cursor() as q:
            q.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
            bid='paddle_'+uuid.uuid4().hex
            q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'paddle','test',%s,true,'SYNTHETIC runtime only')",(bid,bid))
            q.execute("INSERT INTO billing_lifecycle_provider_approvals(binding_id,evidence_reference) VALUES(%s,'SYNTHETIC')",(bid,))
            q.execute("INSERT INTO billing_price_references(binding_id,price_id,provider_price_id,provenance) SELECT %s,price_id,'pri_'||replace(price_id::text,'-',''),'SYNTHETIC' FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL",(bid,))
        # Existing fixture reservation remains untouched. A second synthetic
        # business avoids trying to replace its immutable original binding.
        party=s.parties[1]
    else:party=s.party
    document,env=configuration();document['synthetic_businesses']=[dict(tenant_id=party[0],actor_id=party[1])]
    raw=psycopg2.extensions.parse_dsn(os.environ['BILLING_TEST_DATABASE_URL'])
    env['DATABASE_URL']=f"postgresql://unused@127.0.0.1:{raw['port']}/{raw['dbname']}"
    env.update({variable:role_password(role) for role,variable in R.PASSWORDS.items()})
    if provider=='stripe':binding=s.binding
    else:binding=C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,bid,bid)
    g=next(v for v in document['gateways'] if v['provider']==provider)
    g.update(binding_id=binding.binding_id,merchant_account_id=binding.merchant_account_id,merchant_reviewed=True)
    document['gateways']=[g]
    config=tmp_path/'runtime.json';config.write_text(json.dumps(document),encoding='utf-8');env['KEEL_SANDBOX_CONFIG']=str(config)
    runtime=R.install(client.app,env)
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    # Fixtures supply synthetic policies only after checking the real missing-
    # policy gate. This is never legal or merchant acceptance.
    transports=[]
    if provider=='stripe':
        def transport(*a,**kw):
            if not transports:transports.append(StripeTransport(*a,**kw))
            return transports[0]
        monkeypatch.setattr(R,'BoundCustomerTransport',transport)
    else:
        with owner_db.cursor() as q:
            q.execute("SELECT (amount*100)::integer FROM billing_plan_prices WHERE plan_key='growth' AND period_code='monthly' AND retired_at IS NULL");PaddleTransport.amount=str(q.fetchone()[0])
        def transport(*a,**kw):
            if not transports:transports.append(PaddleTransport(*a,**kw))
            return transports[0]
        monkeypatch.setattr(R,'BoundPaddleTransport',transport)
    operation=s.operation if provider=='stripe' else uuid.uuid4()
    with runtime.journey(SimpleNamespace(tenant_id=party[0],user_id=party[1])) as flow:
        if provider=='paddle':flow.start(operation,'growth','monthly')
        with pytest.raises(ValueError,match='policy_not_approved'):flow.advance(operation,'en')
        assert not transports
        runtime.policies=s.collection.policies;flow.collection.policies=runtime.policies
        p=flow.collection.present(operation,'en')
        flow.collection.accept(operation,'en',uuid.UUID(p['presentation_id']),p['challenge'],True)
        before=fingerprint(owner_db)
        reply=flow.advance(operation,'en');assert reply['state']=='checkout_ready'
        assert flow.advance(operation,'en')['state']=='checkout_ready'
        d=flow.dispatches.command(operation,'read')
        customer=d['provider_customer_id'];checkout=d['provider_checkout_id']
        assert fingerprint(owner_db)==before
    t=transports[0]
    if provider=='stripe':assert sum(isinstance(c,tuple) and c[0]=='create' for c in t.calls)==1 and len(t.sent)==1
    else:assert sum(v[0]=='POST' and v[1]=='/customers' for v in t.calls)==1 and sum(v[0]=='POST' and v[1]=='/transactions' for v in t.calls)==1
    ref=lambda value:C.ProviderReference(provider,value,binding=binding)
    data={'custom_data':{'keel_journey_operation':str(operation),'tenant_id':'untrusted'}} if provider=='paddle' else {'object':{'metadata':{'keel_journey_operation':str(operation),'tenant_id':'untrusted'}}}
    event=C.VerifiedPaymentEvent(provider,'evt_runtime',C.PaymentEventKind.INVOICE_SETTLED if provider=='paddle' else C.PaymentEventKind.CHECKOUT_COMPLETED,
        datetime.now(timezone.utc),ref(customer),None,ref(checkout) if provider=='stripe' else None,ref(checkout) if provider=='paddle' else None,None,b'{}',{'data':data},binding=binding)
    # Actual ceopro_journey_router query + actual initiating-user restricted
    # connections; provider-supplied tenant is never connection context.
    with runtime.resolve(event) as (flow,op,language):
        assert op==operation and flow.collection.tenant==party[0] and flow.collection.actor==party[1] and language=='en'
    with pytest.raises(ValueError):
        with runtime.resolve(replace(event,customer=ref('foreign_customer'))):pytest.fail('Foreign Customer accepted')
    # Use the actual startup-installed HTTP decoder/handler, real routing and
    # B3 persistence. Provider reads are synthetic, incomplete state cannot grant.
    if provider=='stripe':
        class Reader:
            def __init__(self,b,key,*,api_version):self.binding=b;self.api_version=api_version
            def get(self,kind,identifier=None):
                if kind=='account':return dict(object='account',id=binding.merchant_account_id)
                if kind=='balance':return dict(object='balance',livemode=False)
                if kind=='customer':return dict(object='customer',id=customer,livemode=False,metadata=dict(tenant_id=party[0],keel_customer_operation_id=d['customer_operation_id']))
                if kind=='checkout':return dict(object='checkout.session',id=checkout,livemode=False,mode='subscription',status='open',customer=customer)
                raise AssertionError('Unexpected synthetic Stripe read')
        monkeypatch.setattr(R,'BoundStripeReadTransport',Reader)
    route='/billing/trial-journeys/webhook/'+provider
    now=int(time.time())
    core=(dict(id='evt_http_runtime',type='checkout.session.completed',created=now,livemode=False,
        data=dict(object=dict(id=checkout,object='checkout.session',status='complete',mode='subscription',customer=customer,livemode=False,metadata=dict(keel_journey_operation=str(operation)))))
        if provider=='stripe' else dict(event_id='evt_http_runtime',event_type='transaction.completed',occurred_at=datetime.now(timezone.utc).isoformat(),
        data=dict(id=checkout,customer_id=customer,custom_data=dict(keel_journey_operation=str(operation)))))
    for delivery in ('one','two'):
        if provider=='paddle':core['notification_id']=delivery
        payload=json.dumps(core).encode()
        if provider=='stripe':
            from .test_contract import signed
            headers={'Stripe-Signature':signed(payload,env['KEEL_SANDBOX_STRIPE_WEBHOOK_SECRET'])}
        else:
            signature=hmac.new(env['KEEL_SANDBOX_PADDLE_WEBHOOK_SECRET'].encode(),str(now).encode()+b':'+payload,hashlib.sha256).hexdigest()
            headers={'Paddle-Signature':f'ts={now};h1={signature}'}
        response=client.post(route,content=payload,headers=headers)
        assert response.status_code==200,response.json()
        result=response.json()
        assert result['captured'] is True and result['confirmed'] is False
        assert result['event_id']=='evt_http_runtime'
        assert (result['state'],result['reason'])==('pending','provider_capabilities_unproved')
    from src.ai.billing.trial_coordinator import observation_identity
    with owner_db.cursor() as q:
        q.execute('SELECT count(*) FROM billing_observation_receipts WHERE operation_id=%s',(str(observation_identity(operation)),));assert q.fetchone()==(1,)
        q.execute('SELECT count(*) FROM billing_verification_observations WHERE operation_id=%s',(str(observation_identity(operation)),));assert q.fetchone()==(2,)
    assert fingerprint(owner_db)==before
    with owner_db.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",party)
    with pytest.raises((ValueError,psycopg2.Error)):
        with runtime.resolve(event):pytest.fail('Revoked authority accepted')
    assert fingerprint(owner_db)==before
