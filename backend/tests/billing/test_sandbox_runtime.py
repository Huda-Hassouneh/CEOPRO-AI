"""Network-free startup/signature/resolution tests; no merchant acceptance."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,hmac,json,time,uuid
from types import SimpleNamespace
from unittest.mock import Mock,MagicMock
import pytest
from src.ai.billing import sandbox_runtime as R,payment_contracts as C


def configuration():
    tenant,actor=str(uuid.uuid4()),str(uuid.uuid4())
    document=dict(environment='test',provider_operations_authorization='SYNTHETIC NOT AUTHORIZATION',
        synthetic_businesses=[dict(tenant_id=tenant,actor_id=actor)],gateways=[
            dict(provider='stripe',binding_id='stripe_original',merchant_account_id='acct_synthetic',api_version='2026-08-26.dahlia',merchant_reviewed=False,customer_replay_window_seconds=3600,
                return_urls=['https://keel.example.test/onboarding/payment','https://keel.example.test/onboarding/payment']),
            dict(provider='paddle',binding_id='paddle_original',merchant_account_id='slr_synthetic',api_version='1',merchant_reviewed=False,checkout_origin='https://keel.example.test',
                return_urls=['https://keel.example.test/billing/paddle-payment','https://keel.example.test/billing/paddle-payment'])])
    env=dict(KEEL_SANDBOX_ACCEPTANCE_ENABLED='true',KEEL_DEV_ISOLATED='1',SENTRY_ENVIRONMENT='development',DATABASE_URL='postgresql://unused@127.0.0.1:19999/keel_billing_test_sandbox',
        KEEL_SANDBOX_STRIPE_API_KEY='sk_test_SYNTHETIC',KEEL_SANDBOX_STRIPE_WEBHOOK_SECRET='whsec_SYNTHETIC',
        KEEL_SANDBOX_PADDLE_API_KEY='pdl_sdbx_apikey_SYNTHETIC',KEEL_SANDBOX_PADDLE_WEBHOOK_SECRET='pdl_SYNTHETIC')
    env.update({name:'SYNTHETIC password' for name in R.PASSWORDS.values()})
    return document,env


def installed(tmp_path,monkeypatch,app):
    document,env=configuration();path=tmp_path/'private-config.json';path.write_text(json.dumps(document),encoding='utf-8');env['KEEL_SANDBOX_CONFIG']=str(path)
    monkeypatch.setattr(R.SandboxRuntime,'socket',Mock(side_effect=AssertionError('Startup must not connect')))
    runtime=R.install(app,env)
    return runtime,document,env


def test_disabled_is_noop_without_reading_paths_or_secrets():
    app=SimpleNamespace(state=SimpleNamespace())
    assert R.install(app,{'KEEL_SANDBOX_CONFIG':'must never read'}) is None
    assert vars(app.state)=={}


@pytest.mark.parametrize('problem',['hosted','live','database','shared','missing_secret','missing_password','wrong_key','version','paddle_url','duplicate_provider','approval','empty_parties'])
def test_installation_rejects_unsafe_config_without_connections(problem,tmp_path,monkeypatch):
    document,env=configuration()
    if problem=='hosted':env['SENTRY_ENVIRONMENT']='production'
    if problem=='live':document['environment']='live'
    if problem=='database':env['DATABASE_URL']='postgresql://unused@remote.example.test:5432/keel_billing_test_sandbox'
    if problem=='shared':env['DATABASE_URL']='postgresql://unused@127.0.0.1:5432/application'
    if problem=='missing_secret':del env['KEEL_SANDBOX_PADDLE_WEBHOOK_SECRET']
    if problem=='missing_password':del env['KEEL_SANDBOX_CONSENT_DB_PASSWORD']
    if problem=='wrong_key':env['KEEL_SANDBOX_STRIPE_API_KEY']='sk_live_SYNTHETIC'
    if problem=='version':document['gateways'][0]['api_version']='unapproved'
    if problem=='paddle_url':document['gateways'][1]['return_urls'][0]='https://foreign.example.test/billing/paddle-payment'
    if problem=='duplicate_provider':document['gateways'].append(document['gateways'][0])
    if problem=='approval':document['provider_operations_authorization']=''
    if problem=='empty_parties':document['synthetic_businesses']=[]
    path=tmp_path/'config.json';path.write_text(json.dumps(document),encoding='utf-8');env['KEEL_SANDBOX_CONFIG']=str(path)
    socket=Mock(side_effect=AssertionError('No connection'));monkeypatch.setattr(R.SandboxRuntime,'socket',socket)
    app=SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(R.SandboxConfigurationError) as error:R.install(app,env)
    assert 'SYNTHETIC' not in str(error.value) and vars(app.state)=={}
    socket.assert_not_called()


@pytest.mark.parametrize('provider',['stripe','paddle'])
def test_installed_real_signature_routes_are_default_off_and_fail_closed(client,tmp_path,monkeypatch,provider):
    runtime,document,env=installed(tmp_path,monkeypatch,client.app)
    endpoint='/billing/trial-journeys/webhook/'+provider
    assert client.post(endpoint,content=b'{}').status_code==404
    monkeypatch.setenv('RECURRING_JOURNEY_ENABLED','true')
    decoder,handler=client.app.state.bound_journey_webhooks[provider]
    seen=[]
    @contextmanager
    def resolve(event):
        seen.append(event)
        raise ValueError('Unproved recurring authority remains pending')
        yield
    handler.resolve=resolve
    now=int(time.time())
    if provider=='stripe':
        from .test_contract import signed
        raw=dict(id='evt_runtime',type='customer.subscription.updated',created=now,livemode=False,data=dict(object=dict(id='sub_original',customer='cus_original',livemode=False)))
        payload=json.dumps(raw).encode();headers={'Stripe-Signature':signed(payload,env['KEEL_SANDBOX_STRIPE_WEBHOOK_SECRET'])}
    else:
        raw=dict(event_id='evt_runtime',event_type='subscription.updated',occurred_at=datetime.now(timezone.utc).isoformat(),data=dict(id='sub_original',customer_id='ctm_original'))
        payload=json.dumps(raw).encode();digest=hmac.new(env['KEEL_SANDBOX_PADDLE_WEBHOOK_SECRET'].encode(),str(now).encode()+b':'+payload,hashlib.sha256).hexdigest()
        headers={'Paddle-Signature':f'ts={now};h1={digest}'}
    try:
        assert client.post(endpoint,content=payload,headers={'Stripe-Signature':'bad','Paddle-Signature':'bad'}).status_code==400
        assert seen==[]
        assert client.post(endpoint,content=payload,headers=headers).status_code==500
        assert len(seen)==1 and seen[0].binding==runtime.gateways[provider].binding
        assert seen[0].binding.environment is C.GatewayEnvironment.TEST
        runtime.socket.assert_not_called()
    finally:
        del client.app.state.bound_journey_webhooks;del client.app.state.subscription_journey_factory


@pytest.mark.parametrize('problem',['valid','foreign_binding','foreign_merchant','ambiguous','unknown','foreign_actor','forged_marker'])
def test_signed_lookup_uses_original_database_identity_not_provider_tenant(problem):
    document,env=configuration();runtime=R.SandboxRuntime(document,env);b=runtime.gateways['paddle'].binding
    operation=uuid.uuid4();party=document['synthetic_businesses'][0]
    conn=MagicMock();q=conn.cursor.return_value.__enter__.return_value
    q.fetchall.return_value=[(operation,uuid.UUID(party['tenant_id']),uuid.UUID(party['actor_id']))]
    if problem=='ambiguous':q.fetchall.return_value*=2
    if problem=='unknown':q.fetchall.return_value=[]
    if problem=='foreign_binding':b=C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,'slr_other','foreign')
    raw={'data':{'custom_data':{'tenant_id':'UNTRUSTED','keel_journey_operation':'forged' if problem=='forged_marker' else str(operation)}}}
    event=C.VerifiedPaymentEvent('paddle','evt_test',C.PaymentEventKind.SUBSCRIPTION_CHANGED,datetime.now(timezone.utc),C.ProviderReference('paddle','ctm_original',binding=b),C.ProviderReference('paddle','sub_original',binding=b),None,None,None,b'{}',raw,binding=b)
    flow=Mock();flow.dispatches.command.return_value=dict(presentation_id=str(uuid.uuid4()),provider_checkout_id='txn_original')
    flow.collection.consents.read.return_value=C.CustomerPayload.freeze(dict(acceptance={'SYNTHETIC':True},policy={'language_tag':'ar'}))
    stored_binding=dict(provider=b.provider,environment=b.environment.value,merchant_account_id='other_merchant' if problem=='foreign_merchant' else b.merchant_account_id,binding_id=b.binding_id)
    flow.collection._owned.return_value={'reservation':{'binding_id':b.binding_id,'approved_terms':{'binding':stored_binding}}}
    runtime.socket=Mock(return_value=conn);contexts=[]
    @contextmanager
    def journey(ctx):
        contexts.append((ctx.tenant_id,ctx.user_id))
        if problem=='foreign_actor':raise ValueError('Current actor revoked')
        yield flow
    runtime.journey=journey
    if problem=='valid':
        with runtime.resolve(event) as result:assert result==(flow,operation,'ar')
        assert contexts==[(party['tenant_id'],party['actor_id'])]
        assert q.execute.call_args.args[1][0]==b.binding_id
        assert 'UNTRUSTED' not in str(q.execute.call_args.args)
        conn.commit.assert_called_once()
    else:
        with pytest.raises(ValueError):
            with runtime.resolve(event):pytest.fail('Foreign or ambiguous route accepted')
    if problem in ('foreign_binding','forged_marker'):runtime.socket.assert_not_called()


def test_initial_paddle_receipt_digest_ignores_delivery_id_without_rewriting_event():
    from src.ai.billing.paddle_gateway import PaddleWebhookDecoder,notification_digest
    document,env=configuration();runtime=R.SandboxRuntime(document,env);b=runtime.gateways['paddle'].binding
    op=uuid.uuid4();party=document['synthetic_businesses'][0]
    row={'reservation':{'state':'pending','binding_id':b.binding_id,'approved_terms':{'binding':dict(provider='paddle',environment='test',merchant_account_id=b.merchant_account_id,binding_id=b.binding_id)}}}
    flow=Mock();flow.collection._owned.return_value=row
    flow.dispatches.command.return_value=dict(provider_customer_id='ctm_original',provider_checkout_id='txn_original',provider_subscription_id=None)
    flow.observations.read.return_value={'operation_id':str(op)}
    flow.reconcile.return_value={'state':'pending'}
    @contextmanager
    def resolve(e):yield flow,op,'en'
    from src.ai.billing.journey_webhooks import JourneyWebhookReconciler
    r=JourneyWebhookReconciler(resolve);decoder=PaddleWebhookDecoder(b,'SYNTHETIC',clock=lambda:1000)
    raw=dict(event_id='evt_one',event_type='transaction.completed',occurred_at=datetime.now(timezone.utc).isoformat(),notification_id='one',data=dict(id='txn_original',customer_id='ctm_original'))
    events=[]
    for delivery in ('one','two'):
        raw['notification_id']=delivery;payload=json.dumps(raw).encode();signature=hmac.new(b'SYNTHETIC',b'1000:'+payload,hashlib.sha256).hexdigest()
        e=decoder.decode(payload,'ts=1000;h1='+signature);events.append(e)
        with pytest.raises(ValueError,match='pending'):r(e)
    calls=flow.observations.notification.call_args_list
    assert calls[0].args[2]==calls[1].args[2]==notification_digest(events[0])
    assert events[0].raw_payload!=events[1].raw_payload
    assert flow.reconcile.call_count==2


@pytest.mark.parametrize('problem',['unknown','recovered','withdrawn','conflicting_event'])
def test_webhook_ambiguous_checkout_recovery_is_get_only_and_rechecks_consent(problem):
    document,env=configuration();runtime=R.SandboxRuntime(document,env);b=runtime.gateways['stripe'].binding
    operation=uuid.uuid4();party=document['synthetic_businesses'][0]
    conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchall.return_value=[(operation,uuid.UUID(party['tenant_id']),uuid.UUID(party['actor_id']))]
    runtime.socket=Mock(return_value=conn)
    event=C.VerifiedPaymentEvent('stripe','evt_recover',C.PaymentEventKind.CHECKOUT_COMPLETED,datetime.now(timezone.utc),
        C.ProviderReference('stripe','cus_original',binding=b),None,C.ProviderReference('stripe','cs_original',binding=b),None,None,b'{}',
        {'data':{'object':{'metadata':{'keel_journey_operation':str(operation)}}}},binding=b)
    d=dict(presentation_id=str(uuid.uuid4()),provider_checkout_id=None,submitted_at='SYNTHETIC',acceptance_id=str(uuid.uuid4()),customer_operation_id=str(uuid.uuid4()))
    flow=Mock();flow.dispatches.command.return_value=d
    flow.collection._owned.return_value={'reservation':{'binding_id':b.binding_id,'approved_terms':{'binding':dict(provider=b.provider,environment=b.environment.value,merchant_account_id=b.merchant_account_id,binding_id=b.binding_id)}}}
    flow.collection.consents.read.return_value=C.CustomerPayload.freeze(dict(acceptance={'SYNTHETIC':True},policy={'language_tag':'en'}))
    gateway=Mock(binding=b);session=SimpleNamespace(reference=SimpleNamespace(opaque_id='cs_original'))
    gateway.recover.return_value=None if problem=='unknown' else session
    if problem=='withdrawn':flow._accepted.side_effect=ValueError('Consent withdrawn')
    if problem=='conflicting_event':gateway.recover.return_value=SimpleNamespace(reference=SimpleNamespace(opaque_id='cs_foreign'))
    flow.checkout_gateway.return_value=gateway
    @contextmanager
    def journey(ctx):yield flow
    runtime.journey=journey
    if problem=='recovered':
        with runtime.resolve(event) as result:assert result==(flow,operation,'en')
        flow.dispatches.command.assert_any_call(operation,'session',acceptance=d['acceptance_id'],customer=d['customer_operation_id'],session='cs_original')
        gateway.recover.assert_called_once_with(d)
    elif problem=='conflicting_event':
        # Real adapter validate would reject a foreign original attempt. The
        # runtime also checks the signed positive Checkout ID before persistence.
        with pytest.raises(ValueError):
            with runtime.resolve(event):pytest.fail('Foreign recovered Checkout accepted')
        assert not any(c.args[1]=='session' for c in flow.dispatches.command.call_args_list)
    else:
        with pytest.raises(ValueError):
            with runtime.resolve(event):pytest.fail('Unknown or withdrawn recovery accepted')
        assert not any(c.args[1]=='session' for c in flow.dispatches.command.call_args_list)
    if problem=='withdrawn':gateway.recover.assert_not_called()
    gateway.submit.assert_not_called();flow.advance.assert_not_called()


@pytest.mark.parametrize('role,problem',[('ceopro_app','valid'),('ceopro_billing_setup','inherit'),('ceopro_consent_service','membership'),('ceopro_billing_observer','superuser'),('ceopro_journey_router','schema_create'),('ceopro_billing_setup','wrong_identity')])
def test_runtime_password_socket_checks_effective_role_model_without_fallback(monkeypatch,role,problem):
    import psycopg2
    document,env=configuration();runtime=R.SandboxRuntime(document,env)
    raw=MagicMock();authority=[role,role,False,False,False,False,role=='ceopro_app',False,False,False]
    if problem=='inherit':authority[6]=True
    if problem=='membership':authority[9]=True
    if problem=='superuser':authority[2]=True
    if problem=='schema_create':authority[8]=True
    if problem=='wrong_identity':authority[0]='postgres'
    raw.cursor.return_value.__enter__.return_value.fetchone.return_value=tuple(authority)
    connect=Mock(return_value=raw);monkeypatch.setattr(psycopg2,'connect',connect)
    if problem=='valid':assert runtime.socket(role) is raw
    else:
        with pytest.raises(R.SandboxConfigurationError):runtime.socket(role)
        raw.close.assert_called_once()
    assert connect.call_args.kwargs['user']==role and connect.call_args.kwargs['host']=='127.0.0.1'
    assert connect.call_args.kwargs['password']==env[R.PASSWORDS[role]]
