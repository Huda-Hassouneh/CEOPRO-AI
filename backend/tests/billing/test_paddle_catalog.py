"""Network-free catalog parity and single-submission recovery."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import uuid
import httpx
import pytest
from src.ai.billing import paddle_catalog as P, payment_contracts as C
from src.ai.billing.paddle_gateway import free_card_trial, PaddleJourneyGateway


B=C.GatewayBinding('paddle',C.GatewayEnvironment.TEST,'seller_fixture','catalog_fixture')
ROW=dict(price_id=str(uuid.uuid4()),plan_key='growth',display_name='Plus',period_code='monthly',
    interval_months=1,amount=Decimal('140.00'),currency='USD',trial_days=14)
MANIFEST=dict(provider='paddle',environment='test',binding_id=B.binding_id,merchant_account_id=B.merchant_account_id,
    database='keel_billing_test_catalog',plan_keys=['growth'],tax_category='saas',tax_mode='external',
    provider_operations_authorization='SYNTHETIC catalog authorization',merchant_approval_reference='SYNTHETIC',reason='Synthetic test')


class Store:
    def __init__(self):
        self.binding=B;self.manifest=deepcopy(MANIFEST);self.data={};self.links={};self.allowed=True;self.frozen='reviewed'
    @contextmanager
    def lock(self):yield
    def snapshot(self):
        if not self.allowed:raise P.CatalogBlocked('revoked')
        return [deepcopy(ROW)],self.frozen
    def read(self,kind,key):return deepcopy(self.data.get((kind,key)))
    def prepare(self,kind,key,request,price_id=None):
        if not self.allowed:raise P.CatalogBlocked('revoked')
        row=dict(operation_id=str(uuid.uuid4()),entity_kind=kind,entity_key=key,price_id=price_id,request=deepcopy(request),state='prepared')
        self.data.setdefault((kind,key),row);return deepcopy(self.data[(kind,key)])
    def claim(self,op,expected):
        if not self.allowed or expected!=self.frozen:raise P.CatalogBlocked('revoked or terms changed')
        actual=self.data[(op['entity_kind'],op['entity_key'])]
        if actual['state']!='prepared':raise P.CatalogBlocked('already submitted')
        actual['state']='submitted'
    def finish(self,op,obj,expected):
        if not self.allowed or expected!=self.frozen:raise P.CatalogBlocked('revoked or terms changed')
        row=self.data[(op['entity_kind'],op['entity_key'])];row.update(state='succeeded',provider_object_id=obj['id'])
        if op['price_id']:self.links[op['price_id']]=obj['id']
    def mapping(self,price_id):return self.links.get(price_id)


class Transport:
    api_version='1'
    def __init__(self,store):
        self.binding=B;self.store=store;self.objects={'product':[],'price':[]};self.posts=[];self.lost=None;self.hide=False;self.during_read=None
    def verify_namespace(self):pass
    def request(self,method,path,body=None,*,params=None):
        kind='product' if path.startswith('/products') else 'price'
        if method=='GET':
            if self.during_read:self.during_read()
            return dict(items=[] if self.hide else deepcopy(self.objects[kind]),has_more=False)
        self.posts.append((kind,deepcopy(body)))
        # Every POST follows a durable election, even if its reply is lost.
        assert any(op['state']=='submitted' and op['request']==body for op in self.store.data.values())
        obj=dict(deepcopy(body),id=('pro_' if kind=='product' else 'pri_')+str(len(self.posts)).zfill(26),status='active',type='standard')
        if kind=='price':obj['trial_period'].update(unit_price=None,unit_price_overrides=[])
        self.objects[kind].append(obj)
        if self.lost==kind:self.lost=None;raise TimeoutError('Synthetic lost reply')
        return deepcopy(obj)


def setup():
    repo=Store();transport=Transport(repo);adapter=P.CatalogAdapter(B,transport)
    return repo,transport,adapter


def sync(repo,adapter,apply=True):return P.synchronize(repo,adapter,expected='reviewed',apply=apply)


def test_approved_terms_create_once_and_repeat_verifies_existing_mapping():
    r,t,a=setup();sync(r,a)
    assert len(t.posts)==2 and len(r.links)==1
    assert t.posts[1][1]['unit_price']=={'amount':'14000','currency_code':'USD'}
    assert t.posts[1][1]['billing_cycle']=={'interval':'month','frequency':1}
    assert t.posts[1][1]['trial_period']=={'interval':'day','frequency':14,'requires_payment_method':True}
    assert all(x['state']=='verified' for x in sync(r,a)['actions']) and len(t.posts)==2


@pytest.mark.parametrize('kind',['product','price'])
def test_ambiguous_post_recovers_original_without_second_submission(kind):
    r,t,a=setup();t.lost=kind
    with pytest.raises(TimeoutError):sync(r,a)
    count=len(t.posts);sync(r,a)
    assert len([p for p in t.posts if p[0]==kind])==1 and len(t.posts)==2


def test_empty_discovery_after_uncertain_submission_never_elects_again():
    r,t,a=setup();t.lost='product'
    with pytest.raises(TimeoutError):sync(r,a)
    t.hide=True
    with pytest.raises(P.CatalogBlocked,match='GET recovery only'):sync(r,a)
    assert len(t.posts)==1


@pytest.mark.parametrize('problem',['amount','interval','trial','cardless','paid_trial','overrides','quantity','status','rebound','duplicate','metadata'])
def test_positive_object_drift_or_duplicate_is_never_rewritten(problem):
    r,t,a=setup();sync(r,a);p=t.objects['price'][0]
    if problem=='amount':p['unit_price']['amount']='14001'
    if problem=='interval':p['billing_cycle']['frequency']=3
    if problem=='trial':p['trial_period']['frequency']=13
    if problem=='cardless':p['trial_period']['requires_payment_method']=False
    if problem=='paid_trial':p['trial_period']['unit_price']={'amount':'1','currency_code':'USD'}
    if problem=='overrides':p['unit_price_overrides']=[{}]
    if problem=='quantity':p['quantity']['maximum']=2
    if problem=='status':p['status']='archived'
    if problem=='rebound':p['id']='pri_'+'z'*26
    if problem=='duplicate':t.objects['price'].append(dict(deepcopy(p),id='pri_'+'z'*26))
    if problem=='metadata':p['custom_data']['keel_binding_id']='other'
    with pytest.raises(P.CatalogBlocked):sync(r,a)
    assert len(t.posts)==2


@pytest.mark.parametrize('problem',['revoked','terms','mapping','binding','live'])
def test_authority_terms_or_mapping_conflict_prevents_posts(problem):
    r,t,a=setup()
    if problem=='revoked':t.during_read=lambda:setattr(r,'allowed',False)
    if problem=='terms':t.during_read=lambda:setattr(r,'frozen','changed')
    if problem=='mapping':r.links[ROW['price_id']]='pri_'+'z'*26
    if problem=='binding':a.binding=replace(B,binding_id='foreign')
    if problem=='live':
        with pytest.raises(P.CatalogBlocked):P.CatalogAdapter(replace(B,environment=C.GatewayEnvironment.LIVE),t)
        return
    with pytest.raises(P.CatalogBlocked):sync(r,a)
    assert not t.posts or problem=='mapping' and len(t.posts)==1


@pytest.mark.parametrize('change',[{'amount':Decimal('1.001')},{'amount':float('nan')},{'currency':'JPY'},{'interval_months':2},{'trial_days':0}])
def test_unsupported_financial_policy_has_no_silent_rounding(change):
    with pytest.raises((P.CatalogBlocked,ValueError)):P.price_payload(dict(ROW,**change),'pro_'+'1'*26,{})


@pytest.mark.parametrize('months',[3,6,12])
def test_approved_multi_month_terms_keep_full_period_amount_and_precision(months):
    p=P.price_payload(dict(ROW,interval_months=months,amount=Decimal('123.45')),'pro_'+'1'*26,{})
    assert p['billing_cycle']=={'interval':'month','frequency':months}
    assert p['unit_price']=={'amount':'12345','currency_code':'USD'}


def test_read_only_provider_preview_creates_no_journal_or_provider_objects():
    r,t,a=setup();result=sync(r,a,False)
    assert result['actions'][0]['state']=='create' and not r.data and not t.posts and not r.links


def test_exact_existing_objects_are_adopted_after_local_catalog_restore_without_posts():
    r,t,a=setup();sync(r,a);original=deepcopy(r.links);r.data={};r.links={}
    sync(r,a)
    assert r.links==original and len(t.posts)==2 and all(op['state']=='succeeded' for op in r.data.values())


def test_checkout_accepts_documented_explicit_free_card_trial_without_inventing_readiness():
    trial=dict(interval='day',frequency=14,requires_payment_method=True,unit_price=None,unit_price_overrides=[])
    r=deepcopy(ROW)
    class Reader:
        binding=B;api_version='1'
        def verify_namespace(self):pass
        def request(self,method,path,body=None,*,params=None):
            assert method=='GET' and path=='/prices/pri_'+'1'*26
            return dict(id='pri_'+'1'*26,status='active',trial_period=trial,billing_cycle=dict(interval='month',frequency=1),unit_price=dict(amount='14000',currency_code='USD'))
    terms=dict(binding=dict(binding_id=B.binding_id),approved_amount='140.00',currency='USD',interval_months=1)
    row=dict(reservation=dict(attempt_id='fixture',tenant_id='tenant',trial_duration_days=14,provider_price_id='pri_'+'1'*26,approved_terms=terms))
    gateway=PaddleJourneyGateway(B,Reader(),merchant_reviewed=True,approved_checkout_origin='https://approved.example.test',checkout_page_ready=True)
    result=gateway.prepare(row,C.ProviderReference('paddle','ctm_fixture',binding=B),{'trial_start_mode':'checkout_completion'},('https://approved.example.test/billing/paddle-payment',)*2)
    assert result['approved_terms']==terms and result['transport']['items'][0]['quantity']==1


@pytest.mark.parametrize('trial,allowed',[
    ({'interval':'day','frequency':14},True),
    ({'interval':'day','frequency':14,'requires_payment_method':True,'unit_price':None,'unit_price_overrides':[]},True),
    ({'interval':'day','frequency':14,'requires_payment_method':False},False),
    ({'interval':'day','frequency':14,'unit_price':{'amount':'0','currency_code':'USD'}},False),
    ({'interval':'day','frequency':14,'unknown':True},False),
    ({'interval':'day','frequency':True},False)])
def test_documented_trial_normalization_preserves_fail_closed_behavior(trial,allowed):
    assert free_card_trial(trial) is allowed


def test_pagination_does_not_follow_provider_urls_and_refuses_repeated_cursor():
    t=SimpleNamespace(binding=B,api_version='1',request=lambda *a,**kw:dict(items=[dict(id='pro_'+'1'*26)],has_more=True))
    with pytest.raises(P.CatalogBlocked,match='pagination'):P.CatalogAdapter(B,t).list('product')


def test_catalog_transport_uses_documented_sandbox_paths_and_pagination_only():
    calls=[]
    def responder(req):
        calls.append(req)
        return httpx.Response(200,json={'data':[],'meta':{'pagination':{'has_more':False}}})
    client=httpx.Client(transport=httpx.MockTransport(responder))
    t=P.PaddleCatalogTransport(B,'pdl_sdbx_apikey_SYNTHETIC',client=client)
    assert P.CatalogAdapter(B,t).list('product')==[]
    assert str(calls[0].url).startswith('https://sandbox-api.paddle.com/products?')
    assert calls[0].url.params['status']=='active,archived' and calls[0].headers['Paddle-Version']=='1'
    with pytest.raises(P.CatalogBlocked):t.request('PATCH','/products/pro_'+'1'*26,{})
    client.close()


def test_manifest_requires_specific_merchant_and_tax_approval():
    for change in ({'environment':'live'},{'merchant_account_id':''},{'tax_mode':'account_setting'},{'tax_category':'standard'},{'provider_operations_authorization':''},{'database':'keel_billing_test_invalid_suffix'}):
        with pytest.raises(P.CatalogBlocked):P.validate_manifest(dict(MANIFEST,**change))


def test_transport_namespace_switch_during_read_is_denied_before_post():
    r,t,a=setup();t.during_read=lambda:setattr(t,'binding',replace(B,merchant_account_id='foreign'))
    with pytest.raises(ValueError,match='namespace changed'):sync(r,a)
    assert not t.posts


def test_ambiguous_duplicate_json_configuration_is_refused():
    import json
    from src.ai.billing.paddle_gateway import unique_object
    with pytest.raises(ValueError):json.loads('{"provider":"stripe","provider":"paddle"}',object_pairs_hook=unique_object)


def test_cli_default_is_local_only_and_never_constructs_provider_transport(tmp_path,monkeypatch,capsys):
    import io,json
    from scripts import paddle_sync_catalog as command
    from src.ai.core import security
    manifest=tmp_path/'reviewed.json';manifest.write_text(json.dumps(MANIFEST),encoding='utf-8')
    monkeypatch.setattr(command,'local_database',lambda _:dict(dbname=MANIFEST['database']))
    monkeypatch.setattr(command.sys,'stdin',io.StringIO('synthetic-token\n'))
    monkeypatch.setattr(security,'get_tenant_context',lambda **kw:SimpleNamespace(user_id=str(uuid.uuid4()),tenant_id=str(uuid.uuid4())))
    monkeypatch.setenv('DATABASE_URL','postgresql://unused@127.0.0.1:19999/keel_billing_test_catalog')
    monkeypatch.setattr(command.psycopg2,'connect',lambda *a,**kw:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(command,'CatalogRepository',lambda *a:Store())
    monkeypatch.setattr(command,'PaddleCatalogTransport',lambda *a:pytest.fail('Provider transport in local preview'))
    assert command.main(['--manifest',str(manifest)])==0
    assert 'LOCAL PLAN ONLY' in capsys.readouterr().out


def test_cli_apply_requires_separate_execution_and_reviewed_hash(tmp_path):
    from scripts import paddle_sync_catalog as command
    with pytest.raises(SystemExit):command.main(['--manifest',str(tmp_path/'none'),'--apply'])
