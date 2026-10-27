"""Password-authenticated production billing entry points, disposable PG only.
Stripe network is doubled; signature verification, authorization, SQL and RLS are real.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import time
import uuid

import psycopg2
import pytest

from src.ai import db
from src.ai.billing import admin, credits, maintenance, store, stripe_api
from src.ai.core import usage
from .test_contract import signed
from .test_database import live_subscription


@pytest.fixture
def restricted_runtime(monkeypatch, owner_db):
    for key in ("BILLING_SETUP_DB_PASSWORD", "BILLING_WEBHOOK_DB_PASSWORD", "CREDIT_ACCOUNTING_DB_PASSWORD"):
        assert os.environ.get(key), f"Run repository test command to provision {key}"
    monkeypatch.delenv("KEEL_TEST_DISABLE_METERING", raising=False)
    monkeypatch.setenv("UNASSIGNED_PLAN_ACCESS", "none")
    monkeypatch.setenv("DATABASE_URL", os.environ["SCRAPER_DATABASE_URL"])
    monkeypatch.setattr(db, "system_connection", lambda: pytest.fail("Administrative connection reached runtime"))
    db.close_pool()
    yield
    db.close_pool()


@pytest.fixture
def send(client, monkeypatch, owner_db, restricted_runtime):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_offline")
    ids = []
    def deliver(kind, obj, event_id=None, created=None):
        event_id = event_id or "evt_" + uuid.uuid4().hex
        ids.append(event_id)
        payload = json.dumps(dict(id=event_id, object="event", type=kind, livemode=False,
                                 created=created or int(time.time()), data={"object": obj})).encode()
        return client.post("/billing/webhook", content=payload,
                           headers={"Stripe-Signature": signed(payload, "whsec_offline")})
    yield deliver
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM billing_webhook_events WHERE stripe_event_id=ANY(%s)", (ids,))


def deny(conn, sql, params=None):
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql, params)
    conn.rollback()


@pytest.mark.parametrize("role,login", [("ceopro_billing_webhook",True),("ceopro_credit_accounting",True),
                                      ("ceopro_billing_lookup",False),("ceopro_schedule_writer",False)])
def test_trusted_role_attributes_and_ddl_are_restricted(owner_db, role, login):
    with owner_db.cursor() as cur:
        cur.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolcanlogin FROM pg_roles WHERE rolname=%s", (role,))
        assert cur.fetchone() == (False,False,False,False,False,False,login)
        cur.execute("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s)", (role,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s)", (role,))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT has_schema_privilege(%s,'public','CREATE'),has_database_privilege(%s,current_database(),'CREATE')", (role,role))
        assert cur.fetchone() == (False,False)


def test_password_authenticated_capabilities_do_not_overlap(owner_db,tenant,restricted_runtime):
    tid,uid=tenant
    with closing(db.billing_setup_connection(tid,uid)) as setup, \
         closing(db.credit_accounting_connection(tid,uid)) as accounting, \
         closing(db.billing_webhook_connection("evt_no_receipt")) as webhook:
        for conn in (setup,accounting,webhook):
            deny(conn,"SET ROLE ceopro_app")
            deny(conn,"CREATE TABLE public.forbidden_billing_table(id int)")
        for conn in (setup,accounting):
            deny(conn,"INSERT INTO billing_webhook_events(stripe_event_id,event_type,event_created,payload) VALUES('evt_forged','invoice.paid',now(),'{}')")
            deny(conn,"INSERT INTO billing_payments(tenant_id,stripe_invoice_id,amount,currency,status) VALUES(%s,'in_forged',1,'USD','succeeded')",(tid,))
            deny(conn,"UPDATE billing_subscriptions SET status='active' WHERE tenant_id=%s",(tid,))
        deny(webhook,"INSERT INTO usage_ledger(tenant_id) VALUES(%s)",(tid,))
        deny(webhook,"UPDATE usage_plans SET monthly_price=1 WHERE plan_key='growth'")
        deny(accounting,"SELECT public.billing_provider_tenant('customer','cus_any')")
        with webhook.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id',%s,true)",(tid,))
        deny(webhook,"INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,'cus_unverified')",(tid,))


@pytest.mark.parametrize("header",[None,"invalid"])
def test_invalid_signature_never_opens_trusted_socket(client,monkeypatch,header):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET","whsec_offline")
    monkeypatch.setattr(db,"billing_webhook_connection",lambda *_:pytest.fail("Unverified request opened a trusted socket"))
    assert client.post("/billing/webhook",content=b"{}",headers={"Stripe-Signature":header} if header else {}).status_code==400


def test_event_receipt_scope_rebind_and_replay(owner_db,tenant,restricted_runtime):
    tid,_=tenant; eid="evt_bound_"+uuid.uuid4().hex
    with closing(db.billing_webhook_connection(eid)) as conn:
        assert store.claim_event(conn,eid,"invoice.paid",datetime.now(timezone.utc),{"data":{"object":{"id":"in_allowed"}}})
        conn.commit();conn.bind_tenant(tid)
        with pytest.raises(ValueError):conn.bind_tenant(str(uuid.uuid4()))
        deny(conn,"INSERT INTO billing_payments(tenant_id,stripe_invoice_id,amount,currency,status) VALUES(%s,'in_other',1,'USD','succeeded')",(tid,))
        conn.bind_tenant(tid)
        store.save_customer(conn,tid,"cus_bound_"+tid);conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM billing_customers WHERE tenant_id<>%s",(tid,));assert cur.fetchone()[0]==0
        deny(conn,"UPDATE billing_webhook_events SET payload='{}' WHERE stripe_event_id=%s",(eid,))
        store.finish_event(conn,eid,tid);conn.commit()
        deny(conn,"INSERT INTO billing_customers(tenant_id,stripe_customer_id) VALUES(%s,'cus_after_finish')",(tid,))


def test_signed_activation_renewal_failure_recovery_and_cancel(send,owner_db,tenant,test_price,monkeypatch):
    tid,_=tenant;plan,price=test_price;live=live_subscription(tid,price)
    monkeypatch.setattr(stripe_api,"retrieve_subscription",lambda _:live)
    event="evt_replay_"+uuid.uuid4().hex
    obj=dict(mode="subscription",subscription=live["id"],customer=live["customer"],client_reference_id=tid)
    assert send("checkout.session.completed",obj,event).status_code==200
    assert send("checkout.session.completed",obj,event).json()["duplicate"] is True
    with closing(db.app_role_connection(*tenant)) as conn:
        assert usage.get_plan(conn,tid)["status"]=="active"
    invoice={"id":"in_lifecycle_"+uuid.uuid4().hex,"customer":live["customer"],"subscription":live["id"],
             "status":"open","amount_due":5500,"currency":"usd"}
    monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:invoice)
    live["status"]="past_due"
    assert send("invoice.payment_failed",invoice).status_code==200
    with closing(db.app_role_connection(*tenant)) as conn:
        assert usage.get_plan(conn,tid)["status"]=="past_due"
        with pytest.raises(credits.BudgetError) as error:credits.ensure_available(tid,"data")
        assert error.value.reason=="SUBSCRIPTION_INACTIVE"
    live["status"]="active";live["items"]["data"][0]["current_period_start"]+=86400*30
    live["items"]["data"][0]["current_period_end"]+=86400*30
    invoice.update(status="paid",paid=True,amount_paid=5500)
    assert send("invoice.paid",invoice).status_code==200
    assert store.current_subscription(owner_db,tid)["status"]=="active"
    with owner_db.cursor() as cur:
        cur.execute("SELECT status,count(*) FROM billing_payments WHERE tenant_id=%s GROUP BY status",(tid,));assert cur.fetchall()==[("succeeded",1)]
    # Old event snapshots cannot undo fresh provider state.
    assert send("customer.subscription.updated",{"id":live["id"],"status":"past_due"},created=int(time.time())-500).status_code==200
    assert store.current_subscription(owner_db,tid)["status"]=="active"
    live["status"]="canceled"
    assert send("customer.subscription.deleted",{"id":live["id"]}).status_code==200
    with closing(db.app_role_connection(*tenant)) as conn:
        assert usage.get_plan(conn,tid)["status"]=="cancelled"


@pytest.fixture
def funded(tenant,owner_db,restricted_runtime):
    tid,_=tenant
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) VALUES(%s,'growth','active',current_date,current_date+30,'manual')",(tid,))
    providers={}
    for kind in ("data","ai"):
        provider="offline_"+uuid.uuid4().hex
        admin.set_price(owner_db,budget_kind=kind,provider=provider,operation="op",unit="request",unit_cost_usd=Decimal("0.01"),
                        source="disposable fixture only",verified_on=date.today(),approved_by="test",reason="restricted integration",safety_margin=Decimal("0"))
        providers[kind]=provider
    yield tid,providers
    with owner_db.cursor() as cur:cur.execute("DELETE FROM provider_cost_schedules WHERE provider=ANY(%s)",(list(providers.values()),))


@pytest.mark.parametrize("kind",["data","ai"])
def test_credits_password_role_reserve_settle_and_replay(funded,tenant,owner_db,kind):
    tid,providers=funded
    with credits.metering(tid,"restricted_test",actor_user_id=tenant[1]):
        receipt=credits.reserve(kind,providers[kind],"op",{"request":1},idempotency_key="once")
        result=credits.settle(receipt,{"request":1})
        assert result>0
        assert credits.settle(receipt,{"request":1})==0
        with pytest.raises(credits.BudgetError):credits.reserve(kind,providers[kind],"op",{"request":1},idempotency_key="once")
    with owner_db.cursor() as cur:
        cur.execute("SELECT reserved_credits,consumed_credits FROM tenant_credit_balances WHERE tenant_id=%s AND budget_kind=%s",(tid,kind))
        reserved,consumed=cur.fetchone();assert reserved==0 and consumed==result
        cur.execute("SELECT count(*) FROM usage_ledger WHERE tenant_id=%s AND budget_kind=%s",(tid,kind));assert cur.fetchone()[0]==1
    with closing(db.credit_accounting_connection(str(uuid.uuid4()))) as other:
        with other.cursor() as cur:
            cur.execute("SELECT count(*) FROM usage_ledger WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]==0
            cur.execute("UPDATE tenant_credit_balances SET consumed_credits=0 WHERE tenant_id=%s",(tid,));assert cur.rowcount==0


def test_credit_concurrency_expiry_reconciliation_and_global_cap(funded,owner_db):
    tid,providers=funded;provider=providers["data"]
    def reserve_once(_):
        with credits.metering(tid,"restricted_test"):
            try:return credits.reserve("data",provider,"op",{"request":1},idempotency_key="parallel").ledger_id
            except credits.BudgetError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(reserve_once,range(4)))
    assert len([r for r in results if r])==1
    ledger=next(r for r in results if r)
    with owner_db.cursor() as cur:cur.execute("UPDATE usage_ledger SET created_at=now()-interval '1 day' WHERE ledger_id=%s",(ledger,))
    assert maintenance.run_once()["expired_reservations"]==1
    assert maintenance.run_once()["expired_reservations"]==0
    with closing(db.credit_accounting_connection(tid)) as conn:
        assert credits.reconcile(conn,ledger,Decimal("0.005"),reference="final-provider-invoice",reason="test",actor="test")<0
        conn.commit()
        assert credits.reconcile(conn,ledger,Decimal("0.005"),reference="final-provider-invoice",reason="test",actor="test")==0
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT public.billing_provider_month_spend(%s,NULL,%s)",(provider,datetime.now(timezone.utc)-timedelta(days=32)))
            assert cur.fetchone()[0]==Decimal("0.005")
        deny(conn,"INSERT INTO usage_ledger_adjustments(tenant_id,budget_kind,period_start,credits_delta,kind,reference,reason,actor) VALUES(%s,'data',current_date,100,'admin_credit','forged','test','test')",(tid,))


def test_metered_request_reserve_replay_and_failure_release(funded,tenant):
    tid,_=funded
    receipt=usage.reserve_request(tid,"monthly_reports","report-1",tenant[1])
    assert receipt is not None
    usage.release_request(receipt)
    receipt=usage.reserve_request(tid,"monthly_reports","report-1",tenant[1])
    assert usage.reserve_request(tid,"monthly_reports","report-1",tenant[1]) is None
    usage.release_request(receipt)  # A replayed receipt cannot refund successful work.
    with closing(db.credit_accounting_connection(tid)) as conn:
        assert usage._metered_used(conn,tid,"monthly_reports",receipt["period_start"])==1


def test_trial_and_checkout_use_real_password_authenticated_connections(client,tenant,test_price,restricted_runtime,monkeypatch,owner_db):
    from src.ai.core.security import create_access_token
    tid,uid=tenant;plan,_=test_price
    headers={"Authorization":"Bearer "+create_access_token(tid,uid,email_verified=True)[0]}
    trial=client.post("/billing/trial",json={"plan_key":"growth"},headers=headers)
    assert trial.status_code==200,trial.json()
    assert client.post("/billing/trial",json={"plan_key":"growth"},headers=headers).status_code==409
    monkeypatch.setenv("STRIPE_SECRET_KEY","sk_test_offline")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN","http://127.0.0.1:15173")
    monkeypatch.setattr(stripe_api,"create_customer",lambda *a,**kw:{"id":"cus_password_"+tid})
    calls=[]
    def create(params,idempotency_key):
        calls.append(idempotency_key)
        return {"id":"cs_password_"+tid,"url":"https://checkout.stripe.test/offline"}
    monkeypatch.setattr(stripe_api,"create_checkout_session",create)
    monkeypatch.setattr(stripe_api,"retrieve_checkout_session",lambda sid:{"id":sid,"status":"open","url":"https://checkout.stripe.test/offline"})
    for _ in range(2):
        response=client.post("/billing/checkout",json={"plan_key":plan,"period_code":"monthly"},headers=headers)
        assert response.status_code==200,response.json()
    assert len(calls)==1
    with owner_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM billing_checkout_attempts WHERE tenant_id=%s AND state='open'",(tid,));assert cur.fetchone()[0]==1
        cur.execute("SELECT count(*) FROM billing_subscriptions WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]==0


def test_schedule_command_cannot_change_active_rights(send,tenant,test_price,monkeypatch,owner_db):
    tid,uid=tenant;_,price=test_price;live=live_subscription(tid,price)
    monkeypatch.setattr(stripe_api,"retrieve_subscription",lambda _:live)
    assert send("customer.subscription.created",{"id":live["id"]}).status_code==200
    with closing(db.billing_setup_connection(tid,uid)) as conn:
        store.set_schedule(conn,tid,live["id"],"starter","monthly");conn.commit()
        deny(conn,"UPDATE billing_subscriptions SET status='active' WHERE tenant_id=%s",(tid,))
        store.set_schedule(conn,tid,live["id"],None,None);conn.commit()
    assert store.current_subscription(owner_db,tid)["plan_key"]==test_price[0]


def test_new_definers_have_fixed_search_paths_and_no_public_execute(owner_db):
    names=["billing_provider_tenant","billing_provider_month_spend","billing_expired_credit_tenants","billing_setup_schedule","billing_accounting_principal"]
    with owner_db.cursor() as cur:
        cur.execute("SELECT p.proname,r.rolname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,p.proconfig,"
                    "EXISTS(SELECT FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') "
                    "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.pronamespace='public'::regnamespace AND p.proname=ANY(%s)",(names,))
        rows=cur.fetchall();assert len(rows)==len(names)
        for name,owner,login,superuser,bypass,config,public_execute in rows:
            assert owner in ("ceopro_billing_lookup","ceopro_schedule_writer")
            assert not any((login,superuser,bypass,public_execute)),name
            assert config==["search_path=pg_catalog, public, pg_temp"]


from .test_custom_quote_lifecycle_db import quote_actors, _submit_and_price


def test_custom_paid_activation_and_frozen_limits_use_webhook_role(send,quote_actors,owner_db,monkeypatch):
    from src.ai.billing import custom_offers
    a=quote_actors;tid,uid=a["tenant_a"],a["user_a"]
    with closing(db.app_role_connection(a["platform_tenant"],a["platform_user"])) as operator, \
         closing(db.app_role_connection(tid,uid)) as customer:
        quote=custom_offers.create_draft(operator,tenant_id=tid,customer_user_id=uid,idempotency_key=uuid.uuid4().hex,
            configuration={"enabledFeatures":["market_intelligence"]},feature_quantities={"tracked_products":1},commercial_terms={},economic_inputs={},fx_evidence={})
        operator.commit();_submit_and_price(operator,quote)
        custom_offers.transition(operator,"approve",tenant_id=None,quote_id=str(quote["quote_id"]),expected_revision=1,idempotency_key=uuid.uuid4().hex,approval_reference="SYNTHETIC_TEST_ONLY")
        operator.commit()
        custom_offers.transition(customer,"accept",tenant_id=tid,quote_id=str(quote["quote_id"]),expected_revision=1,idempotency_key=uuid.uuid4().hex)
        customer.commit()
        attempt=custom_offers.prepare_checkout_attempt(customer,tenant_id=tid,quote_id=str(quote["quote_id"]),idempotency_key=uuid.uuid4().hex)
        customer.commit()
        session="cs_test_"+uuid.uuid4().hex
        custom_offers.record_custom_checkout_session(customer,attempt_id=str(attempt["attempt_id"]),session_id=session)
        customer.commit()
        with owner_db.cursor() as cur:
            cur.execute("SELECT revision_id FROM billing_custom_quote_revisions WHERE quote_id=%s",(str(quote["quote_id"]),));revision=str(cur.fetchone()[0])
        live=live_subscription(tid,"price_custom_offline")
        live.update(id="sub_"+uuid.uuid4().hex,customer="cus_"+uuid.uuid4().hex)
        live["metadata"].update(billing_kind="custom_quote",quote_attempt_id=str(attempt["attempt_id"]),custom_quote_id=str(quote["quote_id"]),custom_quote_revision_id=revision)
        store.save_customer(owner_db,tid,live["customer"])
        monkeypatch.setattr(stripe_api,"retrieve_subscription",lambda _:live)
        invoice=dict(id="in_"+uuid.uuid4().hex,customer=live["customer"],subscription=live["id"],currency="usd",amount_paid=1200,status="paid",paid=True,billing_reason="subscription_create",status_transitions={"paid_at":int(time.time())})
        monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:invoice)
        assert send("customer.subscription.created",{"id":live["id"]}).status_code==200
        assert store.current_subscription(owner_db,tid) is None
        paid=send("invoice.paid",invoice)
        assert paid.status_code==200,paid.json()
        assert send("invoice.paid",invoice).status_code==200
        with closing(db.app_role_connection(tid,uid)) as reader:
            plan=usage.get_plan(reader,tid)
            assert plan["plan_key"]=="custom" and plan["status"]=="active"
            assert plan["features"]["tracked_products"]["limit"]==1
            assert plan["features"]["data_credits"]["limit"]==0
            assert "market_intelligence" in plan["entitlements"]
        with owner_db.cursor() as cur:
            cur.execute("SELECT count(*) FROM billing_custom_contract_activations WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]==1
            cur.execute("SELECT count(*) FROM tenant_entitlement_overrides WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]==13
            cur.execute("SELECT count(*) FROM entitlement_audit_log WHERE tenant_id=%s",(tid,));assert cur.fetchone()[0]>=14
