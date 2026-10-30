"""Trial transition integrity on real restricted PostgreSQL/HTTP boundaries.

Only Stripe HTTP is doubled. This provider double reproduces the observed Stripe
phase replacement: omitting trial_end ends a current trial, not just its label.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import time
import uuid

import pytest

from src.ai import db
from src.ai.billing import admin, credits, service, store, stripe_api
from src.ai.core import usage
from src.ai.core.security import create_access_token
from .test_database import live_subscription
from .test_reconciliation_roles import restricted_runtime, send  # noqa: F401


class TrialProvider:
    """Stateful offline Stripe contract, including the historical failure mode."""
    def __init__(self, tenant, price):
        self.live = live_subscription(tenant, price, status="trialing")
        self.live["trial_end"] = int(time.time()) + 14 * 86400
        self.live["items"]["data"][0]["current_period_end"] = self.live["trial_end"]
        self.original = deepcopy(self.live)
        self.schedules = {}
        self.creates = 0
        self.updates = []
        self.releases = 0

    def install(self, monkeypatch):
        for name, method in (("retrieve_subscription", self.subscription),
                             ("create_schedule_from_subscription", self.create),
                             ("retrieve_schedule", self.schedule),
                             ("modify_schedule", self.modify),
                             ("release_schedule", self.release),
                             ("modify_subscription", self.upgrade)):
            monkeypatch.setattr(stripe_api, name, method)

    def subscription(self, sid):
        assert sid == self.live["id"]
        return deepcopy(self.live)

    def create(self, sid):
        assert sid == self.live["id"]
        self.creates += 1
        key = "sub_sched_offline_" + uuid.uuid4().hex
        start, end = store.period_bounds(self.live)
        phase = {"start_date": int(start.timestamp()), "end_date": int(end.timestamp()),
                 "items": [{"price": self.live["items"]["data"][0]["price"], "quantity": 1}],
                 "collection_method": "charge_automatically", "metadata": {"fixture": "trial-integrity"}}
        if self.live["status"] == "trialing":
            phase["trial_end"] = self.live["trial_end"]
        self.schedules[key] = {"id": key, "current_phase": {k: phase[k] for k in ("start_date", "end_date")}, "phases": [phase]}
        self.live["schedule"] = key
        return {"id": key}

    def schedule(self, sid):
        return deepcopy(self.schedules[sid])

    def modify(self, sid, **params):
        self.updates.append(deepcopy(params))
        first = params["phases"][0]
        if self.live["status"] == "trialing" and first.get("trial_end") != self.live["trial_end"]:
            # Observed production incident: clearing the phase cutoff ends the
            # trial and resets the paid billing anchor before any payment.
            self.live.update(status="active", trial_end=int(time.time()))
            self.live["items"]["data"][0].update(current_period_start=int(time.time()), current_period_end=int(time.time())+30*86400)
        self.schedules[sid]["phases"] = deepcopy(params["phases"])
        return self.schedule(sid)

    def release(self, sid):
        self.releases += 1
        self.live["schedule"] = None
        return {"id": sid, "status": "released"}

    def upgrade(self, sid, **params):
        assert sid == self.live["id"]
        assert self.live["status"] == "trialing"
        assert params["trial_end"] == self.original["trial_end"]
        assert params["proration_behavior"] == "none"
        self.live["items"]["data"][0]["price"] = {"id": params["items"][0]["price"]}
        return deepcopy(self.live)


@pytest.fixture
def plans(owner_db, tenant):
    keys = ["test_"+uuid.uuid4().hex[:18] for _ in range(3)]
    prices = ["price_offline_"+uuid.uuid4().hex for _ in keys]
    with owner_db.cursor() as cur:
        for tier, (key, price) in enumerate(zip(keys, prices), 1):
            cur.execute("INSERT INTO usage_plans(plan_key,display_name,monthly_price,currency,trial_days,tier_level,self_serve,is_active) VALUES(%s,'Synthetic trial integrity',%s,'USD',14,%s,TRUE,TRUE)", (key,55*tier,tier))
            cur.execute("INSERT INTO billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency,stripe_price_id) VALUES(%s,'monthly',1,0,%s,'USD',%s)", (key,55*tier,price))
            cur.execute("INSERT INTO usage_plan_limits(plan_key,feature_code,limit_value,trial_limit_value) SELECT %s,feature_code,limit_value,trial_limit_value FROM usage_plan_limits WHERE plan_key='growth'", (key,))
            cur.execute("INSERT INTO usage_plan_entitlements(plan_key,feature_code) SELECT %s,feature_code FROM usage_plan_entitlements WHERE plan_key='growth'", (key,))
    yield list(zip(keys, prices))
    with owner_db.cursor() as cur:
        cur.execute("DELETE FROM billing_subscriptions WHERE plan_key=ANY(%s)", (keys,))
        cur.execute("DELETE FROM tenant_plan_assignments WHERE plan_key=ANY(%s)", (keys,))
        cur.execute("DELETE FROM billing_plan_prices WHERE plan_key=ANY(%s)", (keys,))
        cur.execute("DELETE FROM usage_plan_limits WHERE plan_key=ANY(%s)", (keys,))
        cur.execute("DELETE FROM usage_plan_entitlements WHERE plan_key=ANY(%s)", (keys,))
        cur.execute("DELETE FROM usage_plans WHERE plan_key=ANY(%s)", (keys,))


@pytest.fixture
def trial(tenant, plans, send, monkeypatch, owner_db):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    provider = TrialProvider(tenant[0], plans[1][1])
    provider.install(monkeypatch)
    assert send("customer.subscription.created", {"id": provider.live["id"]}).status_code == 200
    headers = {"Authorization": "Bearer " + create_access_token(*tenant, email_verified=True)[0]}
    return provider, headers


def snapshot(owner_db, tid):
    with owner_db.cursor() as cur:
        cur.execute("SELECT plan_key,status,current_period_start,current_period_end,catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s", (tid,))
        assignment = cur.fetchone()
        cur.execute("SELECT budget_kind,period_start,reserved_credits,consumed_credits FROM tenant_credit_balances WHERE tenant_id=%s ORDER BY budget_kind,period_start", (tid,))
        balances = cur.fetchall()
    sub = store.current_subscription(owner_db, tid)
    return assignment, balances, tuple(sub[k] for k in ("status","current_period_start","current_period_end","trial_end"))


def change(client, headers, plan):
    return client.post("/billing/change-plan", json={"plan_key": plan, "period_code": "monthly"}, headers=headers)


def test_provider_contract_reproduces_omitted_trial_end():
    provider = TrialProvider(str(uuid.uuid4()), "price_offline")
    sid = provider.create(provider.live["id"])["id"]
    first = provider.schedule(sid)["phases"][0]
    del first["trial_end"]
    provider.modify(sid, phases=[first, {"items": [{"price": "price_other"}]}])
    assert provider.live["status"] == "active"
    assert provider.live["trial_end"] < provider.original["trial_end"]


def test_trial_downgrade_repeat_cancel_and_multiple_transitions(client, trial, plans, owner_db, tenant, send):
    provider, headers = trial
    before = snapshot(owner_db, tenant[0])
    response = change(client, headers, plans[0][0])
    assert response.status_code == 200, response.json()
    assert response.json()["effective_at"] == store._ts(provider.original["trial_end"]).isoformat()
    assert provider.live["status"] == "trialing"
    assert provider.updates[0]["phases"][0]["trial_end"] == provider.original["trial_end"]
    assert provider.updates[0]["phases"][0]["metadata"] == {"fixture":"trial-integrity"}
    assert provider.updates[0]["proration_behavior"] == "none"
    assert snapshot(owner_db, tenant[0]) == before
    assert change(client, headers, plans[0][0]).status_code == 409
    assert provider.creates == len(provider.updates) == 1
    assert send("customer.subscription.updated", {"id":provider.live["id"]}).status_code == 200
    assert snapshot(owner_db, tenant[0]) == before
    assert client.delete("/billing/scheduled-change", headers=headers).status_code == 200
    assert snapshot(owner_db, tenant[0]) == before
    assert change(client, headers, plans[0][0]).status_code == 200
    assert change(client, headers, plans[2][0]).status_code == 200
    assert provider.live["trial_end"] == provider.original["trial_end"]
    assert provider.live["status"] == "trialing"
    # The upgrade remains a trial; only a signed reconciliation updates its plan.
    assert snapshot(owner_db, tenant[0]) == before
    assert send("customer.subscription.updated", {"id":provider.live["id"]}).status_code == 200
    assert store.current_subscription(owner_db,tenant[0])["status"] == "trialing"
    assert change(client, headers, plans[0][0]).status_code == 200
    assert provider.updates[-1]["phases"][0]["end_date"] == provider.original["trial_end"]


@pytest.mark.parametrize("mutation", ["truncated", "extended", "stale_status", "stale_period"])
def test_missing_reconciliation_cannot_drive_plan_mutation(client, trial, plans, mutation, owner_db, tenant):
    provider, headers = trial
    before = snapshot(owner_db, tenant[0])
    if mutation == "truncated":
        provider.live.update(status="active", trial_end=int(time.time()))
    elif mutation == "extended":
        provider.live["trial_end"] += 86400
    elif mutation == "stale_status":
        provider.live["status"] = "past_due"
    else:
        provider.live["items"]["data"][0]["current_period_end"] += 86400
    response = change(client, headers, plans[0][0])
    assert response.status_code == 409, response.json()
    assert provider.creates == 0
    assert snapshot(owner_db, tenant[0]) == before


@pytest.mark.parametrize("kind", ["truncated", "extended", "early_active", "failed_with_changed_cutoff"])
def test_signed_but_invalid_trial_boundary_cannot_grant_paid_access(trial, owner_db, tenant, send, kind):
    provider, _ = trial
    before = snapshot(owner_db, tenant[0])
    if kind == "early_active":
        provider.live["status"] = "active"
    elif kind == "failed_with_changed_cutoff":
        provider.live.update(status="past_due", trial_end=int(time.time()))
    else:
        provider.live["trial_end"] += -86400 if kind == "truncated" else 86400
    event = "evt_rejected_" + uuid.uuid4().hex
    response = send("customer.subscription.updated", {"id":provider.live["id"]}, event)
    assert response.status_code == 500
    assert snapshot(owner_db, tenant[0]) == before
    with owner_db.cursor() as cur:
        cur.execute("SELECT error,processed_at FROM billing_webhook_events WHERE stripe_event_id=%s AND error IS NOT NULL", (event,))
        error, processed = cur.fetchone()
        assert "trial_boundary_conflict" in error and processed is None


def test_zero_trial_invoice_then_verified_first_payment_failure_recovery_and_replay(trial, owner_db, tenant, send, monkeypatch):
    provider, _ = trial
    live = provider.live
    invoice = {"id":"in_offline_"+uuid.uuid4().hex,"customer":live["customer"],"subscription":live["id"],"status":"paid","paid":True,"amount_paid":0,"amount_due":0,"currency":"usd"}
    live["latest_invoice"]=invoice["id"]
    monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:deepcopy(invoice))
    assert send("invoice.paid", invoice).status_code == 200
    assert store.current_subscription(owner_db,tenant[0])["status"] == "trialing"
    with closing(db.app_role_connection(*tenant)) as conn:
        assert usage.get_plan(conn,tenant[0],now=store._ts(live["trial_end"])-timedelta(seconds=1))["status"] == "trialing"
        assert usage.get_plan(conn,tenant[0],now=store._ts(live["trial_end"]))["status"] == "expired"
    # Provider-confirmed first period begins at the original trial end.
    live["status"] = "past_due"
    live["items"]["data"][0].update(current_period_start=live["trial_end"],current_period_end=live["trial_end"]+30*86400)
    invoice.update(id="in_first_"+uuid.uuid4().hex,status="open",paid=False,amount_due=11000,
                   lines={"data":[{"period":{"start":live["trial_end"],"end":live["trial_end"]+30*86400}}]})
    live["latest_invoice"]=invoice["id"]
    assert send("invoice.payment_failed",invoice).status_code == 200
    with pytest.raises(credits.BudgetError) as error:
        credits.ensure_available(tenant[0],"data")
    assert error.value.reason == "SUBSCRIPTION_INACTIVE"
    live["status"] = "active"
    invoice.update(status="paid",paid=True,amount_paid=11000)
    event = "evt_offline_"+uuid.uuid4().hex
    assert send("invoice.paid",invoice,event).status_code == 200
    before = snapshot(owner_db,tenant[0])
    assert before[2][0] == "active"
    assert send("invoice.paid",invoice,event).json()["duplicate"] is True
    assert send("customer.subscription.updated",{"id":live["id"],"status":"trialing"},created=int(time.time())-500).status_code == 200
    assert snapshot(owner_db,tenant[0]) == before
    with owner_db.cursor() as cur:
        cur.execute("SELECT amount,status FROM billing_payments WHERE tenant_id=%s ORDER BY amount",(tenant[0],))
        assert cur.fetchall() == [(Decimal('0.00'),'succeeded'), (Decimal('110.00'),'succeeded')]


def test_paid_downgrade_preserves_paid_period_and_failed_renewal_denies(client,trial,plans,tenant,owner_db,send,monkeypatch):
    provider, headers = trial
    provider.live["status"] = "active"
    provider.live["items"]["data"][0].update(current_period_start=provider.live["trial_end"],current_period_end=provider.live["trial_end"]+30*86400)
    paid={"id":"in_paid_"+uuid.uuid4().hex,"subscription":provider.live["id"],"customer":provider.live["customer"],
          "status":"paid","lines":{"data":[{"period":{"start":provider.live["trial_end"],"end":provider.live["trial_end"]+30*86400}}]}}
    provider.live["latest_invoice"]=paid["id"]
    monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:paid)
    assert send("customer.subscription.updated",{"id":provider.live["id"]}).status_code == 200
    before = snapshot(owner_db,tenant[0])
    assert change(client,headers,plans[0][0]).status_code == 200
    assert snapshot(owner_db,tenant[0]) == before
    provider.live["status"] = "past_due"
    invoice={"id":"in_offline_"+uuid.uuid4().hex,"subscription":provider.live["id"],"customer":provider.live["customer"],"status":"open","amount_due":11000,"currency":"usd"}
    monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:invoice)
    assert send("invoice.payment_failed",invoice).status_code == 200
    with pytest.raises(credits.BudgetError): credits.ensure_available(tenant[0],"ai")


def test_concurrent_downgrades_have_one_schedule(trial,plans,tenant,owner_db):
    provider, _ = trial
    def request(_):
        with closing(db.app_role_connection(*tenant)) as conn, closing(db.billing_setup_connection(*tenant)) as setup:
            try:
                return service.change_plan(conn,setup,tenant[0],plans[0][0],"monthly")["state"]
            except service.BillingError as exc:
                return exc.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(request,range(4)))
    assert results.count("scheduled") == 1
    assert results.count("already_scheduled") == 3
    assert provider.creates == len(provider.updates) == 1
    assert store.current_subscription(owner_db,tenant[0])["status"] == "trialing"


@pytest.mark.parametrize("kind",["data","ai"])
def test_trial_transitions_never_roll_credit_period_or_duplicate_budget(client,trial,plans,tenant,owner_db,kind):
    provider, headers = trial
    vendor="offline_"+uuid.uuid4().hex
    admin.set_price(owner_db,budget_kind=kind,provider=vendor,operation="op",unit="request",unit_cost_usd=Decimal('0.01'),source="synthetic isolated fixture",verified_on=date.today(),approved_by="test",reason="trial integrity",safety_margin=Decimal('0'))
    try:
        with credits.metering(tenant[0],"restricted_test",actor_user_id=tenant[1]):
            receipt=credits.reserve(kind,vendor,"op",{"request":1},idempotency_key="before")
            credits.settle(receipt,{"request":1})
        before=snapshot(owner_db,tenant[0])
        assert before[1]
        assert change(client,headers,plans[0][0]).status_code == 200
        assert client.delete("/billing/scheduled-change",headers=headers).status_code == 200
        assert snapshot(owner_db,tenant[0]) == before
        with credits.metering(tenant[0],"restricted_test",actor_user_id=tenant[1]):
            with pytest.raises(credits.BudgetError) as error:
                credits.reserve(kind,vendor,"op",{"request":1},idempotency_key="before")
            assert error.value.reason == "DUPLICATE_REQUEST"
        assert snapshot(owner_db,tenant[0]) == before
    finally:
        with owner_db.cursor() as cur:cur.execute("DELETE FROM provider_cost_schedules WHERE provider=%s",(vendor,))


def test_cross_tenant_owner_cannot_use_another_tenants_trial(client,trial,plans,tenant,owner_db):
    provider,_=trial
    other=str(uuid.uuid4())
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Other synthetic tenant','US','USD')",(other,))
    try:
        forged={"Authorization":"Bearer "+create_access_token(other,tenant[1],email_verified=True)[0]}
        response=change(client,forged,plans[0][0])
        assert response.status_code in (403,404)
        assert provider.creates == 0
    finally:
        with owner_db.cursor() as cur:cur.execute("DELETE FROM companies WHERE tenant_id=%s",(other,))


def test_verified_first_payment_at_original_boundary_activates_once(trial,owner_db,tenant,send,monkeypatch):
    provider,_=trial
    live=provider.live
    cutoff=live["trial_end"]
    live["status"]="active"
    live["items"]["data"][0].update(current_period_start=cutoff,current_period_end=cutoff+30*86400)
    invoice={"id":"in_first_"+uuid.uuid4().hex,"subscription":live["id"],"customer":live["customer"],"status":"paid","paid":True,"amount_due":11000,"amount_paid":11000,"currency":"usd"}
    invoice["lines"]={"data":[{"period":{"start":cutoff,"end":cutoff+30*86400}}]}
    live["latest_invoice"]=invoice["id"]
    monkeypatch.setattr(stripe_api,"retrieve_invoice",lambda _:invoice)
    event="evt_first_"+uuid.uuid4().hex
    assert send("invoice.paid",invoice,event).status_code==200
    before=snapshot(owner_db,tenant[0])
    assert before[2][0]=="active"
    with closing(db.app_role_connection(*tenant)) as conn:
        paid=usage.get_plan(conn,tenant[0])
        assert paid["features"]["data_credits"]["limit"] > 0
        assert paid["status"]=="active"
    assert send("invoice.paid",invoice,event).json()["duplicate"] is True
    assert snapshot(owner_db,tenant[0])==before


def test_expired_trial_blocks_upgrade_downgrade_and_credit_spending(client,trial,plans,tenant,owner_db,monkeypatch):
    from types import SimpleNamespace
    provider,headers=trial
    cutoff=provider.live["trial_end"]
    monkeypatch.setattr(service,"time",SimpleNamespace(time=lambda:cutoff))
    before=snapshot(owner_db,tenant[0])
    for plan in (plans[0][0],plans[2][0]):
        assert change(client,headers,plan).status_code==409
    real_get_plan=usage.get_plan
    monkeypatch.setattr(usage,"get_plan",lambda conn,tid:real_get_plan(conn,tid,now=store._ts(cutoff)))
    expired=client.get("/billing/subscription",headers=headers)
    assert expired.status_code==200
    assert expired.json()["status"]=="expired" and expired.json()["hasAccess"] is False
    for kind in ("data","ai"):
        with pytest.raises(credits.BudgetError) as error:credits.ensure_available(tenant[0],kind)
        assert error.value.reason=="SUBSCRIPTION_INACTIVE"
    assert provider.creates==0
    assert snapshot(owner_db,tenant[0])==before


def test_schedule_preserves_current_financial_fields_without_mutating_input():
    provider=TrialProvider(str(uuid.uuid4()),"price_offline")
    sid=provider.create(provider.live["id"])["id"]
    phase=provider.schedule(sid)["phases"][0]
    phase.update(automatic_tax={"enabled":False},default_tax_rates=["txr_offline"],
                 discounts=[{"discount":"di_offline"}],invoice_settings={"days_until_due":7},
                 default_payment_method="pm_offline",application_fee_percent=2,
                 transfer_data={"destination":"acct_offline"})
    phase["items"][0].update(tax_rates=["txr_item"],discounts=[{"discount":"di_item"}])
    before=deepcopy(phase)
    saved=service._preserved_current_phase(phase,provider.live)
    assert phase==before
    for key in ("trial_end","automatic_tax","default_tax_rates","discounts","invoice_settings", "default_payment_method","application_fee_percent","transfer_data"):
        assert saved[key]==before[key]
    assert saved["items"][0]["price"]=="price_offline"
    assert saved["items"][0]["tax_rates"]==["txr_item"]


def test_schedule_with_additional_invoice_items_requires_review():
    provider=TrialProvider(str(uuid.uuid4()),"price_offline")
    sid=provider.create(provider.live["id"])["id"]
    phase=provider.schedule(sid)["phases"][0]
    phase["add_invoice_items"]=[{"price":"price_one_time","quantity":1}]
    with pytest.raises(service.BillingError) as error:service._preserved_current_phase(phase,provider.live)
    assert error.value.code=="plan_transition_unclassified"


@pytest.mark.parametrize('invoice_state',['draft','open','missing','old_zero_trial','other_subscription'])
def test_active_provider_label_without_current_paid_invoice_cannot_finish_trial(trial,tenant,owner_db,send,monkeypatch,invoice_state):
    provider,_=trial;live=provider.live;cutoff=live['trial_end']
    live['status']='active'
    live['items']['data'][0].update(current_period_start=cutoff,current_period_end=cutoff+30*86400)
    invoice={'id':'in_pending_'+uuid.uuid4().hex,'subscription':live['id'],'customer':live['customer'],
             'status':'paid' if invoice_state in ('old_zero_trial','other_subscription') else invoice_state,
             'amount_paid':0,'lines':{'data':[{'period':{'start':cutoff,'end':cutoff+30*86400}}]}}
    if invoice_state=='old_zero_trial':invoice['lines']['data'][0]['period']={'start':cutoff-14*86400,'end':cutoff}
    if invoice_state=='other_subscription':invoice['subscription']='sub_unrelated'
    live['latest_invoice']=None if invoice_state=='missing' else invoice['id']
    monkeypatch.setattr(stripe_api,'retrieve_invoice',lambda _:deepcopy(invoice))
    before=snapshot(owner_db,tenant[0])
    event='evt_pending_'+uuid.uuid4().hex
    assert send('customer.subscription.updated',{'id':live['id']},event).status_code==500
    assert snapshot(owner_db,tenant[0])==before
    with closing(db.app_role_connection(*tenant)) as conn:
        assert usage.get_plan(conn,tenant[0],now=store._ts(cutoff))['status']=='expired'
    # Provider reconciliation may complete later. Replaying the same signed
    # event then uses fresh invoice truth and issues exactly one paid period.
    invoice.update(status='paid',subscription=live['id'])
    invoice['lines']['data'][0]['period']={'start':cutoff,'end':cutoff+30*86400}
    live['latest_invoice']=invoice['id']
    assert send('customer.subscription.updated',{'id':live['id']},event).status_code==200
    assert store.current_subscription(owner_db,tenant[0])['status']=='active'
    assert send('customer.subscription.updated',{'id':live['id']},event).json()['duplicate'] is True
