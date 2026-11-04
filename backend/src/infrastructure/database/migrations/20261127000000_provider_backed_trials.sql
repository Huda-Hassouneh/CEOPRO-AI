-- New trials are provider-confirmed. Historical billing_trials/assignments are untouched.
CREATE TABLE public.billing_trial_checkouts (
 attempt_id UUID PRIMARY KEY REFERENCES public.billing_checkout_attempts(attempt_id) ON DELETE CASCADE,
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 started_by_user_id UUID NOT NULL REFERENCES public.users(user_id),
 plan_key VARCHAR(50) NOT NULL REFERENCES public.usage_plans(plan_key),
 period_code VARCHAR(50) NOT NULL,
 provider_price_id TEXT NOT NULL,
 trial_duration_days INTEGER NOT NULL CHECK(trial_duration_days > 0),
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','activated','released')),
 provider TEXT, provider_subscription_id TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), activated_at TIMESTAMPTZ,
 CHECK((state='activated')=(provider IS NOT NULL AND provider_subscription_id IS NOT NULL AND activated_at IS NOT NULL))
);
CREATE UNIQUE INDEX billing_trial_checkout_person_pending ON public.billing_trial_checkouts(started_by_user_id) WHERE state='pending';
CREATE UNIQUE INDEX billing_trial_checkout_tenant_pending ON public.billing_trial_checkouts(tenant_id) WHERE state='pending';
CREATE UNIQUE INDEX billing_trial_checkout_subscription ON public.billing_trial_checkouts(provider,provider_subscription_id) WHERE provider_subscription_id IS NOT NULL;
ALTER TABLE public.billing_trial_checkouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_trial_checkouts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_trial_checkouts FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_trial_checkouts TO ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_trial_issuer;
GRANT SELECT ON public.billing_trials TO ceopro_billing_webhook;
CREATE POLICY trial_confirmation_webhook_read ON public.billing_trials FOR SELECT TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant());
CREATE POLICY trial_confirmation_webhook_boundary ON public.billing_trials AS RESTRICTIVE FOR SELECT TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant());
GRANT INSERT,UPDATE ON public.billing_trial_checkouts TO ceopro_trial_issuer;
REVOKE INSERT ON public.tenant_plan_assignments FROM ceopro_trial_issuer;
REVOKE INSERT(tenant_id,plan_key,status,current_period_start,current_period_end,source) ON public.tenant_plan_assignments FROM ceopro_trial_issuer;
GRANT SELECT ON public.billing_plan_prices TO ceopro_trial_issuer;
GRANT UPDATE(state,updated_at) ON public.billing_checkout_attempts TO ceopro_trial_issuer;
CREATE POLICY trial_checkout_attempt_expire ON public.billing_checkout_attempts FOR UPDATE TO ceopro_trial_issuer
 USING(tenant_id=public.billing_webhook_tenant()) WITH CHECK(tenant_id=public.billing_webhook_tenant() AND state='expired');
CREATE POLICY trial_checkout_app ON public.billing_trial_checkouts FOR SELECT TO ceopro_app USING(tenant_id=public.get_current_tenant());
CREATE POLICY trial_checkout_setup ON public.billing_trial_checkouts FOR SELECT TO ceopro_billing_setup USING(tenant_id=public.get_current_tenant());
CREATE POLICY trial_checkout_webhook ON public.billing_trial_checkouts FOR SELECT TO ceopro_billing_webhook USING(tenant_id=public.billing_webhook_tenant());
CREATE POLICY trial_checkout_issuer ON public.billing_trial_checkouts TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant() OR started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_checkout_attempts,public.billing_webhook_events TO ceopro_trial_issuer;
CREATE POLICY trial_checkout_attempt_read ON public.billing_checkout_attempts FOR SELECT TO ceopro_trial_issuer USING(tenant_id=public.get_current_tenant());
CREATE POLICY trial_checkout_receipt_read ON public.billing_webhook_events FOR SELECT TO ceopro_trial_issuer
 USING(stripe_event_id=current_setting('app.billing_event_id',true) AND tenant_id=public.get_current_tenant());
GRANT EXECUTE ON FUNCTION public.billing_webhook_tenant() TO ceopro_trial_issuer;
CREATE POLICY trial_confirmation_person_read ON public.billing_trials FOR SELECT TO ceopro_trial_issuer
 USING(EXISTS(SELECT FROM public.billing_trial_checkouts c WHERE c.tenant_id=public.get_current_tenant() AND c.started_by_user_id=billing_trials.started_by_user_id));
