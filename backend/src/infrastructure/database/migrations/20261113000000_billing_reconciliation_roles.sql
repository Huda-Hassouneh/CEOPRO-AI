-- Trusted payment reconciliation and usage accounting are separate capabilities.
-- No runtime role owns schemas/tables, bypasses RLS, inherits roles or has DDL.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_billing_webhook','ceopro_credit_accounting','ceopro_billing_lookup','ceopro_schedule_writer'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION',r);
  END IF;
  IF EXISTS(SELECT FROM pg_roles WHERE rolname=r AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication))
   OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=r))
   OR EXISTS(SELECT FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=r))
   OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname=r))
   OR EXISTS(SELECT FROM pg_database WHERE datdba=(SELECT oid FROM pg_roles WHERE rolname=r)) THEN
   RAISE EXCEPTION 'Unexpected trusted billing role privileges/ownership: %; operator review required',r;
  END IF;
 END LOOP;
END $$;
ALTER ROLE ceopro_billing_webhook LOGIN;
ALTER ROLE ceopro_credit_accounting LOGIN;
GRANT USAGE ON SCHEMA public TO ceopro_billing_webhook,ceopro_credit_accounting,ceopro_billing_lookup,ceopro_schedule_writer;
-- Receipt access is limited to the signature-verified event passed by the router.
GRANT SELECT,INSERT ON public.billing_webhook_events TO ceopro_billing_webhook;
GRANT UPDATE(processed_at,error,tenant_id) ON public.billing_webhook_events TO ceopro_billing_webhook;
CREATE POLICY webhook_receipt_scope ON public.billing_webhook_events TO ceopro_billing_webhook
 USING(stripe_event_id=current_setting('app.billing_event_id',true))
 WITH CHECK(stripe_event_id=current_setting('app.billing_event_id',true));
CREATE POLICY webhook_receipt_boundary ON public.billing_webhook_events AS RESTRICTIVE TO ceopro_billing_webhook
 USING(stripe_event_id=current_setting('app.billing_event_id',true))
 WITH CHECK(stripe_event_id=current_setting('app.billing_event_id',true));
CREATE FUNCTION public.billing_webhook_tenant() RETURNS uuid
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT tenant_id FROM public.billing_webhook_events
 WHERE stripe_event_id=current_setting('app.billing_event_id',true)
 AND tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid
 AND processed_at IS NULL AND error IS NULL
 AND (event_type IN ('checkout.session.completed','checkout.session.expired','invoice.paid','invoice.payment_succeeded','invoice.payment_failed')
 OR event_type IN ('customer.subscription.created','customer.subscription.updated','customer.subscription.deleted','customer.subscription.paused',
 'customer.subscription.resumed','customer.subscription.trial_will_end','customer.subscription.pending_update_applied','customer.subscription.pending_update_expired',
 'subscription_schedule.released','subscription_schedule.completed','subscription_schedule.canceled','subscription_schedule.aborted'))
$$;
REVOKE ALL ON FUNCTION public.billing_webhook_tenant() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_webhook_tenant() TO ceopro_billing_webhook;
-- Exact reference lookups and aggregate-only accounting do not expose tenant rows.
GRANT SELECT ON public.billing_customers,public.billing_subscriptions,public.billing_promotion_redemptions,public.usage_ledger TO ceopro_billing_lookup;
CREATE POLICY billing_lookup_read ON public.billing_customers FOR SELECT TO ceopro_billing_lookup USING(true);
CREATE POLICY billing_lookup_read ON public.billing_subscriptions FOR SELECT TO ceopro_billing_lookup USING(true);
CREATE POLICY billing_lookup_read ON public.billing_promotion_redemptions FOR SELECT TO ceopro_billing_lookup USING(true);
CREATE POLICY billing_lookup_read ON public.usage_ledger FOR SELECT TO ceopro_billing_lookup USING(true);
CREATE FUNCTION public.billing_provider_tenant(p_kind text,p_reference text) RETURNS uuid
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF session_user='ceopro_billing_webhook' THEN
  IF p_kind='customer' THEN RETURN (SELECT tenant_id FROM public.billing_customers WHERE stripe_customer_id=p_reference);
  ELSIF p_kind='subscription' THEN RETURN (SELECT tenant_id FROM public.billing_subscriptions WHERE stripe_subscription_id=p_reference);
  ELSIF p_kind='promotion' THEN RETURN (SELECT tenant_id FROM public.billing_promotion_redemptions WHERE redemption_id::text=p_reference);
  END IF;
 END IF;
 RAISE EXCEPTION 'Unsupported provider routing capability' USING ERRCODE='42501';
