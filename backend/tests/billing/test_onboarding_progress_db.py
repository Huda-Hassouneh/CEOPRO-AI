"""Native tenant-role tests: durable original onboarding, no commercial mutation."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from src.ai import onboarding_profile as profile
from src.ai.core import usage

def step(number,revision,**values):
    return profile.StepRequest(step=number,expected_revision=revision,**values)

@pytest.mark.parametrize('payload',[
    dict(step=1,expected_revision=0,country='US',city='New York'),
    dict(step=2,expected_revision=0,industry='invented'),
    dict(step=3,expected_revision=0,businessSize='1-50',annualRevenue='999'),
    dict(step=4,expected_revision=0,objectives=[]),
    dict(step=4,expected_revision=0,objectives=['knowledge','knowledge']),
    dict(step=5,expected_revision=0,selectedPlan='growth',billingPeriod='yearly'),
    dict(step=2,expected_revision=0,industry='retail',selectedPlan='enterprise'),
])
def test_original_step_fields_reject_invalid_or_extraneous_choices(payload):
    with pytest.raises(ValidationError): profile.StepRequest(**payload)

def test_saved_progress_retry_conflict_and_completion_do_not_start_another_trial(owner_db,tenant,billing_connections,monkeypatch):
    tid,uid=tenant
    conn=billing_connections(tid,uid)
    try:
        assert profile.state(conn,tid)['currentStep']==1
        with pytest.raises(HTTPException) as skipped: profile.save(conn,tid,uid,step(4,0,objectives=['knowledge']))
        assert skipped.value.status_code==409
        first=step(1,0,country='JO',city='amman',language='en')
        assert profile.save(conn,tid,uid,first)['revision']==1
        assert profile.save(conn,tid,uid,first)['revision']==1
        with pytest.raises(HTTPException) as stale: profile.save(conn,tid,uid,step(1,0,country='JO',city='irbid',language='en'))
        assert stale.value.status_code==409
        profile.save(conn,tid,uid,step(2,1,industry='retail'))
        profile.save(conn,tid,uid,step(3,2,businessSize='1-50',annualRevenue='under-100k'))
        profile.save(conn,tid,uid,step(4,3,objectives=['competitors']))
        assert profile.state(conn,tid)['currentStep']==5
        # A trial alone does not acknowledge a plan choice.
        monkeypatch.setattr(usage,'get_plan',lambda *a:{'assigned':True,'status':'trialing','plan_key':'growth'})
        with pytest.raises(HTTPException): profile.complete(conn,tid,uid)
        profile.save(conn,tid,uid,step(5,4,selectedPlan='growth',billingPeriod='monthly'))
        assert profile.complete(conn,tid,uid)['isComplete'] is True
        assert profile.complete(conn,tid,uid)['isComplete'] is True
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='ONBOARDING_COMPLETED'",(tid,));assert cur.fetchone()[0]==1
            cur.execute("SELECT count(*) FROM billing_subscriptions WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]==0
    finally:conn.close()

def test_profile_is_tenant_isolated_and_completed_legacy_company_is_unchanged(owner_db,tenant,billing_connections):
    tid,uid=tenant
    with owner_db.cursor() as cur:cur.execute("UPDATE companies SET onboarding_completed_at=now() WHERE tenant_id=%s",(tid,))
    conn=billing_connections(tid,uid)
    try:
        assert profile.state(conn,tid)['isComplete'] is True
        assert profile.complete(conn,tid,uid)['isComplete'] is True
        from uuid import uuid4
        with pytest.raises(HTTPException) as hidden:profile.state(conn,str(uuid4()))
        assert hidden.value.status_code==404
        with pytest.raises(HTTPException) as locked:profile.save(conn,tid,uid,step(1,0,country='JO',city='amman',language='ar'))
        assert locked.value.status_code==409
    finally:conn.close()

@pytest.mark.parametrize('effective',[
 {'assigned':False,'status':'active','plan_key':'growth'},
 {'assigned':True,'status':'pending','plan_key':'growth'},
 {'assigned':True,'status':'trialing','plan_key':'enterprise'},
])
def test_selected_plan_requires_actual_access_and_matching_plan(owner_db,tenant,billing_connections,monkeypatch,effective):
    tid,uid=tenant
    with owner_db.cursor() as cur:cur.execute("UPDATE companies SET onboarding_profile=%s::jsonb WHERE tenant_id=%s",('{"highestCompletedStep":5,"selectedPlan":"growth","revision":5}',tid))
    conn=billing_connections(tid,uid)
    monkeypatch.setattr(usage,'get_plan',lambda *a:effective)
    try:
        with pytest.raises(HTTPException) as refused:profile.complete(conn,tid,uid)
        assert refused.value.status_code==409
        assert profile.state(conn,tid)['isComplete'] is False
    finally:conn.close()


def test_concurrent_exact_retry_saves_one_revision_and_one_audit(owner_db,tenant,billing_connections):
    from concurrent.futures import ThreadPoolExecutor
    tid,uid=tenant
    def save_one(_):
        conn=billing_connections(tid,uid)
        try:
            result=profile.save(conn,tid,uid,step(1,0,country='JO',city='amman',language='ar'))
            conn.commit()
            return result
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save_one,range(2)))
    assert [r['revision'] for r in results]==[1,1]
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='ONBOARDING_STEP_SAVED'",(tid,))
        assert cur.fetchone()[0]==1

def test_original_setup_http_requires_auth_and_company_admin(owner_db,tenant,billing_connections):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.routers import onboarding
    from src.ai.core.security import TenantContext,get_tenant_context
    app=FastAPI();app.include_router(onboarding.router)
    with TestClient(app) as client:
        assert client.get('/onboarding/state').status_code==401
        assert client.put('/onboarding/state',json={'step':1,'expected_revision':0,'country':'JO','city':'amman','language':'en'}).status_code==401
        tid,uid=tenant
        app.dependency_overrides[get_tenant_context]=lambda:TenantContext(tid,uid)
        with owner_db.cursor() as cur:cur.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",(tid,uid))
        assert client.get('/onboarding/state').status_code==200
        assert client.put('/onboarding/state',json={'step':1,'expected_revision':0,'country':'JO','city':'amman','language':'en'}).status_code==403
        with owner_db.cursor() as cur:cur.execute("UPDATE tenant_users SET role_key='owner' WHERE tenant_id=%s AND user_id=%s",(tid,uid))
        assert client.put('/onboarding/state',json={'step':1,'expected_revision':0,'country':'JO','city':'amman','language':'en','tenant_id':'forged'}).status_code==422
        assert client.put('/onboarding/state',json={'step':1,'expected_revision':0,'country':'JO','city':'amman','language':'en'}).status_code==200

@pytest.mark.parametrize('seconds,eligible',[(48*3600,False),(48*3600+1,True),(47*3600,False)])
def test_review_and_checkout_share_the_original_trial_boundary(seconds,eligible):
    from datetime import datetime,timezone
    from src.ai.billing.service import checkout_trial_end
    now=1700000000
    actual=checkout_trial_end({'ends_at':datetime.fromtimestamp(now+seconds,timezone.utc)},now=now)
    assert actual==(now+seconds if eligible else None)
    assert checkout_trial_end(None,now=now) is None
