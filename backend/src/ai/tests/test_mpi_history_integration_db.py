import os,json
from uuid import uuid4
import psycopg2,pytest
from fastapi import Depends
from src.ai.routers import mpi
from src.ai.core.entitlements import requires
from src.ai.core import usage
from src.ai.core.security import create_access_token
from src.ai.tests.test_durable_upload_integration_db import setup
from src.ai.tests.test_products_integration_db import seeded_tenants
from src.ai.mpi.evidence import insert_evidence_record
from src.ai import db
from src.ai.core.exceptions import register_exception_handlers

@pytest.fixture
def history(setup):
    client,app,ts,us=setup;register_exception_handlers(app);app.include_router(mpi.router,dependencies=[requires(usage.MARKET_INTELLIGENCE)])
    for tenant,actor in zip(ts,us):
        conn=db.app_role_connection(tenant,actor)
        try:
            for _ in range(3):insert_evidence_record(conn,tenant,'UNKNOWN','ai.mpi',{'subject_type':'BUSINESS','subject_id':None,'status':'UNKNOWN','eligible_review_count':0},None,'Synthetic history fixture: no analyzed reviews.',None)
            conn.commit()
        finally:conn.close()
    return client,ts,us

def count(tenant,table):
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute('SELECT count(*) FROM '+table+' WHERE tenant_id=%s',(tenant,));return q.fetchone()[0]

def test_history_pagination_is_read_only_uncharged_and_uses_existing_evidence(history):
    client,ts,us=history;before={t:count(ts[0],t) for t in ['evidence_records','usage_ledger','tenant_usage_counters']}
    first=client.get('/mpi/history',params={'subject_type':'BUSINESS','limit':2});assert first.status_code==200,first.text;assert len(first.json()['items'])==2 and first.json()['has_more']
    second=client.get('/mpi/history',params={'subject_type':'BUSINESS','subject_id':ts[0],'offset':2});assert second.status_code==200 and len(second.json()['items'])==1
    assert not({x['evidence_id'] for x in first.json()['items']}&{x['evidence_id'] for x in second.json()['items']})
    assert all(item['result']['status']=='UNKNOWN' for item in first.json()['items'])
    assert before=={t:count(ts[0],t) for t in before}

def test_history_subject_and_tenant_boundaries_are_enforced(history):
    client,ts,us=history;a=client.get('/mpi/history',params={'subject_type':'BUSINESS'}).json()['items']
    assert client.get('/mpi/history',params={'subject_type':'BUSINESS','subject_id':ts[1]}).status_code==404
    assert client.get('/mpi/history',params={'subject_type':'PRODUCT','subject_id':str(uuid4())}).status_code==404
    assert client.get('/mpi/history',params={'subject_type':'PRODUCT','subject_id':'invalid'}).status_code==422
    assert client.get('/mpi/history',params={'subject_type':'OTHER'}).status_code==422
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    b=client.get('/mpi/history',params={'subject_type':'BUSINESS'}).json()['items'];assert not({x['evidence_id'] for x in a}&{x['evidence_id'] for x in b})
    client.headers.clear();assert client.get('/mpi/history',params={'subject_type':'BUSINESS'}).status_code==401

def test_history_retains_existing_market_entitlement_requirement(history):
    client,ts,us=history
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:q.execute("UPDATE tenant_plan_assignments SET status='cancelled' WHERE tenant_id=%s",(ts[0],))
    assert client.get('/mpi/history',params={'subject_type':'BUSINESS'}).status_code==402
