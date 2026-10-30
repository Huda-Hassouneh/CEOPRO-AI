from contextlib import contextmanager
from datetime import datetime, timezone
import uuid
import pytest
from src.ai.billing import checkout_attempts, service, store, stripe_api
from src.infrastructure.public_urls import frontend_origin


@pytest.mark.parametrize('origin',['http://evil.example','https://user:pass@example.com','https://app.example/path','https://app.example?x=1','https://app.example#x','javascript:alert(1)'])
def test_invalid_public_origin_is_refused(monkeypatch,origin):
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN',origin)
    with pytest.raises(ValueError):frontend_origin()


def test_frontend_origin_is_shared_explicit_and_validated(monkeypatch):
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:5203/')
    assert frontend_origin()=='http://127.0.0.1:5203'
    assert service.config.app_base_url()=='http://127.0.0.1:5203'


def test_different_legacy_origins_are_not_silently_used(monkeypatch):
    monkeypatch.delenv('PUBLIC_FRONTEND_ORIGIN',raising=False)
    monkeypatch.setenv('FRONTEND_BASE_URL','http://127.0.0.1:5203')
    monkeypatch.setenv('APP_BASE_URL','http://localhost:5173')
    with pytest.raises(ValueError):frontend_origin()


def test_pending_checkout_blocks_another_contract_and_reuses_same_session(monkeypatch,memory_checkout_reservations):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_offline')
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:5203')
    monkeypatch.setattr(store,'current_subscription',lambda *args:None)
    monkeypatch.setattr(store,'current_price',lambda *args:{'is_active':True,'self_serve':True,'stripe_price_id':'price_test'})
    calls=[]
    def create(*args,**kw):
        calls.append(kw['_attempt']['attempt_id'])
        return {'session_id':'cs_test_synthetic','url':'https://checkout.stripe.test'}
    monkeypatch.setattr(service,'_create_checkout',create)
    first=service.create_checkout(None,None,'tenant','owner@example.test','Fixture','growth','monthly')
    assert service.create_checkout(None,None,'tenant','owner@example.test','Fixture','growth','monthly')==first
    with pytest.raises(service.BillingError,match='pending'):
        service.create_checkout(None,None,'tenant','owner@example.test','Fixture','enterprise','monthly')
    assert len(calls)==1


def test_checkout_return_cannot_confirm_another_tenants_payment(monkeypatch):
    monkeypatch.setattr(stripe_api,'retrieve_checkout_session',lambda _: {'metadata':{'tenant_id':'other'},'status':'complete','payment_status':'paid'})
    with pytest.raises(service.BillingError) as err:service.checkout_status(None,'tenant','cs_test_synthetic')
    assert err.value.status==404


def test_paid_return_waits_for_matching_webhook_subscription(monkeypatch):
    monkeypatch.setattr(stripe_api,'retrieve_checkout_session',lambda _: {'metadata':{'tenant_id':'tenant'},'customer':'cus_synthetic',
        'subscription':'sub_new','status':'complete','payment_status':'paid'})
    monkeypatch.setattr(store,'customer_id',lambda *args:'cus_synthetic')
    monkeypatch.setattr(store,'current_subscription',lambda *args:{'stripe_subscription_id':'sub_old','status':'active'})
    assert service.checkout_status(None,'tenant','cs_test_synthetic')['state']=='pending'


def test_unreconciled_provider_subscription_prevents_another_purchase(monkeypatch,memory_checkout_reservations):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_offline')
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:5204')
    monkeypatch.setattr(store,'current_subscription',lambda *args:None)
    monkeypatch.setattr(store,'customer_id',lambda *args:'cus_synthetic')
    monkeypatch.setattr(store,'current_price',lambda *args:{'is_active':True,'self_serve':True,'stripe_price_id':'price_synthetic'})
    monkeypatch.setattr(stripe_api,'customer_subscriptions',lambda *args:[{'id':'sub_existing','status':'active'}])
    with pytest.raises(service.BillingError) as error:
        service.create_checkout(None,None,'tenant','owner@example.test','Fixture','growth','monthly')
    assert error.value.code=='checkout_reconciling'
    assert memory_checkout_reservations=={}, 'No reservation or provider creation should precede reconciliation'


def test_checkout_reservation_persists_and_is_immutable(owner_db,tenant):
    tid,_=tenant
    with checkout_attempts.tenant_lock(owner_db,tid):
        row=checkout_attempts.reserve(owner_db,tid,'synthetic-key','growth','monthly')
        params={'success_url':'http://127.0.0.1:5203/billing','line_items':[{'price':'price_synthetic'}]}
        assert checkout_attempts.freeze(owner_db,row,params)==params
        assert checkout_attempts.freeze(owner_db,row,{'tampered':True})==params
        checkout_attempts.opened(owner_db,row,{'id':'cs_test_'+uuid.uuid4().hex})
        assert str(checkout_attempts.active(owner_db,tid)['attempt_id'])==row['attempt_id']
    import psycopg2
    with owner_db.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute('UPDATE billing_checkout_attempts SET request_key=%s WHERE tenant_id=%s',('tampered',tid))
    owner_db.rollback()


def test_checkout_reservation_force_rls_and_restricted_writes(owner_db):
    with owner_db.cursor() as cur:
        cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='billing_checkout_attempts'::regclass")
        assert cur.fetchone()==(True,True)
        cur.execute("SELECT has_table_privilege('ceopro_app','billing_checkout_attempts','INSERT'),has_table_privilege('ceopro_app','billing_checkout_attempts','UPDATE')")
        assert cur.fetchone()==(False,False)


def test_concurrent_checkout_uses_one_provider_creation(owner_db,tenant,test_price,billing_connections,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from src.ai import db
    import time
    tid,uid=tenant
    plan,price=test_price
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_offline')
    monkeypatch.setenv('PUBLIC_FRONTEND_ORIGIN','http://127.0.0.1:5204')
    monkeypatch.setattr(stripe_api,'create_customer',lambda *a,**kw:{'id':'cus_synthetic_'+tid})
    sessions=[]
    def create(params,idempotency_key):
        time.sleep(0.1)
        sessions.append(idempotency_key)
        return {'id':'cs_test_'+tid,'url':'https://checkout.stripe.test','status':'open'}
    monkeypatch.setattr(stripe_api,'create_checkout_session',create)
    monkeypatch.setattr(stripe_api,'retrieve_checkout_session',lambda sid:{'id':sid,'url':'https://checkout.stripe.test','status':'open'})
    def request():
        conn=billing_connections(tid,uid);system=db.system_connection()
        try:return service.create_checkout(conn,system,tid,'fixture@example.test','Fixture',plan,'monthly')
        finally:conn.close();system.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:request(),range(2)))
    assert results[0]==results[1]
    assert len(sessions)==1
    with owner_db.cursor() as cur:
        cur.execute('SELECT count(*) FROM billing_checkout_attempts WHERE tenant_id=%s',(tid,))
        assert cur.fetchone()[0]==1


def test_checkout_attempts_are_tenant_isolated(owner_db,tenant,billing_connections):
    tid,uid=tenant
    row=checkout_attempts.reserve(owner_db,tid,'synthetic-isolation','growth','monthly')
    conn=billing_connections(tid,uid)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT attempt_id FROM billing_checkout_attempts')
            assert [str(item[0]) for item in cur.fetchall()]==[row['attempt_id']]
            import psycopg2
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code) VALUES(gen_random_uuid(),%s,'forged','growth','monthly')",(tid,))
        conn.rollback()
    finally:conn.close()
