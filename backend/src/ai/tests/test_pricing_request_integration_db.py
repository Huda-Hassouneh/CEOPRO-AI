import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest,psycopg2
from src.ai import db
from src.ai.core.exceptions import register_exception_handlers
from src.ai.routers import pricing
from src.ai.pricing import pipeline
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.ai.routers.products import create_product
from src.ai.core.security import create_access_token

@pytest.fixture
def request_fixture(setup):
    client,app,ts,us=setup;app.include_router(pricing.router);register_exception_handlers(app)
    c=db.app_role_connection(ts[0],us[0])
    try:p=create_product(c,ts[0],us[0],{'en':'Pricing replay'},None,None,None,10,None,'JOD');c.commit()
    finally:c.close()
    return client,ts,us,p

def counts(t):
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        result={}
        for table in ['evidence_records','recommendation_outcomes','keel_pricing_request_results','usage_ledger']:
            q.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(t,));result[table]=q.fetchone()[0]
        return result

def recommend(client,p,key):return client.post('/pricing/recommend',params={'product_id':p['product_id']},headers={'Idempotency-Key':key})

def test_concurrent_request_replay_persists_one_unchanged_result_and_history(request_fixture):
    client,ts,us,p=request_fixture;key=str(uuid4());before=counts(ts[0])
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:recommend(client,p,key),[1,2]))
    assert all(r.status_code==200 for r in results),[r.text for r in results];assert results[0].json()==results[1].json()
    after=counts(ts[0]);assert after['evidence_records']==before['evidence_records']+1 and after['recommendation_outcomes']==before['recommendation_outcomes']+1 and after['keel_pricing_request_results']==1 and after['usage_ledger']==before['usage_ledger']
    assert client.get('/pricing/history/'+p['product_id']).json()['items'][0]['evidence_id']==results[0].json()['evidence_id']
    c=db.app_role_connection(ts[0],us[0])
    try:
        with c.cursor() as q:
            q.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname='keel_pricing_request_results'");assert q.fetchone()==(True,)
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):q.execute("UPDATE keel_pricing_request_results SET response='{}'")
    finally:c.close()

def test_failure_after_evidence_write_rolls_back_identity_and_safe_retry(request_fixture,monkeypatch):
    client,ts,us,p=request_fixture;key=str(uuid4());before=counts(ts[0]);original=pipeline.evidence.insert_recommendation_outcome
    monkeypatch.setattr(pipeline.evidence,'insert_recommendation_outcome',lambda *a:(_ for _ in ()).throw(RuntimeError('synthetic interruption')))
    with pytest.raises(RuntimeError):recommend(client,p,key)
    assert counts(ts[0])==before
    monkeypatch.setattr(pipeline.evidence,'insert_recommendation_outcome',original)
    assert recommend(client,p,key).status_code==200
    assert counts(ts[0])['keel_pricing_request_results']==1

def test_request_identity_conflicts_bad_uuid_and_cross_tenant_are_rejected(request_fixture):
    client,ts,us,p=request_fixture;key=str(uuid4());assert recommend(client,p,key).status_code==200
    assert recommend(client,{'product_id':str(uuid4())},key).status_code==409
    assert recommend(client,p,'bad key').status_code==422
    assert recommend(client,{'product_id':'invalid'},str(uuid4())).status_code==422
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    assert recommend(client,p,key).status_code==404
    c=db.app_role_connection(ts[1],us[1])
    try:
        with c.cursor() as q:q.execute('SELECT * FROM keel_pricing_request_results');assert q.fetchall()==[]
    finally:c.close()


def test_existing_company_deletion_still_works_after_pricing_replay_receipt(request_fixture):
    from src.ai import company_data
    client,ts,us,p=request_fixture;assert recommend(client,p,str(uuid4())).status_code==200
    conn=psycopg2.connect(os.environ['AI_TEST_DATABASE_URL'])
    try:
        with conn.cursor() as q:
            with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):q.execute('DELETE FROM keel_pricing_request_results WHERE tenant_id=%s',(ts[0],))
        conn.rollback()
        company_data.delete_company(conn,ts[0]);conn.commit()
        with conn.cursor() as q:q.execute('SELECT count(*) FROM companies WHERE tenant_id=%s',(ts[0],));assert q.fetchone()==(0,)
    finally:conn.close()


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("plan_key,status,expired_period", [
    ("growth", "active", False),
    ("custom", "active", False),
    ("growth", "trialing", False),
    ("growth", "expired", False),
    ("growth", "past_due", False),
    ("growth", "cancelled", False),
    ("growth", "trialing", True),
    (None, None, False),
])
def test_subscription_guard_uses_real_tenant_plan(request_fixture, bulk, plan_key, status, expired_period):
    from datetime import date, timedelta

    client, tenants, users, product = request_fixture
    tenant = tenants[0]
    with psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"]) as admin, admin.cursor() as cursor:
        if plan_key is None:
            cursor.execute("DELETE FROM tenant_plan_assignments WHERE tenant_id=%s", (tenant,))
        else:
            end = date.today() + timedelta(days=-1 if expired_period else 30)
            cursor.execute(
                "UPDATE tenant_plan_assignments SET plan_key=%s,status=%s,source='contract',"
                "current_period_start=%s,current_period_end=%s WHERE tenant_id=%s",
                (plan_key, status, date.today() - timedelta(days=30), end, tenant),
            )
    restricted = db.app_role_connection(tenant, users[0])
    try:
        with restricted.cursor() as cursor:
            cursor.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cursor.fetchone() == ("ceopro_app", False, False)
    finally:
        restricted.close()
    before = counts(tenant)
    response = client.post("/pricing/recommend-all") if bulk else recommend(client, product, str(uuid4()))
    eligible = plan_key is not None and status in ("active", "trialing") and not expired_period
    if eligible:
        assert response.status_code == 200, response.text
        after = counts(tenant)
        assert after["evidence_records"] == before["evidence_records"] + 1
        assert after["recommendation_outcomes"] == before["recommendation_outcomes"] + 1
        assert after["usage_ledger"] == before["usage_ledger"]
    else:
        assert response.status_code == 402, response.text
        assert response.json()["detail"]["reason"] == "SUBSCRIPTION_INACTIVE"
        assert counts(tenant) == before


def test_persisted_replay_is_denied_after_subscription_expiry(request_fixture):
    client, tenants, _, product = request_fixture
    key = str(uuid4())
    first = recommend(client, product, key)
    assert first.status_code == 200, first.text
    before = counts(tenants[0])
    with psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"]) as admin, admin.cursor() as cursor:
        cursor.execute("UPDATE tenant_plan_assignments SET status='expired' WHERE tenant_id=%s", (tenants[0],))
    response = recommend(client, product, key)
    assert response.status_code == 402, response.text
    assert response.json()["detail"]["reason"] == "SUBSCRIPTION_INACTIVE"
    assert counts(tenants[0]) == before
