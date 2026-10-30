-- Checkout setup is separate from verified-payment reconciliation.
-- Proven against a fresh disposable cluster before adding this migration.
-- No grants on payments, subscriptions, credit ledgers, or paid activation.
DO $$ DECLARE r TEXT; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_billing_setup','ceopro_trial_issuer'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION',r);
  END IF;
  IF EXISTS(SELECT FROM pg_roles WHERE rolname=r AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication))
    OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=r))
    OR EXISTS(SELECT FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=r))
    OR EXISTS(SELECT FROM pg_namespace WHERE nspowner=(SELECT oid FROM pg_roles WHERE rolname=r))
    OR EXISTS(SELECT FROM pg_database WHERE datdba=(SELECT oid FROM pg_roles WHERE rolname=r)) THEN
   RAISE EXCEPTION 'Unexpected billing setup role privileges/ownership: %; operator review required',r;
  END IF;
 END LOOP;
END $$;
-- No password in migration history. Login password is provisioned separately.
ALTER ROLE ceopro_billing_setup LOGIN;
ALTER ROLE ceopro_trial_issuer NOLOGIN;
GRANT USAGE ON SCHEMA public TO ceopro_billing_setup;
GRANT SELECT (tenant_id,timezone,deleted_at) ON public.companies TO ceopro_billing_setup;
GRANT SELECT ON public.tenant_users TO ceopro_billing_setup;
GRANT SELECT ON public.billing_checkout_attempts,public.billing_customers TO ceopro_billing_setup;
GRANT INSERT (attempt_id,tenant_id,request_key,plan_key,period_code),UPDATE(provider_params,stripe_session_id,state,updated_at) ON public.billing_checkout_attempts TO ceopro_billing_setup;
GRANT INSERT(tenant_id,stripe_customer_id),UPDATE(stripe_customer_id) ON public.billing_customers TO ceopro_billing_setup;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(UUID,UUID) TO ceopro_billing_setup;
DO $$ DECLARE t TEXT; g TEXT:=$guard$tenant_id=public.get_current_tenant() AND EXISTS(SELECT FROM public.tenant_users m WHERE m.tenant_id=public.get_current_tenant() AND m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid AND m.role_key IN ('owner','admin','accountant') AND m.removed_at IS NULL AND m.platform_suspended_at IS NULL)$guard$; BEGIN
 FOREACH t IN ARRAY ARRAY['billing_checkout_attempts','billing_customers'] LOOP
  EXECUTE format('CREATE POLICY billing_setup_scope ON public.%I TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',t,g,g);
  -- Public tenant policies are permissive; this additional policy is restrictive.
  EXECUTE format('CREATE POLICY billing_setup_boundary ON public.%I AS RESTRICTIVE TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',t,g,g);
 END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO ceopro_trial_issuer;