DROP POLICY billing_setup_trial_insert ON public.billing_trials;
CREATE POLICY trial_confirmation_insert ON public.billing_trials FOR INSERT TO ceopro_trial_issuer
 WITH CHECK(tenant_id=public.billing_webhook_tenant() AND EXISTS(SELECT FROM public.billing_trial_checkouts c
  WHERE c.tenant_id=billing_trials.tenant_id AND c.plan_key=billing_trials.plan_key AND c.started_by_user_id=billing_trials.started_by_user_id AND c.state='pending'));

-- Keep the existing eligibility API, but close its local/cardless activation command.
CREATE OR REPLACE FUNCTION public.billing_setup_trial(p_plan TEXT,p_start BOOLEAN DEFAULT FALSE) RETURNS JSONB
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t UUID:=public.get_current_tenant(); u UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 d INTEGER; s BOOLEAN; a BOOLEAN; r TEXT;
BEGIN
 IF p_start IS NULL THEN RAISE EXCEPTION 'Explicit trial operation required' USING ERRCODE='22023'; END IF;
 IF public.keel_active_principal(u,t) IS DISTINCT FROM TRUE THEN RAISE EXCEPTION 'active principal required' USING ERRCODE='42501'; END IF;
 IF p_start THEN RAISE EXCEPTION 'Trials require verified provider confirmation' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT trial_days,self_serve,is_active INTO d,s,a FROM public.usage_plans WHERE plan_key=p_plan;
 IF NOT FOUND OR NOT a OR NOT s OR d<=0 THEN r:='plan_has_no_trial';
 ELSIF EXISTS(SELECT FROM public.billing_trials WHERE tenant_id=t) THEN r:='trial_already_used';
 ELSIF EXISTS(SELECT FROM public.billing_trials WHERE started_by_user_id=u) THEN r:='trial_already_used_by_person';
 ELSIF EXISTS(SELECT FROM public.tenant_plan_assignments WHERE tenant_id=t) THEN r:='plan_already_assigned';
 ELSIF EXISTS(SELECT FROM public.billing_subscriptions WHERE tenant_id=t) THEN r:='subscription_exists';
 ELSIF EXISTS(SELECT FROM public.billing_trial_checkouts WHERE started_by_user_id=u AND tenant_id<>t AND state='pending') THEN r:='trial_checkout_pending'; END IF;
 RETURN jsonb_build_object('reason',r);
END $$;