END $$;
ALTER FUNCTION public.billing_provider_tenant(text,text) OWNER TO ceopro_billing_lookup;
REVOKE ALL ON FUNCTION public.billing_provider_tenant(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_provider_tenant(text,text) TO ceopro_billing_webhook;
CREATE FUNCTION public.billing_provider_month_spend(p_provider text,p_model text,p_since timestamptz) RETURNS numeric
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT coalesce(sum(coalesce(actual_cost_usd,estimated_cost_usd)),0) FROM public.usage_ledger
 WHERE (p_provider IS NULL OR provider=p_provider) AND (p_model IS NULL OR provider_operation=p_model)
 AND created_at>=p_since AND status<>'released'
$$;
ALTER FUNCTION public.billing_provider_month_spend(text,text,timestamptz) OWNER TO ceopro_billing_lookup;
REVOKE ALL ON FUNCTION public.billing_provider_month_spend(text,text,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_provider_month_spend(text,text,timestamptz) TO ceopro_credit_accounting;
CREATE FUNCTION public.billing_expired_credit_tenants(p_seconds integer) RETURNS SETOF uuid
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT DISTINCT tenant_id FROM public.usage_ledger WHERE status='reserved'
 AND p_seconds>0 AND created_at<now()-make_interval(secs=>p_seconds)
$$;
ALTER FUNCTION public.billing_expired_credit_tenants(integer) OWNER TO ceopro_billing_lookup;
REVOKE ALL ON FUNCTION public.billing_expired_credit_tenants(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_expired_credit_tenants(integer) TO ceopro_credit_accounting;
GRANT SELECT ON public.billing_customers TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,stripe_customer_id) ON public.billing_customers TO ceopro_billing_webhook;
GRANT UPDATE(stripe_customer_id) ON public.billing_customers TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_customers TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_customers AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_subscriptions TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,plan_key,period_code,status,current_period_start,current_period_end,trial_end,cancel_at_period_end,cancelled_at,last_event_at) ON public.billing_subscriptions TO ceopro_billing_webhook;
GRANT UPDATE(stripe_customer_id,stripe_price_id,plan_key,period_code,status,current_period_start,current_period_end,trial_end,cancel_at_period_end,cancelled_at,scheduled_plan_key,scheduled_period_code,last_event_at,updated_at) ON public.billing_subscriptions TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_subscriptions TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_subscriptions AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_payments TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,stripe_invoice_id,stripe_subscription_id,amount,currency,status,paid_at,failure_reason,hosted_invoice_url,invoice_pdf_url,period_start,period_end) ON public.billing_payments TO ceopro_billing_webhook;
GRANT UPDATE(amount,status,paid_at,failure_reason,hosted_invoice_url,invoice_pdf_url) ON public.billing_payments TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_payments TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_payments AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.tenant_plan_assignments TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,plan_key,status,current_period_start,current_period_end,period_code,source,updated_at) ON public.tenant_plan_assignments TO ceopro_billing_webhook;
GRANT UPDATE(plan_key,status,current_period_start,current_period_end,period_code,source,updated_at) ON public.tenant_plan_assignments TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.tenant_plan_assignments TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.tenant_plan_assignments AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_custom_quotes TO ceopro_billing_webhook;
GRANT UPDATE(updated_at) ON public.billing_custom_quotes TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_custom_quotes TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_custom_quotes AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_custom_quote_revisions TO ceopro_billing_webhook;
GRANT UPDATE(created_at) ON public.billing_custom_quote_revisions TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_custom_quote_revisions TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_custom_quote_revisions AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_custom_quote_checkout_attempts TO ceopro_billing_webhook;
GRANT UPDATE(state,stripe_subscription_id,stripe_invoice_id,provider_event_id,provider_outcome,updated_at,last_error_code,stripe_checkout_session_id) ON public.billing_custom_quote_checkout_attempts TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_custom_quote_checkout_attempts TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_custom_quote_checkout_attempts AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_custom_contract_activations TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,quote_id,revision_id,attempt_id,stripe_subscription_id,stripe_invoice_id,provider_event_id,invoice_paid_at) ON public.billing_custom_contract_activations TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_custom_contract_activations TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_custom_contract_activations AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_custom_quote_events TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,quote_id,revision_id,action,actor_user_id,idempotency_key,evidence) ON public.billing_custom_quote_events TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_custom_quote_events TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_custom_quote_events AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.tenant_custom_contracts TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,contract_ref,monthly_price,currency,trial_days,data_sources,included_features,refresh_frequency,support_level,approved_by,reason) ON public.tenant_custom_contracts TO ceopro_billing_webhook;
GRANT UPDATE(contract_ref,monthly_price,currency,trial_days,data_sources,included_features,refresh_frequency,support_level,approved_by,reason,approved_at) ON public.tenant_custom_contracts TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.tenant_custom_contracts TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.tenant_custom_contracts AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.tenant_entitlement_overrides TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,feature_code,limit_value,contract_ref,approved_by,reason) ON public.tenant_entitlement_overrides TO ceopro_billing_webhook;
GRANT UPDATE(limit_value,contract_ref,approved_by,reason,approved_at) ON public.tenant_entitlement_overrides TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.tenant_entitlement_overrides TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.tenant_entitlement_overrides AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.entitlement_audit_log TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,action,subject,old_value,new_value,contract_ref,approved_by,reason) ON public.entitlement_audit_log TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.entitlement_audit_log TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.entitlement_audit_log AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_promotion_redemptions TO ceopro_billing_webhook;
GRANT UPDATE(state,stripe_checkout_session_id,stripe_subscription_id,stripe_initial_invoice_id,settled_at,last_error_code,updated_at) ON public.billing_promotion_redemptions TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_promotion_redemptions TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_promotion_redemptions AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.billing_promotion_events TO ceopro_billing_webhook;
GRANT INSERT(tenant_id,redemption_id,actor_user_id,event_type,old_state,new_state,stripe_event_id,reason_code) ON public.billing_promotion_events TO ceopro_billing_webhook;
CREATE POLICY webhook_scope ON public.billing_promotion_events TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
CREATE POLICY webhook_boundary ON public.billing_promotion_events AS RESTRICTIVE TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant());
-- Payment rows must also match the invoice in the verified receipt.
CREATE POLICY webhook_invoice_evidence ON public.billing_payments AS RESTRICTIVE TO ceopro_billing_webhook
 USING(true) WITH CHECK(EXISTS(SELECT FROM public.billing_webhook_events e
 WHERE e.stripe_event_id=current_setting('app.billing_event_id',true)
 AND e.event_type IN ('invoice.paid','invoice.payment_succeeded','invoice.payment_failed')
 AND e.payload#>>'{data,object,id}'=billing_payments.stripe_invoice_id));
GRANT SELECT(tenant_id,timezone,deleted_at) ON public.companies TO ceopro_billing_webhook,ceopro_credit_accounting;
CREATE POLICY webhook_company ON public.companies FOR SELECT TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant());
GRANT SELECT ON public.usage_plans,public.usage_features,public.usage_plan_limits,public.usage_plan_entitlements,public.billing_plan_prices TO ceopro_billing_webhook,ceopro_credit_accounting;
GRANT SELECT ON public.tenant_plan_assignments TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.tenant_plan_assignments FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_trials TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.billing_trials FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_subscriptions TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.billing_subscriptions FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.tenant_custom_contracts TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.tenant_custom_contracts FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.tenant_entitlement_overrides TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.tenant_entitlement_overrides FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.tenant_users TO ceopro_credit_accounting;
CREATE POLICY accounting_read ON public.tenant_users FOR SELECT TO ceopro_credit_accounting USING(tenant_id=public.get_current_tenant());
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid,uuid) TO ceopro_credit_accounting;
GRANT SELECT ON public.billing_cost_policy TO ceopro_credit_accounting;
CREATE POLICY accounting_policy_read ON public.billing_cost_policy FOR SELECT TO ceopro_credit_accounting USING(true);
GRANT SELECT ON public.provider_cost_schedules TO ceopro_credit_accounting;
CREATE POLICY accounting_policy_read ON public.provider_cost_schedules FOR SELECT TO ceopro_credit_accounting USING(true);
GRANT SELECT ON public.provider_spend_controls TO ceopro_credit_accounting;
CREATE POLICY accounting_policy_read ON public.provider_spend_controls FOR SELECT TO ceopro_credit_accounting USING(true);
GRANT SELECT,INSERT(ledger_id,tenant_id,budget_kind,operation_id,operation_type,usage_class,actor_user_id,provider,provider_operation,idempotency_key,period_start,plan_key,plan_status,subscription_id,estimated_units,estimated_cost_usd,reserved_credits,status) ON public.usage_ledger TO ceopro_credit_accounting;
GRANT UPDATE(status,measured_units,actual_cost_usd,consumed_credits,error_code,provider_request_id,settled_at,reconciled_at) ON public.usage_ledger TO ceopro_credit_accounting;
CREATE POLICY accounting_scope ON public.usage_ledger TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY accounting_boundary ON public.usage_ledger AS RESTRICTIVE TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
GRANT SELECT,INSERT(tenant_id,budget_kind,period_start,period_end,reserved_credits,consumed_credits,consumed_cost_usd) ON public.tenant_credit_balances TO ceopro_credit_accounting;
GRANT UPDATE(reserved_credits,consumed_credits,consumed_cost_usd,updated_at) ON public.tenant_credit_balances TO ceopro_credit_accounting;
CREATE POLICY accounting_scope ON public.tenant_credit_balances TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY accounting_boundary ON public.tenant_credit_balances AS RESTRICTIVE TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
GRANT SELECT,INSERT(ledger_id,tenant_id,budget_kind,period_start,credits_delta,cost_delta_usd,kind,reference,reason,actor) ON public.usage_ledger_adjustments TO ceopro_credit_accounting;
CREATE POLICY accounting_scope ON public.usage_ledger_adjustments TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY accounting_boundary ON public.usage_ledger_adjustments AS RESTRICTIVE TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
GRANT SELECT,INSERT(tenant_id,feature_code,idempotency_key,period_start,actor_user_id,request_fingerprint) ON public.metered_request_keys TO ceopro_credit_accounting;
GRANT UPDATE(replayed) ON public.metered_request_keys TO ceopro_credit_accounting;
CREATE POLICY accounting_scope ON public.metered_request_keys TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY accounting_boundary ON public.metered_request_keys AS RESTRICTIVE TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
GRANT SELECT,INSERT(tenant_id,feature_code,period_start,used) ON public.tenant_usage_counters TO ceopro_credit_accounting;
GRANT UPDATE(used,updated_at) ON public.tenant_usage_counters TO ceopro_credit_accounting;
CREATE POLICY accounting_scope ON public.tenant_usage_counters TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY accounting_boundary ON public.tenant_usage_counters AS RESTRICTIVE TO ceopro_credit_accounting USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
GRANT DELETE ON public.metered_request_keys TO ceopro_credit_accounting;
CREATE POLICY accounting_adjustment_evidence ON public.usage_ledger_adjustments AS RESTRICTIVE FOR INSERT TO ceopro_credit_accounting
 WITH CHECK(kind='reconciliation' AND ledger_id IS NOT NULL AND EXISTS(SELECT FROM public.usage_ledger l
 WHERE l.ledger_id=usage_ledger_adjustments.ledger_id AND l.tenant_id=usage_ledger_adjustments.tenant_id));
