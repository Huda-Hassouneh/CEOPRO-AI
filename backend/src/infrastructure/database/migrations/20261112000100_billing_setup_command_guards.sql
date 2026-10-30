-- Forward-only hardening of the new setup identity; no broader grants.
-- The earlier migration was already applied during disposable verification.
CREATE OR REPLACE FUNCTION public.billing_setup_trial(p_plan TEXT,p_start BOOLEAN DEFAULT FALSE) RETURNS JSONB
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 t UUID:=public.get_current_tenant(); u UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 d INTEGER; s BOOLEAN; a BOOLEAN; r TEXT; n TIMESTAMPTZ:=clock_timestamp(); e TIMESTAMPTZ;
BEGIN
 IF p_start IS NULL THEN RAISE EXCEPTION 'Explicit trial operation required' USING ERRCODE='22023'; END IF;
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

DO $$ DECLARE t TEXT; p TEXT; g TEXT:=$guard$tenant_id=public.get_current_tenant() AND public.keel_active_principal(nullif(current_setting('app.current_user_id',true),'')::uuid,public.get_current_tenant()) AND EXISTS(SELECT FROM public.tenant_users m WHERE m.tenant_id=public.get_current_tenant() AND m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid AND m.role_key IN ('owner','admin','accountant') AND m.removed_at IS NULL AND m.platform_suspended_at IS NULL)$guard$; BEGIN
 FOREACH t IN ARRAY ARRAY['billing_checkout_attempts','billing_customers','billing_promotion_redemptions','billing_promotion_events'] LOOP
  FOREACH p IN ARRAY ARRAY['billing_setup_scope','billing_setup_boundary'] LOOP
   EXECUTE format('ALTER POLICY %I ON public.%I USING(%s) WITH CHECK(%s)',p,t,g,g);
  END LOOP;
 END LOOP;
END $$;
-- Setup coordination cannot impersonate evidence from a signed Stripe event.
CREATE POLICY billing_setup_event_evidence ON public.billing_promotion_events AS RESTRICTIVE FOR INSERT TO ceopro_billing_setup
 WITH CHECK(stripe_event_id IS NULL AND (actor_user_id IS NULL OR actor_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 AND (new_state IS NULL OR new_state IN ('pending','rejected','reconciliation_required')));
