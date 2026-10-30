"""Restricted-role module selection from paid activation correlation.

Provider evidence is a labeled synthetic SQL fixture here. Actual Stripe
payment and signed activation are tested separately in the browser/provider run.
"""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
import psycopg2
from src.ai.billing import admin,custom_offers,store
from src.ai.core import usage
from tests.billing.test_custom_quote_lifecycle_db import quote_actors,_conn,_submit_and_price

@pytest.mark.parametrize('selected',[[],['market_intelligence'],['market_intelligence','demand_prediction','competitor_management']])
def test_paid_custom_modules_follow_only_correlated_immutable_revision(owner_db,billing_connections,quote_actors,selected):
    actors=quote_actors;tid,uid=actors['tenant_a'],actors['user_a']
    operator=_conn(billing_connections,actors);customer=_conn(billing_connections,actors,'tenant_a')
    try:
        quote=custom_offers.create_draft(operator,tenant_id=tid,customer_user_id=uid,idempotency_key=str(uuid4()),configuration={'enabledFeatures':selected,**({'refreshFrequency':'daily'} if 'competitor_management' in selected else {})},feature_quantities={'tracked_products':1,**({'tracked_competitors':1} if 'competitor_management' in selected else {})},commercial_terms={},economic_inputs={},fx_evidence={})
        operator.commit();_submit_and_price(operator,quote)
        custom_offers.transition(operator,'approve',tenant_id=None,quote_id=str(quote['quote_id']),expected_revision=1,idempotency_key=str(uuid4()),approval_reference='SYNTHETIC_TEST_ONLY');operator.commit()
        custom_offers.transition(customer,'accept',tenant_id=tid,quote_id=str(quote['quote_id']),expected_revision=1,idempotency_key=str(uuid4()));customer.commit()
        attempt=custom_offers.prepare_checkout_attempt(customer,tenant_id=tid,quote_id=str(quote['quote_id']),idempotency_key=str(uuid4()));customer.commit()
        with owner_db.cursor() as cur:
            cur.execute('SELECT revision_id FROM billing_custom_quote_revisions WHERE quote_id=%s',(str(quote['quote_id']),));revision=str(cur.fetchone()[0])
        reference=f"custom-quote:{quote['quote_id']}:{revision}"
        admin.set_custom_contract(owner_db,tenant_id=tid,contract_ref=reference,approved_by='SYNTHETIC_TEST_ONLY',reason='native module fixture',limits=admin.closed_quote_limits({'tracked_products':1}),included_features=selected)
        now=datetime.now(timezone.utc);sid='sub_native_'+uuid4().hex;cid='cus_native_'+uuid4().hex
        store.save_customer(owner_db,tid,cid)
        provider={'id':sid,'customer':cid,'status':'active','items':{'data':[{'price':{'id':'price_synthetic'},'current_period_start':int(now.timestamp()),'current_period_end':int((now+timedelta(days=30)).timestamp())}]}}
        store.apply_subscription(owner_db,tid,provider,'custom','monthly',now)
        premium={usage.MARKET_INTELLIGENCE,usage.DEMAND_PREDICTION,usage.COMPETITOR_MANAGEMENT}
        before=usage.get_plan(customer,tid);assert not premium.intersection(before['entitlements'])  # no verified proof
        customer.commit()
        with owner_db.cursor() as cur:
            cur.execute("INSERT INTO billing_custom_contract_activations(tenant_id,quote_id,revision_id,attempt_id,stripe_subscription_id,stripe_invoice_id,provider_event_id,invoice_paid_at) VALUES(%s,%s,%s,%s,%s,%s,%s,now())",(tid,str(quote['quote_id']),revision,str(attempt['attempt_id']),sid,'in_native_'+uuid4().hex,'evt_native_'+uuid4().hex))
        actual=usage.get_plan(customer,tid)
        assert set(actual['entitlements']) == (set(before['entitlements']) - premium) | set(selected)
        assert set(actual['entitlements'])-premium==set(before['entitlements'])-premium  # existing core rights preserved
        with customer.cursor() as cur:
            cur.execute("SELECT has_table_privilege(current_user,'billing_custom_contract_activations','SELECT')");assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(current_user,'keel_paid_custom_catalog_snapshot(uuid,jsonb)','EXECUTE')");assert cur.fetchone()[0] is False
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):cur.execute('SELECT keel_paid_custom_catalog_snapshot(%s,%s::jsonb)',(actors['tenant_b'],'{}'))
        customer.rollback()
        with owner_db.cursor() as cur:cur.execute("UPDATE tenant_plan_assignments SET catalog_snapshot='{}'::jsonb WHERE tenant_id=%s",(tid,))
        assert set(usage.get_plan(customer,tid)['entitlements'])==set(actual['entitlements'])
        assert set(usage.get_plan(owner_db,tid)['entitlements'])==set(actual['entitlements'])
    finally:operator.close();customer.close()