-- Schedule metadata cannot change current plan, payment status or entitlements.
GRANT SELECT ON public.tenant_users,public.billing_subscriptions TO ceopro_schedule_writer;
GRANT UPDATE(scheduled_plan_key,scheduled_period_code,updated_at) ON public.billing_subscriptions TO ceopro_schedule_writer;
CREATE POLICY schedule_read ON public.billing_subscriptions FOR SELECT TO ceopro_schedule_writer USING(tenant_id=public.get_current_tenant());
CREATE POLICY schedule_write ON public.billing_subscriptions FOR UPDATE TO ceopro_schedule_writer USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_setup_schedule(p_subscription text,p_plan text,p_period text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant(); u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF public.keel_active_principal(u,t) IS DISTINCT FROM TRUE OR NOT EXISTS(SELECT FROM public.tenant_users
 WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL) THEN
  RAISE EXCEPTION 'Active billing principal required' USING ERRCODE='42501'; END IF;
 IF (p_plan IS NULL) <> (p_period IS NULL) OR (p_period IS NOT NULL AND p_period NOT IN ('monthly','three-months','six-months','yearly')) THEN
  RAISE EXCEPTION 'Invalid schedule metadata' USING ERRCODE='22023'; END IF;
 UPDATE public.billing_subscriptions SET scheduled_plan_key=p_plan,scheduled_period_code=p_period,updated_at=now()
 WHERE tenant_id=t AND stripe_subscription_id=p_subscription;
END $$;
ALTER FUNCTION public.billing_setup_schedule(text,text,text) OWNER TO ceopro_schedule_writer;
REVOKE ALL ON FUNCTION public.billing_setup_schedule(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_setup_schedule(text,text,text) TO ceopro_billing_setup;

DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_billing_webhook','ceopro_credit_accounting','ceopro_billing_lookup','ceopro_schedule_writer'] LOOP
  IF has_schema_privilege(r,'public','CREATE') OR has_database_privilege(r,current_database(),'CREATE') THEN
   RAISE EXCEPTION 'Trusted billing role inherits DDL: %; operator review required',r;
  END IF;
 END LOOP;
END $$;
