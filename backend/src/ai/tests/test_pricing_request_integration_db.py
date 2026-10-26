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
