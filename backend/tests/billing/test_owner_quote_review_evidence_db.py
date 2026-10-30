"""Real restricted-role proof of the original owner quote review read contract."""
from uuid import uuid4
import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.ai.billing import custom_offers
from src.ai.core.security import TenantContext
from src.ai.routers import platform


def test_owner_review_uses_restricted_connection_and_returns_history(owner_db, billing_connections, platform_owner_context, tenant, monkeypatch):
    pt, pu = platform_owner_context
    tid, uid = tenant
    conn = billing_connections(pt, pu)
    draft = custom_offers.create_draft(conn,tenant_id=tid,customer_user_id=uid,idempotency_key=str(uuid4()),configuration={'enabledFeatures':[]},feature_quantities={'team_seats':3},commercial_terms={},economic_inputs={},fx_evidence={})
    custom_offers.transition(conn,'submit',tenant_id=None,quote_id=str(draft['quote_id']),expected_revision=1,idempotency_key=str(uuid4()))
    conn.commit();conn.close()
    def forbidden():
        pytest.fail('Owner review must not request an administrative connection')
    monkeypatch.setattr(platform.db,'system_connection',forbidden)
    app=FastAPI();app.include_router(platform.router)
    app.dependency_overrides[platform.get_tenant_context]=lambda:TenantContext(pt,pu)
    with TestClient(app) as client:
        response=client.get('/platform/billing/custom-quotes/'+str(draft['quote_id']))
        assert response.status_code==200,response.text
        result=response.json();assert result['tenant_id']==tid
        assert result['feature_quantities']=={'team_seats':3}
        assert result['currentRevision']['pricingSnapshot']=={}
        assert len(result['revisions'])==1
        assert any(e['action']=='submitted' for e in result['events'])
        assert result['checkout_attempts']==[]
        assert client.get('/platform/billing/custom-quotes/'+str(uuid4())).status_code==404
    customer=billing_connections(tid,uid)
    try:
        with pytest.raises(custom_offers.CustomOfferError) as denied:
            custom_offers.admin_quote_detail(customer,str(draft['quote_id']))
        assert denied.value.status==403
        customer.rollback()
        with customer.cursor() as cur:
            cur.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()==(False,False)
            cur.execute("SELECT has_table_privilege(current_user,'billing_custom_pricing_policies','UPDATE')")
            assert cur.fetchone()==(False,)
    finally:customer.close()