GRANT SELECT ON public.tenant_users,public.usage_plans,public.billing_trials,public.tenant_plan_assignments,public.billing_subscriptions TO ceopro_trial_issuer;
GRANT INSERT(tenant_id,plan_key,started_at,ends_at,started_by_user_id) ON public.billing_trials TO ceopro_trial_issuer;
GRANT INSERT(tenant_id,plan_key,status,current_period_start,current_period_end,source) ON public.tenant_plan_assignments TO ceopro_trial_issuer;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(UUID,UUID) TO ceopro_trial_issuer;
CREATE POLICY billing_setup_trial_person ON public.billing_trials FOR SELECT TO ceopro_trial_issuer
 USING (tenant_id=public.get_current_tenant() OR started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY billing_setup_trial_insert ON public.billing_trials FOR INSERT TO ceopro_trial_issuer WITH CHECK(tenant_id=public.get_current_tenant() AND started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY billing_setup_trial_subscription_read ON public.billing_subscriptions FOR SELECT TO ceopro_trial_issuer USING(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_setup_trial(p_plan TEXT,p_start BOOLEAN DEFAULT FALSE) RETURNS JSONB
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 t UUID:=public.get_current_tenant(); u UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 d INTEGER; s BOOLEAN; a BOOLEAN; r TEXT; n TIMESTAMPTZ:=clock_timestamp(); e TIMESTAMPTZ;
BEGIN
 IF public.keel_active_principal(u,t) IS DISTINCT FROM TRUE THEN
  RAISE EXCEPTION 'active principal required' USING ERRCODE='42501'; END IF;
 IF p_start AND NOT EXISTS (SELECT FROM public.tenant_users WHERE tenant_id=t AND user_id=u
  AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL) THEN
  RAISE EXCEPTION 'billing role required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT trial_days,self_serve,is_active INTO d,s,a FROM public.usage_plans WHERE plan_key=p_plan;
 IF NOT FOUND OR NOT a OR NOT s OR d<=0 THEN r:='plan_has_no_trial';
 ELSIF EXISTS(SELECT FROM public.billing_trials WHERE tenant_id=t) THEN r:='trial_already_used';
 ELSIF EXISTS(SELECT FROM public.billing_trials WHERE started_by_user_id=u) THEN r:='trial_already_used_by_person';
 ELSIF EXISTS(SELECT FROM public.tenant_plan_assignments WHERE tenant_id=t) THEN r:='plan_already_assigned';
 ELSIF EXISTS(SELECT FROM public.billing_subscriptions WHERE tenant_id=t) THEN r:='subscription_exists'; END IF;
 IF r IS NOT NULL OR NOT p_start THEN RETURN jsonb_build_object('reason',r); END IF;
 e:=n+make_interval(days=>d);
 INSERT INTO public.billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(t,p_plan,n,e,u);
 INSERT INTO public.tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source)
 VALUES(t,p_plan,'trialing',n::date,e::date,'trial');
 RETURN jsonb_build_object('reason',NULL,'plan_key',p_plan,'started_at',n,'ends_at',e);
END $$;
ALTER FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) TO ceopro_billing_setup;

-- Only unpaid promotion coordination in the disposable proof database.
GRANT SELECT ON billing_promotions,billing_promotion_plans,billing_promotion_redemptions,billing_promotion_events,usage_plans,billing_plan_prices TO ceopro_billing_setup;
GRANT SELECT(tenant_id) ON tenant_custom_contracts TO ceopro_billing_setup;
CREATE POLICY billing_setup_contract_read ON tenant_custom_contracts FOR SELECT TO ceopro_billing_setup USING(tenant_id=public.get_current_tenant());
GRANT UPDATE(updated_at) ON billing_promotions TO ceopro_billing_setup;
CREATE POLICY billing_setup_active_promotions ON billing_promotions TO ceopro_billing_setup USING(status='active') WITH CHECK(status='active');
CREATE POLICY billing_setup_plan_promotions ON billing_promotion_plans FOR SELECT TO ceopro_billing_setup USING(EXISTS(SELECT FROM billing_promotions p WHERE p.promotion_id=billing_promotion_plans.promotion_id AND p.status='active'));
GRANT INSERT(tenant_id,promotion_id,state,request_key,request_fingerprint,plan_key,period_code) ON billing_promotion_redemptions TO ceopro_billing_setup;
GRANT UPDATE(state,stripe_checkout_session_id,checkout_request_started_at,stripe_subscription_id,stripe_initial_invoice_id,settled_at,last_error_code,updated_at) ON billing_promotion_redemptions TO ceopro_billing_setup;
GRANT INSERT(tenant_id,redemption_id,actor_user_id,event_type,old_state,new_state,stripe_event_id,reason_code) ON billing_promotion_events TO ceopro_billing_setup;
GRANT EXECUTE ON FUNCTION billing_promotion_capacity_reason(UUID) TO ceopro_billing_setup;
DO $$ DECLARE t TEXT; g TEXT:=$guard$tenant_id=public.get_current_tenant() AND EXISTS(SELECT FROM public.tenant_users m WHERE m.tenant_id=public.get_current_tenant() AND m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid AND m.role_key IN ('owner','admin','accountant') AND m.removed_at IS NULL AND m.platform_suspended_at IS NULL)$guard$; BEGIN
 FOREACH t IN ARRAY ARRAY['billing_promotion_redemptions','billing_promotion_events'] LOOP
 EXECUTE format('CREATE POLICY billing_setup_scope ON public.%I TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',t,g,g);
 EXECUTE format('CREATE POLICY billing_setup_boundary ON public.%I AS RESTRICTIVE TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',t,g,g); END LOOP;
END $$;
CREATE POLICY billing_setup_unpaid ON billing_promotion_redemptions AS RESTRICTIVE TO ceopro_billing_setup USING(TRUE)
 WITH CHECK(state IN ('pending','rejected','reconciliation_required') AND settled_at IS NULL AND stripe_subscription_id IS NULL AND stripe_initial_invoice_id IS NULL);

-- Fail closed on a legacy schema with PUBLIC CREATE, rather than changing
-- shared schema/database permissions or silently inheriting DDL privileges.
DO $$ DECLARE r TEXT; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_billing_setup','ceopro_trial_issuer'] LOOP
  IF has_schema_privilege(r,'public','CREATE') OR has_database_privilege(r,current_database(),'CREATE') THEN
   RAISE EXCEPTION 'Billing setup role inherits database/schema CREATE: %; operator review required',r;
  END IF;
 END LOOP;
END $$;