CREATE FUNCTION public.billing_reserve_trial_checkout(p_attempt UUID,p_plan TEXT,p_period TEXT) RETURNS JSONB
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t UUID:=public.get_current_tenant(); u UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 c public.billing_trial_checkouts; r TEXT; d INTEGER; price TEXT;
BEGIN
 IF public.keel_active_principal(u,t) IS DISTINCT FROM TRUE OR NOT EXISTS(SELECT FROM public.tenant_users
  WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'billing role required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT * INTO c FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt;
 IF FOUND THEN
  IF c.tenant_id<>t OR c.started_by_user_id<>u OR c.plan_key<>p_plan OR c.period_code<>p_period OR c.state<>'pending'
  THEN RAISE EXCEPTION 'trial checkout identity conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(c);
 END IF;
 r:=public.billing_setup_trial(p_plan,FALSE)->>'reason';
 IF r IS NOT NULL THEN RETURN jsonb_build_object('reason',r); END IF;
 IF NOT EXISTS(SELECT FROM public.billing_checkout_attempts WHERE attempt_id=p_attempt AND tenant_id=t
  AND plan_key=p_plan AND period_code=p_period AND state IN ('preparing','open'))
 THEN RAISE EXCEPTION 'authorized checkout attempt required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT FROM public.billing_trial_checkouts WHERE started_by_user_id=u AND state='pending')
 THEN RETURN jsonb_build_object('reason','trial_checkout_pending'); END IF;
 SELECT trial_days INTO d FROM public.usage_plans WHERE plan_key=p_plan;
 SELECT stripe_price_id INTO price FROM public.billing_plan_prices WHERE plan_key=p_plan AND period_code=p_period AND retired_at IS NULL;
 IF nullif(price,'') IS NULL THEN RAISE EXCEPTION 'published provider price required' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_trial_checkouts(attempt_id,tenant_id,started_by_user_id,plan_key,period_code,trial_duration_days,provider_price_id)
 VALUES(p_attempt,t,u,p_plan,p_period,d,price) RETURNING * INTO c;
 RETURN to_jsonb(c);
END $$;
ALTER FUNCTION public.billing_reserve_trial_checkout(UUID,TEXT,TEXT) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_reserve_trial_checkout(UUID,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_reserve_trial_checkout(UUID,TEXT,TEXT) TO ceopro_billing_setup;

CREATE FUNCTION public.billing_release_trial_checkout(p_attempt UUID) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 UPDATE public.billing_trial_checkouts c SET state='released' WHERE c.attempt_id=p_attempt
  AND c.tenant_id=public.get_current_tenant() AND c.state='pending'
  AND EXISTS(SELECT FROM public.billing_checkout_attempts a WHERE a.attempt_id=c.attempt_id AND a.state='expired');
END $$;
ALTER FUNCTION public.billing_release_trial_checkout(UUID) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_release_trial_checkout(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_release_trial_checkout(UUID) TO ceopro_billing_setup;

CREATE FUNCTION public.billing_expire_trial_checkout(p_attempt UUID,p_session TEXT) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t UUID:=public.billing_webhook_tenant();
BEGIN
 IF t IS NULL THEN RAISE EXCEPTION 'bound verified payment receipt required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT FROM public.billing_checkout_attempts WHERE attempt_id=p_attempt AND tenant_id=t AND stripe_session_id=p_session)
 THEN RAISE EXCEPTION 'checkout session identity conflict' USING ERRCODE='42501'; END IF;
 UPDATE public.billing_checkout_attempts SET state='expired',updated_at=clock_timestamp()
 WHERE attempt_id=p_attempt AND tenant_id=t AND state IN ('preparing','open');
 UPDATE public.billing_trial_checkouts SET state='released' WHERE attempt_id=p_attempt AND tenant_id=t AND state='pending';
END $$;
ALTER FUNCTION public.billing_expire_trial_checkout(UUID,TEXT) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_expire_trial_checkout(UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_expire_trial_checkout(UUID,TEXT) TO ceopro_billing_webhook;

CREATE FUNCTION public.billing_confirm_trial_checkout(p_attempt UUID,p_provider TEXT,p_subscription TEXT,p_started TIMESTAMPTZ,p_ends TIMESTAMPTZ) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t UUID:=public.billing_webhook_tenant(); c public.billing_trial_checkouts;
BEGIN
 IF t IS NULL THEN RAISE EXCEPTION 'bound verified payment receipt required' USING ERRCODE='42501'; END IF;
 SELECT * INTO c FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=t;
 IF NOT FOUND THEN RAISE EXCEPTION 'authorized trial checkout required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||c.started_by_user_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT * INTO c FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=t FOR UPDATE;
 IF c.state='activated' AND c.provider=p_provider AND c.provider_subscription_id=p_subscription THEN RETURN; END IF;
 IF c.state<>'pending' OR nullif(p_provider,'') IS NULL OR nullif(p_subscription,'') IS NULL
  OR p_started IS NULL OR p_ends IS NULL OR extract(epoch FROM (p_ends-p_started))<>c.trial_duration_days::bigint*86400
 THEN RAISE EXCEPTION 'provider trial does not match authorized terms' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT FROM public.billing_trials WHERE tenant_id=t OR started_by_user_id=c.started_by_user_id)
  OR EXISTS(SELECT FROM public.tenant_plan_assignments WHERE tenant_id=t)
  OR EXISTS(SELECT FROM public.billing_subscriptions WHERE tenant_id=t)
 THEN RAISE EXCEPTION 'one-time trial eligibility already consumed' USING ERRCODE='23505'; END IF;
 INSERT INTO public.billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id)
 VALUES(t,c.plan_key,p_started,p_ends,c.started_by_user_id);
 UPDATE public.billing_trial_checkouts SET state='activated',provider=p_provider,provider_subscription_id=p_subscription,activated_at=clock_timestamp()
 WHERE attempt_id=p_attempt;
 -- No assignment is created here. The verified reconciliation transaction owns it.
END $$;
ALTER FUNCTION public.billing_confirm_trial_checkout(UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_confirm_trial_checkout(UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_confirm_trial_checkout(UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ) TO ceopro_billing_webhook;
