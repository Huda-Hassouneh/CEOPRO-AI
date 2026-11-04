"""Lean future-customer terms; only disposable fixtures are changed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.ai import db
from src.ai.billing import admin, service, store
from src.ai.billing.standard_plan_catalog import install_catalog, load_catalog
from src.ai.core import storage_ledger, usage
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401
from .test_provider_trials import provider, headers  # noqa: F401

TARGET = {
    'starter': (1024, 51200, 3000, 1, 5),
    'growth': (5120, 204800, 12000, 3, 15),
    'enterprise': (20480, 768000, 40000, 8, 40),
}
CODES = ('document_storage_mb', 'document_extraction', 'sentiment_analysis',
         'connected_data_sources', 'tracked_competitors')
LEGACY = {'starter': (1024, 51200, 5000, 1, None),
          'growth': (10240, 512000, 25000, 5, None),
          'enterprise': (51200, 2097152, 100000, 20, None)}


def sql(conn, query, args=()):
    with conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchall() if cur.description else None


def assign(conn, tenant, plan, period='monthly'):
    months = {'monthly': 1, 'three-months': 3, 'six-months': 6}[period]
    sql(conn, "INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,source,period_code,current_period_start,current_period_end) "
        "VALUES(%s,%s,'active','manual',%s,current_date,(current_date+make_interval(months=>%s)-interval '1 day')::date)",
        (tenant[0], plan, period, months))


def test_only_approved_five_allowances_change():
    c = load_catalog()
    assert c['catalog_version'] == 'standard-plans-lean-search-v1'
    for p, credits, products, seats, images, reports in zip(c['plans'], (436,1111,2780),
            (100,250,500), (5,20,50), (20,100,150), (5,20,60)):
        a = {r['feature_key']: r for r in p['allowances']}
        assert tuple(a[k]['value'] for k in CODES) == TARGET[p['plan_key']]
        assert all(a[k]['trial_value'] is None for k in CODES)
        assert a['tracked_products']['value'] == products
        assert a['team_seats']['value'] == seats
        assert a['marketing_image_generation']['value'] == images
        assert a['monthly_reports']['value'] == reports
        assert a['ai_credits']['value'] == a['data_credits']['value'] == credits
        assert a['rag_assistant']['value'] == {'starter':100000,'growth':500000,'enterprise':2000000}[p['plan_key']]
        assert p['trial_days'] == (7 if p['plan_key']=='enterprise' else 14)
        assert p['bootstrap_commercial_defaults']['monthly_price'] == {'starter':'29.00','growth':'59.00','enterprise':'99.00'}[p['plan_key']]
        assert [x['discount_percent'] for x in p['bootstrap_commercial_defaults']['billing_periods']] == ['0.00','0.00']


@pytest.mark.parametrize('plan', TARGET)
@pytest.mark.parametrize('period', ['monthly','three-months','six-months'])
def test_period_allowance_is_not_multiplied(owner_db, tenant, restricted_runtime, plan, period):
    assign(owner_db, tenant, plan, period)
    with closing(db.app_role_connection(*tenant)) as conn:
        effective = usage.get_plan(conn, tenant[0])
        assert tuple(effective['features'][k]['limit'] for k in CODES) == TARGET[plan]
        assert effective['period_code'] == period
        for code,quota in [(usage.DOCUMENT_EXTRACTION,TARGET[plan][1]),(usage.SENTIMENT_ANALYSIS,TARGET[plan][2])]:
            usage.reserve(conn, tenant[0], code, quota)
            conn.commit()
            with pytest.raises(usage.PlanLimitReached):
                usage.reserve(conn, tenant[0], code, 1)
            conn.rollback()


@pytest.mark.parametrize('plan', TARGET)
@pytest.mark.parametrize('trial',[False,True])
def test_installer_and_new_terms_do_not_rewrite_existing_snapshots(owner_db, tenant, plan,trial):
    # Reconstruct historical purchased terms in synthetic fixtures, then
    # exercise the existing explicit future-assignment authoring operation.
    try:
        for code, value in zip(CODES, LEGACY[plan]):
            sql(owner_db, 'UPDATE usage_plan_limits SET limit_value=%s WHERE plan_key=%s AND feature_code=%s', (value,plan,code))
        if trial:
            assert store.start_trial(owner_db,tenant[0],started_by_user_id=tenant[1],plan_key=plan)
        else:assign(owner_db, tenant, plan)
        issued=store.trial(owner_db,tenant[0])
        before = sql(owner_db, 'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))[0][0]
        install_catalog(owner_db)
        assert tuple(dict(sql(owner_db,'SELECT feature_code,limit_value FROM usage_plan_limits WHERE plan_key=%s',(plan,)))[k] for k in CODES) == LEGACY[plan]
        for code, value in zip(CODES, TARGET[plan]):
            admin.set_plan_feature(owner_db, plan_key=plan, feature_code=code, included=True,
                limit_value=value, approved_by=tenant[1], reason='Disposable lean catalog acceptance')
        future=str(uuid4())
        try:
            sql(owner_db,"INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Future lean fixture','JO','JOD')",(future,))
            assign(owner_db,(future,tenant[1]),plan)
            assert tuple(usage.get_plan(owner_db,future)['features'][k]['limit'] for k in CODES)==TARGET[plan]
        finally:sql(owner_db,'DELETE FROM companies WHERE tenant_id=%s',(future,))
        assert sql(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))[0][0] == before
        assert tuple(usage.get_plan(owner_db,tenant[0])['features'][k]['limit'] for k in CODES) == LEGACY[plan]
        sql(owner_db,"UPDATE tenant_plan_assignments SET current_period_start=current_date,current_period_end=current_date+180 WHERE tenant_id=%s",(tenant[0],))
        assert sql(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))[0][0] == before
        assert store.trial(owner_db,tenant[0])==issued
    finally:
        for code, value in zip(CODES,TARGET[plan]):
            sql(owner_db,'UPDATE usage_plan_limits SET limit_value=%s WHERE plan_key=%s AND feature_code=%s',(value,plan,code))


def test_legacy_rights_loss_is_not_an_ordinary_upgrade(monkeypatch):
    # Real classification, then real change context; no provider operation.
    base = {'entitlements':['competitor_management'], 'features':{
        'tracked_competitors':{'unit':'competitors','aggregation_type':'max','reset_cycle':'lifetime','limit':None},
        'tracked_products':{'unit':'products','aggregation_type':'max','reset_cycle':'lifetime','limit':100}}}
    target = deepcopy(base)
    target['features']['tracked_competitors']['limit'] = 15
    target['features']['tracked_products']['limit'] = 250
    assert service._classify_rights_change(base,target) == ('mixed',())
    monkeypatch.setattr(service,'_require_payments',lambda:None)
    monkeypatch.setattr(service,'_live_subscription',lambda *a:{'status':'active','cancel_at_period_end':False,
        'plan_key':'starter','period_code':'monthly','scheduled_plan_key':None,'scheduled_period_code':None})
    monkeypatch.setattr(service,'_price_or_error',lambda *a:{'tier_level':2,'amount':59})
    monkeypatch.setattr(service.store,'has_custom_contract',lambda *a:False)
    monkeypatch.setattr(usage,'get_plan',lambda *a:{**base,'source':'stripe'})
    monkeypatch.setattr(service.store,'configured_plan_rights',lambda *a,**kw:target)
    with pytest.raises(service.BillingError) as error:
        service._plan_change_context(None,'synthetic','growth','monthly')
    assert error.value.code == 'plan_transition_mixed_rights'
    assert service._classify_rights_change(target,base)[0] == 'mixed'


def test_legacy_local_trial_checkout_keeps_original_snapshot_and_cutoff(client,owner_db,tenant,provider,send):
    try:
        for code,value in zip(CODES,LEGACY['starter']):
            sql(owner_db,'UPDATE usage_plan_limits SET limit_value=%s WHERE plan_key=%s AND feature_code=%s',(value,'starter',code))
        assert store.start_trial(owner_db,tenant[0],started_by_user_id=tenant[1],plan_key='starter')
    finally:
        for code,value in zip(CODES,TARGET['starter']):
            sql(owner_db,'UPDATE usage_plan_limits SET limit_value=%s WHERE plan_key=%s AND feature_code=%s',(value,'starter',code))
    issued=store.trial(owner_db,tenant[0])
    before=sql(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))[0][0]
    blocked=client.post('/billing/checkout',headers=headers(tenant),json={'plan_key':'growth'})
    assert blocked.status_code==409,blocked.text
    assert blocked.json()['detail']['reason']=='plan_transition_mixed_rights'
    assert not provider['requests']
    response=client.post('/billing/checkout',headers=headers(tenant),json={'plan_key':'starter'})
    assert response.status_code==200,response.text
    sid=response.json()['session_id']
    assert provider['requests'][0]['subscription_data']['trial_end']==int(issued['ends_at'].timestamp())
    sub=provider['confirm'](sid)
    assert send('customer.subscription.created',sub).status_code==200
    assert store.trial(owner_db,tenant[0])==issued
    assert sql(owner_db,'SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s',(tenant[0],))[0][0]==before


@pytest.mark.parametrize('current',list(TARGET))
@pytest.mark.parametrize('target',list(TARGET))
def test_catalog_transition_matrix_retains_real_legacy_losses(current,target):
    catalog=load_catalog()
    metadata={f['key']:f for f in catalog['features']}
    def rights(key):
        p=next(p for p in catalog['plans'] if p['plan_key']==key)
        return {'entitlements':[f['key'] for f in catalog['features'] if f['entitlement_type']=='boolean'],
            'features':{a['feature_key']:{**{k:metadata[a['feature_key']][k] for k in ('unit','aggregation_type','reset_cycle')},
                'limit':a['value']} for a in p['allowances']}}
    new_current,new_target=rights(current),rights(target)
    ranks=list(TARGET)
    direction='gain' if ranks.index(current)<ranks.index(target) else 'loss' if current!=target else 'unchanged'
    assert service._classify_rights_change(new_current,new_target)==(direction,())
    historical=deepcopy(new_current)
    for code,value in zip(CODES,LEGACY[current]):historical['features'][code]['limit']=value
    expected='mixed' if ranks.index(current)<ranks.index(target) else 'loss'
    assert service._classify_rights_change(historical,new_target)==(expected,())


def test_storage_uses_bytes_not_display_rounding(owner_db, tenant, restricted_runtime):
    assign(owner_db,tenant,'starter')
    cap = 1024 * 1048576
    sql(owner_db,"INSERT INTO tenant_storage_objects(tenant_id,bucket,object_key,size_bytes,kind) VALUES(%s,'fixture',%s,%s,'test')",
        (tenant[0],uuid4().hex,cap-1))
    with closing(db.app_role_connection(*tenant)) as conn:
        usage.ensure_capacity(conn,tenant[0],usage.DOCUMENT_STORAGE_MB,1/1048576)
        with pytest.raises(usage.PlanLimitReached):
            usage.ensure_capacity(conn,tenant[0],usage.DOCUMENT_STORAGE_MB,2/1048576)


def test_concurrent_manual_competitor_api_is_atomic(owner_db,tenant,restricted_runtime):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core.exceptions import register_exception_handlers
    from src.ai.core.security import TenantContext,get_tenant_context
    from src.ai.routers import competitors
    assign(owner_db,tenant,'starter')
    # Real handler, registration, classifier, transaction and restricted role.
    app=FastAPI();register_exception_handlers(app);app.include_router(competitors.router)
    app.dependency_overrides[get_tenant_context]=lambda:TenantContext(*tenant)
    names=[uuid4().hex for _ in range(6)]
    with TestClient(app) as client:
        def add(name):
            return client.post('/competitors',json={'name':'Synthetic '+name,'website_url':'https://'+name+'.example.test'})
        for name in names[:4]:assert add(name).status_code==200
        start=Barrier(2)
        def race(name):start.wait(timeout=10);return add(name)
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(race,names[4:]))
        assert sorted(r.status_code for r in responses)==[200,402],[r.text for r in responses]
        assert sql(owner_db,'SELECT count(*) FROM tenant_competitors WHERE tenant_id=%s AND is_tracked',(tenant[0],))[0][0]==5
        assert add(names[0]).status_code==200 # Idempotent at capacity.
        assert sql(owner_db,'SELECT count(*) FROM global_competitors WHERE added_by_tenant_id=%s',(tenant[0],))[0][0]==5


@pytest.mark.parametrize('modes', [('auto','auto'),('priced','priced'),('auto','priced'),('auto','manual'),('stored','manual'),('stored','auto')])
def test_competitor_last_slot_is_shared_across_paths(owner_db,tenant,restricted_runtime,modes):
    from src.market_scraper.market_discovery import pipeline
    assign(owner_db,tenant,'starter')
    ids=[]
    for n in range(6):
        cid=str(uuid4());ids.append(cid)
        sql(owner_db,'INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES(%s,%s)',(cid,'Synthetic '+cid))
        sql(owner_db,'INSERT INTO tenant_competitors(tenant_id,global_competitor_id,is_tracked) VALUES(%s,%s,%s)',(tenant[0],cid,n<4))
    start=Barrier(2)
    def run(pair):
        mode,cid=pair
        with closing(db.app_role_connection(*tenant)) as conn:
            start.wait(timeout=10)
            if mode=='stored':
                pipeline.store(conn,tenant[0],SimpleNamespace(industry_key='general_retail'),[])
                sql(conn,'UPDATE tenant_competitors SET last_seen_at=now() WHERE tenant_id=%s AND global_competitor_id=%s',(tenant[0],cid))
                pipeline.auto_track(conn,tenant[0],[(cid,.9,.9)])
            elif mode=='auto':pipeline.auto_track(conn,tenant[0],[(cid,.9,.9)])
            elif mode=='priced':pipeline._track_priced(conn,tenant[0],[cid])
            else:
                usage.ensure_capacity(conn,tenant[0],usage.TRACKED_COMPETITORS,0)
                if usage.capacity_left(conn,tenant[0],usage.TRACKED_COMPETITORS)>0:
                    sql(conn,'UPDATE tenant_competitors SET is_tracked=TRUE WHERE tenant_id=%s AND global_competitor_id=%s',(tenant[0],cid))
            conn.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,zip(modes,ids[4:])))
        assert sql(owner_db,'SELECT count(*) FROM tenant_competitors WHERE tenant_id=%s AND is_tracked',(tenant[0],))[0][0] == 5
    finally:
        sql(owner_db,'DELETE FROM tenant_competitors WHERE tenant_id=%s',(tenant[0],))
        for cid in ids:sql(owner_db,'DELETE FROM global_competitors WHERE global_competitor_id=%s',(cid,))


def test_matching_commits_non_access_evidence_before_tracking_lock(owner_db,tenant,restricted_runtime,monkeypatch):
    from src.market_scraper.market_discovery import pipeline
    assign(owner_db,tenant,'starter');ids=[]
    for _ in range(6):
        cid=str(uuid4());ids.append(cid)
        sql(owner_db,'INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES(%s,%s)',(cid,'Synthetic '+cid))
        sql(owner_db,'INSERT INTO tenant_competitors(tenant_id,global_competitor_id,is_tracked) VALUES(%s,%s,FALSE)',(tenant[0],cid))
    monkeypatch.setattr(pipeline.offerings,'company_products',lambda *a:[])
    monkeypatch.setattr(pipeline.offerings,'record_matches',lambda *a,**kw:{'currency_mismatch':0,'matched':1,'matches':[{'product_id':'offline'}]})
    monkeypatch.setattr(pipeline.price_comparison_engine,'refresh_for_competitor',lambda *a,**kw:{'rows':0})
    actual=pipeline._track_priced
    def track(conn,*args):
        # A separate committed read proves no matching row lock is retained;
        # pooled connections immediately start a new SET LOCAL transaction.
        assert sql(owner_db,"SELECT count(*) FROM tenant_competitors WHERE tenant_id=%s AND relationship='DIRECT'",(tenant[0],))[0][0]==6
        return actual(conn,*args)
    monkeypatch.setattr(pipeline,'_track_priced',track)
    try:
        with closing(db.app_role_connection(*tenant)) as conn:
            result=pipeline._match_prices(conn,tenant[0],ids)
            assert result['competitors_matched']==6
            assert result['tracked']==5
    finally:
        sql(owner_db,'DELETE FROM tenant_competitors WHERE tenant_id=%s',(tenant[0],))
        for cid in ids:sql(owner_db,'DELETE FROM global_competitors WHERE global_competitor_id=%s',(cid,))


def image_doubles(monkeypatch, size, barrier=None):
    from src.ai.marketing import image_service as images
    monkeypatch.setattr(images,'uses_plan_allowance',lambda:True)
    monkeypatch.setattr(images.image_generation,'build_image_prompt',lambda c:'Synthetic test image')
    def generate(*a,**kw):
        if barrier:barrier.wait(timeout=15)
        return images.image_generation.GeneratedImage(content=b'x'*size,content_type='image/png',provider='offline')
    monkeypatch.setattr(images.image_generation,'generate_campaign_image',generate)
    monkeypatch.setattr(db,'minio_client',lambda:object())
    uploaded=[]
    def upload(client, content, content_type, tid, cid, on_pre_upload=None):
        key=tid+'/'+uuid4().hex+'.png'
        if on_pre_upload:on_pre_upload(images.image_storage.GENERATED_IMAGES_BUCKET,key,len(content))
        uploaded.append(key)
        return key
    monkeypatch.setattr(images.image_storage,'upload_generated_image',upload)
    monkeypatch.setattr(images.data_access,'add_image_asset',lambda *a,**kw:str(uuid4()))
    monkeypatch.setattr(images.data_access,'save_generated_image',lambda *a,**kw:None)
    return images,uploaded


def fill_storage(conn, tid, remaining):
    storage_ledger.record(conn,tid,'fixture',uuid4().hex,1024*1048576-remaining,'test')


@pytest.mark.parametrize('worker',[False,True])
def test_generated_image_checks_actual_bytes_before_upload(owner_db,tenant,restricted_runtime,monkeypatch,worker):
    assign(owner_db,tenant,'starter');fill_storage(owner_db,tenant[0],600000)
    images,uploaded=image_doubles(monkeypatch,700000)
    with closing(db.app_role_connection(*tenant)) as conn:
        def record(bucket,key,size):
            storage_ledger.record(conn,tenant[0],bucket,key,size,'marketing_generated_image');conn.commit()
        with pytest.raises(usage.PlanLimitReached):
            images.generate_and_store(conn,*tenant,str(uuid4()),{},on_pre_upload=record if worker else None)
        assert not uploaded
        assert next(f['current_usage'] for f in usage.current_usage(conn,tenant[0])
                    if f['feature_code']==usage.IMAGE_GENERATION)==0


@pytest.mark.parametrize('worker',[False,True])
def test_concurrent_generated_images_share_storage_capacity(owner_db,tenant,restricted_runtime,monkeypatch,worker):
    assign(owner_db,tenant,'starter');fill_storage(owner_db,tenant[0],1048576)
    images,uploaded=image_doubles(monkeypatch,700000,Barrier(2))
    def run(_):
        with closing(db.app_role_connection(*tenant)) as conn:
            def record(bucket,key,size):
                storage_ledger.record(conn,tenant[0],bucket,key,size,'marketing_generated_image');conn.commit()
            try:
                images.generate_and_store(conn,*tenant,str(uuid4()),{},on_pre_upload=record if worker else None)
                return 'stored'
            except usage.PlanLimitReached:return 'full'
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(run,range(2)))
    assert sorted(outcomes)==['full','stored']
    assert len(uploaded)==1
    assert sql(owner_db,'SELECT sum(size_bytes) FROM tenant_storage_objects WHERE tenant_id=%s',(tenant[0],))[0][0] <= 1024*1048576
