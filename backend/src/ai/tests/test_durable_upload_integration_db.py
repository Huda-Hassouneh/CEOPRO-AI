"""Real parser/staging/canonical PostgreSQL replay and interruption tests."""
import io,os
from datetime import date,timedelta
from uuid import uuid4
import pytest,psycopg2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.ai.core.security import TenantContext,get_tenant_context,create_access_token
from src.ai.routers import extraction
from src.ai import db
from src.ai.tests.test_products_integration_db import seeded_tenants

@pytest.fixture
def setup(seeded_tenants,monkeypatch):
    ts,us=seeded_tenants
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        for t in ts:q.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end) VALUES(%s,'growth','active',%s,%s)",(t,date.today(),date.today()+timedelta(days=30)))
    monkeypatch.setattr(db,'minio_client',lambda:None)
    monkeypatch.setattr(extraction,'_publish_discovery_request',lambda *a:None)
    monkeypatch.setattr(extraction,'_refresh_forecasts',lambda *a:None)
    app=FastAPI();app.include_router(extraction.router)
    client=TestClient(app);client.headers['Authorization']='Bearer '+create_access_token(ts[0],us[0],email_verified=True)[0]
    return client,app,ts,us

def upload(client,key,name='Example'):
    content=f'product_name,quantity,unit_price,currency,transaction_date\n{name},5,10,JOD,2026-10-26\n'.encode()
    return client.post('/extraction/upload',files={'file':('fixture.csv',content,'text/csv')},headers={'Idempotency-Key':key})

def counts(t):
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as c,c.cursor() as q:
        result={}
        for table in ['keel_file_upload_requests','ingestion_jobs','import_staging_rows','transactions','invoices']:
            q.execute(f'SELECT count(*) FROM {table} WHERE tenant_id=%s',(t,));result[table]=q.fetchone()[0]
        q.execute("SELECT coalesce(sum(used),0) FROM tenant_usage_counters WHERE tenant_id=%s AND feature_code='document_extraction'",(t,));result['document_usage']=int(q.fetchone()[0]);return result

def test_completed_replay_is_one_job_one_charge_and_tenant_actor_scoped(setup):
    client,app,ts,us=setup;k=str(uuid4());first=upload(client,k);assert first.status_code==200,first.text
    second=upload(client,k);assert second.status_code==200 and second.json()==first.json()
    assert counts(ts[0])=={'keel_file_upload_requests':1,'ingestion_jobs':1,'import_staging_rows':1,'transactions':1,'invoices':1,'document_usage':1}
    assert upload(client,k,'Changed').status_code==409
    assert client.get('/extraction/upload-requests/'+k).json()['state']=='completed'
    client.headers['Authorization']='Bearer '+create_access_token(ts[1],us[1],email_verified=True)[0]
    assert client.get('/extraction/upload-requests/'+k).status_code==404

@pytest.mark.parametrize('point',['after_processing','after_canonical_commit'])
def test_interruption_resumes_same_staging_and_preserves_once_only_allowance(setup,monkeypatch,point):
    client,app,ts,us=setup;k=str(uuid4())
    target=extraction.ingestion_pipeline if point=='after_processing' else extraction
    name='process_records' if point=='after_processing' else '_summary_response';original=getattr(target,name)
    def interrupted(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('Synthetic crash after durable boundary')
    monkeypatch.setattr(target,name,interrupted)
    with pytest.raises(RuntimeError) if point=='after_canonical_commit' else _expect_http_failure():
        first=upload(client,k)
        if point=='after_processing':assert first.status_code==500
    before=counts(ts[0]);assert before['document_usage']==1 and before['ingestion_jobs']==1 and before['import_staging_rows']==1
    monkeypatch.setattr(target,name,original);second=upload(client,k);assert second.status_code==200,second.text
    assert counts(ts[0])=={'keel_file_upload_requests':1,'ingestion_jobs':1,'import_staging_rows':1,'transactions':1,'invoices':1,'document_usage':1}
    assert upload(client,k).json()==second.json()

from contextlib import nullcontext as _expect_http_failure


def test_company_deletion_reports_retained_durable_import_evidence(setup):
    from src.ai import company_data
    client,app,ts,us=setup;assert upload(client,str(uuid4())).status_code==200
    with psycopg2.connect(os.environ['AI_TEST_DATABASE_URL']) as conn:
        with pytest.raises(company_data.DeletionBlocked,match='integration_evidence_review'):company_data.delete_company(conn,ts[0])
        conn.rollback()
        with conn.cursor() as q:q.execute('SELECT count(*) FROM keel_file_upload_requests WHERE tenant_id=%s',(ts[0],));assert q.fetchone()==(1,)
