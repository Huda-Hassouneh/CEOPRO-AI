"""Real PostgreSQL restricted-role HTTP tests; provider payloads are synthetic."""
import base64,hashlib,hmac,json,os
from uuid import uuid4
import pytest,psycopg2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.ai import db
from src.ai.routers import provider_webhooks
from src.market_scraper.tests.test_provider_lifecycle_integration_db import lifecycle_seed,_tenant_app_connection,_verified,_app_url

@pytest.fixture
def fixture(lifecycle_seed,monkeypatch):
    admin,tenants=lifecycle_seed
    for tenant,actor,source in tenants:
        conn=_tenant_app_connection(tenant,actor);_verified(conn,tenant,source);conn.commit();conn.close()
    monkeypatch.setenv('SHOPIFY_CLIENT_SECRET','synthetic-local-webhook-secret')
    monkeypatch.setattr(db,'auth_lookup_connection',lambda:psycopg2.connect(_app_url()))
    app=FastAPI();app.include_router(provider_webhooks.router)
    yield TestClient(app),admin,tenants
    with admin.cursor() as c:c.execute('DELETE FROM keel_provider_privacy_requests WHERE tenant_id=ANY(%s::uuid[])',([x[0] for x in tenants],))

def send(client,tenant,source,topic='products/update',payload=None,delivery=None,domain=None):
    domain=domain or tenant.replace('-','')[:10]+'.myshopify.com'
    raw=json.dumps(payload if payload is not None else {'id':123},separators=(',',':')).encode()
    signature=base64.b64encode(hmac.new(b'synthetic-local-webhook-secret',raw,hashlib.sha256).digest()).decode()
    return client.post('/onboarding/shopify/webhooks/'+source,content=raw,headers={'X-Shopify-Hmac-Sha256':signature,'X-Shopify-Shop-Domain':domain,'X-Shopify-Topic':topic,'X-Shopify-Webhook-Id':delivery or str(uuid4())})

def test_durable_delivery_replay_content_conflict_and_shop_attribution(fixture):
    client,admin,ts=fixture;t,a,s=ts[0];delivery=str(uuid4())
    r=send(client,t,s,delivery=delivery);assert r.status_code==200,r.text;assert not r.json()['canonical_write_performed'] and r.json()['state']=='reconciliation_required'
    replay=send(client,t,s,delivery=delivery);assert replay.status_code==200 and replay.json()['duplicate']
    assert send(client,t,s,payload={'id':456},delivery=delivery).status_code==409
    assert send(client,t,s,domain='different.myshopify.com').status_code==404
    with admin.cursor() as c:
        c.execute("SELECT count(*) FROM audit_logs WHERE tenant_id=%s AND action_type='SHOPIFY_DELIVERY_RECORDED'",(t,));assert c.fetchone()[0]==1
        c.execute('SELECT payload_sha256,sanitized_metadata FROM keel_provider_delivery_receipts WHERE tenant_id=%s',(t,));digest,meta=c.fetchone();assert len(digest)==64 and meta=={'topic':'products/update'}

@pytest.mark.parametrize('topic',['customers/redact','shop/redact'])
def test_privacy_numeric_gid_identity_durable_hold_reimport_fence_and_rls(fixture,topic):
    client,admin,ts=fixture;t,a,s=ts[0];shop=int(__import__('uuid').UUID(t))%10**12
    payload={'shop_id':shop,'shop_domain':t.replace('-','')[:10]+'.myshopify.com','customer':{'id':456,'email':'private@example.test'},'orders_to_redact':[987]}
    r=send(client,t,s,topic,payload);assert r.status_code==200,r.text;assert r.json()['privacy_completed'] is False
    with admin.cursor() as c:
        c.execute('SELECT is_active FROM data_sources WHERE source_id=%s',(s,));assert c.fetchone()==(False,)
        c.execute('SELECT topic,status FROM keel_provider_privacy_requests WHERE source_id=%s',(s,));assert c.fetchone()==(topic,'policy_review_required')
        c.execute('SELECT is_active FROM data_sources WHERE source_id=%s',(ts[1][2],));assert c.fetchone()==(True,)
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):c.execute('UPDATE data_sources SET is_active=true WHERE source_id=%s',(s,))
    own=_tenant_app_connection(t,a)
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):_verified(own,t,s)
        own.rollback()
    finally:own.close()
    other=_tenant_app_connection(ts[1][0],ts[1][1])
    try:
        with other.cursor() as c:c.execute('SELECT * FROM keel_provider_privacy_requests');assert c.fetchall()==[]
        with other.cursor() as c:
            c.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname='keel_provider_privacy_requests'");assert c.fetchone()==(True,)
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):c.execute('DELETE FROM keel_provider_privacy_requests')
    finally:other.close()

def test_data_request_does_not_disable_collection_and_invalid_shop_never_persists(fixture):
    client,admin,ts=fixture;t,a,s=ts[0];shop=int(__import__('uuid').UUID(t))%10**12
    p={'shop_id':shop,'shop_domain':t.replace('-','')[:10]+'.myshopify.com','data_request':{'id':789}}
    assert send(client,t,s,'customers/data_request',p).status_code==200
    assert send(client,t,s,'customers/data_request',{**p,'shop_id':shop+1}).status_code==401
    assert send(client,t,s,'customers/data_request',p,domain='http://127.0.0.1').status_code==401
    with admin.cursor() as c:c.execute('SELECT is_active FROM data_sources WHERE source_id=%s',(s,));assert c.fetchone()==(True,)

def test_uninstall_disables_only_bound_shop_with_signed_id(fixture):
    client,admin,ts=fixture;t,a,s=ts[0];shop=int(__import__('uuid').UUID(t))%10**12
    assert send(client,t,s,'app/uninstalled',{'id':shop+1}).status_code==401
    assert send(client,t,s,'app/uninstalled',{'id':shop}).status_code==200
    with admin.cursor() as c:c.execute('SELECT is_active FROM data_sources WHERE source_id=%s',(s,));assert c.fetchone()==(False,)

def test_authentication_precedes_lookup_and_payload_is_bounded(fixture,monkeypatch):
    client,admin,ts=fixture;t,a,s=ts[0]
    monkeypatch.setattr(db,'auth_lookup_connection',lambda:pytest.fail('Unauthenticated lookup'))
    url='/onboarding/shopify/webhooks/'+s
    assert client.post(url,content=b'{}').status_code==401
    assert client.post(url,content=b'x'*(2*1024*1024+1)).status_code==413
    monkeypatch.delenv('SHOPIFY_CLIENT_SECRET');assert client.post(url,content=b'{}').status_code==503
