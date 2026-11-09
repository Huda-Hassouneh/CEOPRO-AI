-- Coordinated dormant journey. No policy seed, LOGIN or activation grants.
ALTER TABLE public.companies ADD COLUMN subscription_journey_required boolean NOT NULL DEFAULT false;
CREATE FUNCTION public.billing_journey_company_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_OP='INSERT' THEN
  NEW.subscription_journey_required:=coalesce(current_setting('app.recurring_journey_required',true),'false')='true';
 ELSIF NEW.subscription_journey_required IS DISTINCT FROM OLD.subscription_journey_required THEN
  RAISE EXCEPTION 'Journey cohort is immutable' USING ERRCODE='22023';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_company_guard() FROM PUBLIC;
CREATE TRIGGER journey_company BEFORE INSERT OR UPDATE ON public.companies FOR EACH ROW EXECUTE FUNCTION public.billing_journey_company_guard();
CREATE TABLE public.billing_journey_dispatches (
 attempt_id uuid PRIMARY KEY REFERENCES public.billing_trial_checkouts(attempt_id),
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 acceptance_id uuid NOT NULL UNIQUE REFERENCES public.billing_consent_acceptances(acceptance_id),
 customer_operation_id uuid NOT NULL REFERENCES public.billing_customer_operations(operation_id),
 provider_customer_id text NOT NULL,
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 request jsonb NOT NULL,
 submitted_at timestamptz,
 provider_checkout_id text,
 provider_subscription_id text,
 expired_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(jsonb_typeof(request)='object'),
 CHECK(provider_checkout_id IS NULL OR submitted_at IS NOT NULL)
);
ALTER TABLE public.billing_journey_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_journey_dispatches FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_journey_dispatches FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,
 ceopro_credit_accounting,ceopro_billing_observer,ceopro_trial_attestor,ceopro_trial_confirmer;
GRANT SELECT,INSERT,UPDATE(submitted_at,provider_checkout_id,provider_subscription_id,expired_at) ON public.billing_journey_dispatches TO ceopro_consent_owner;
CREATE POLICY journey_owner ON public.billing_journey_dispatches TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_journey_dispatches TO ceopro_trial_issuer;
CREATE POLICY journey_issuer_read ON public.billing_journey_dispatches FOR SELECT TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_verification_observations TO ceopro_consent_owner;
GRANT SELECT(subscription_journey_required) ON public.companies TO ceopro_consent_owner;
CREATE POLICY journey_consent_history ON public.billing_verification_observations FOR SELECT TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant());
-- Preserve the original Checkout scope guard and its sole issuer ownership.
-- No caller-controlled payload or state; copy only the protected dispatch row.
CREATE FUNCTION public.billing_journey_checkout_checkpoint(p_attempt uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d public.billing_journey_dispatches; BEGIN
 IF session_user<>'ceopro_consent_service' THEN RAISE EXCEPTION 'Consent socket required' USING ERRCODE='42501'; END IF;
 SELECT * INTO d FROM public.billing_journey_dispatches WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant();
 IF d.attempt_id IS NULL THEN RAISE EXCEPTION 'Protected dispatch required' USING ERRCODE='42501'; END IF;
 UPDATE public.billing_checkout_attempts SET provider_params=d.request->'transport',replay_window_seconds=1,
  first_submitted_at=d.submitted_at,provider_session_id=d.provider_checkout_id,
  state=CASE WHEN d.expired_at IS NOT NULL THEN 'expired' WHEN d.provider_checkout_id IS NULL THEN 'preparing' ELSE 'open' END,updated_at=clock_timestamp()
 WHERE attempt_id=p_attempt AND tenant_id=d.tenant_id AND gateway_binding_id=d.binding_id AND state IN ('preparing','open');
 IF NOT FOUND THEN RAISE EXCEPTION 'Pending Checkout required' USING ERRCODE='22023'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_checkout_checkpoint(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_journey_checkout_checkpoint(uuid) TO ceopro_consent_owner;
GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_journey_checkout_checkpoint(uuid) OWNER TO ceopro_trial_issuer;
REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer;

CREATE FUNCTION public.billing_journey_dispatch(p_attempt uuid,p_acceptance uuid,p_customer uuid,p_request jsonb,p_action text,p_session text DEFAULT NULL)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts; a public.billing_consent_acceptances; v public.billing_consent_presentations;
 c public.billing_customer_operations; d public.billing_journey_dispatches; u uuid; elected boolean:=false;
BEGIN
 -- Same reservation -> presentation -> nonblocking authority order as withdrawal.
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant() FOR UPDATE;
 u:=public.billing_consent_authorize();
 IF r.attempt_id IS NULL OR r.started_by_user_id IS DISTINCT FROM u
 THEN RAISE EXCEPTION 'Owned journey required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT FROM public.companies WHERE tenant_id=r.tenant_id AND subscription_journey_required)
 THEN RAISE EXCEPTION 'Original journey cohort required' USING ERRCODE='42501'; END IF;
 SELECT * INTO d FROM public.billing_journey_dispatches WHERE attempt_id=p_attempt;
 IF p_action='read' THEN
  IF d.attempt_id IS NULL THEN RETURN '{}'::jsonb; END IF;
  RETURN to_jsonb(d)||jsonb_build_object('presentation_id',(SELECT presentation_id FROM public.billing_consent_acceptances WHERE acceptance_id=d.acceptance_id));
 END IF;
 IF d.expired_at IS NOT NULL THEN
  IF p_action='expired' THEN RETURN to_jsonb(d); END IF;
  RAISE EXCEPTION 'Checkout expired' USING ERRCODE='55000';
 END IF;
 SELECT * INTO a FROM public.billing_consent_acceptances WHERE acceptance_id=p_acceptance AND attempt_id=p_attempt AND actor_id=u;
 IF a.acceptance_id IS NULL THEN RAISE EXCEPTION 'Accepted consent required' USING ERRCODE='22023'; END IF;
 v:=public.billing_consent_locked(a.presentation_id);
 SELECT * INTO c FROM public.billing_customer_operations WHERE operation_id=p_customer AND tenant_id=r.tenant_id;
 IF c.state IS DISTINCT FROM 'succeeded' OR c.binding_id IS DISTINCT FROM r.binding_id
 OR a.binding_id IS DISTINCT FROM r.binding_id OR r.state<>'pending'
 THEN RAISE EXCEPTION 'Original successful Customer required' USING ERRCODE='22023'; END IF;
 IF p_action='prepare' THEN
  IF p_request IS NULL OR p_request->'approved_terms' IS DISTINCT FROM r.approved_terms
   OR p_request->>'customer' IS DISTINCT FROM c.provider_customer_id
   OR p_request->>'idempotency_key' IS DISTINCT FROM 'keel-trial-checkout-'||p_attempt::text
   OR jsonb_typeof(p_request->'transport') IS DISTINCT FROM 'object'
  THEN RAISE EXCEPTION 'Frozen dispatch conflict' USING ERRCODE='22023'; END IF;
  IF d.attempt_id IS NOT NULL THEN
   IF d.acceptance_id<>p_acceptance OR d.customer_operation_id<>p_customer OR d.request IS DISTINCT FROM p_request
   THEN RAISE EXCEPTION 'Dispatch replay conflict' USING ERRCODE='22023'; END IF;
  ELSE
   -- A previously submitted generic attempt must never be adopted/rebuilt.
   IF EXISTS(SELECT FROM public.billing_checkout_attempts WHERE attempt_id=p_attempt
      AND (provider_params IS NOT NULL OR first_submitted_at IS NOT NULL OR provider_session_id IS NOT NULL OR state<>'preparing'))
   THEN RAISE EXCEPTION 'Existing Checkout requires reconciliation' USING ERRCODE='55000'; END IF;
   INSERT INTO public.billing_journey_dispatches(attempt_id,tenant_id,acceptance_id,customer_operation_id,provider_customer_id,binding_id,request)
   VALUES(p_attempt,r.tenant_id,p_acceptance,p_customer,c.provider_customer_id,r.binding_id,p_request) RETURNING * INTO d;
  END IF;
 ELSIF d.attempt_id IS NULL OR d.acceptance_id<>p_acceptance OR d.customer_operation_id<>p_customer THEN
  RAISE EXCEPTION 'Prepared dispatch required' USING ERRCODE='22023';
 ELSIF p_action='elect' THEN
  IF d.submitted_at IS NULL THEN
   UPDATE public.billing_journey_dispatches SET submitted_at=clock_timestamp() WHERE attempt_id=p_attempt RETURNING * INTO d;
   elected:=true;
  END IF;
 ELSIF p_action='session' THEN
  IF d.submitted_at IS NULL OR nullif(btrim(p_session),'') IS NULL
   OR (d.provider_checkout_id IS NOT NULL AND d.provider_checkout_id<>p_session)
  THEN RAISE EXCEPTION 'Checkout association conflict' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_journey_dispatches SET provider_checkout_id=p_session WHERE attempt_id=p_attempt RETURNING * INTO d;
 ELSIF p_action='subscription' THEN
  IF nullif(btrim(p_session),'') IS NULL OR (d.provider_subscription_id IS NOT NULL AND d.provider_subscription_id<>p_session)
   OR NOT EXISTS(SELECT FROM public.billing_observation_operations o JOIN public.billing_verification_observations h ON h.observation_id=o.last_observation_id
     WHERE o.attempt_id=r.attempt_id AND o.tenant_id=r.tenant_id AND o.binding_id=r.binding_id AND NOT o.has_conflict
     AND o.provider_customer_id=d.provider_customer_id AND o.provider_checkout_id=d.provider_checkout_id
     AND h.evidence->>'subscription'=p_session AND h.source='authoritative_lookup' AND h.outcome='pending')
  THEN RAISE EXCEPTION 'Exact immutable subscription evidence required' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_journey_dispatches SET provider_subscription_id=p_session WHERE attempt_id=p_attempt RETURNING * INTO d;
 ELSIF p_action='expired' AND d.provider_checkout_id IS NOT NULL THEN
  UPDATE public.billing_journey_dispatches SET expired_at=clock_timestamp() WHERE attempt_id=p_attempt RETURNING * INTO d;
 ELSIF p_action<>'authorize' OR d.submitted_at IS NULL THEN
  RAISE EXCEPTION 'Unsupported dispatch action' USING ERRCODE='22023';
 END IF;
 PERFORM public.billing_journey_checkout_checkpoint(p_attempt);
 RETURN to_jsonb(d)||jsonb_build_object('elected',elected);
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_dispatch(uuid,uuid,uuid,jsonb,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_journey_dispatch(uuid,uuid,uuid,jsonb,text,text) TO ceopro_consent_service;
GRANT CREATE ON SCHEMA public TO ceopro_consent_owner;
ALTER FUNCTION public.billing_journey_dispatch(uuid,uuid,uuid,jsonb,text,text) OWNER TO ceopro_consent_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_consent_owner;

-- Reuse immutable authoritative B3 history for a SetupIntent first observed on
-- this exact subscription. No customer-wide search or attached-card inference.
CREATE FUNCTION public.billing_observation_setup_source(p_operation uuid,p_subscription text) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.billing_observation_operations; s text;
BEGIN
 PERFORM public.billing_observation_principal();
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=p_operation
 AND tenant_id=public.get_current_tenant() AND initiated_by=nullif(current_setting('app.current_user_id',true),'')::uuid;
 IF o.operation_id IS NULL THEN RAISE EXCEPTION 'Owned observation required' USING ERRCODE='42501'; END IF;
 IF o.has_conflict THEN RAISE EXCEPTION 'Conflicting history' USING ERRCODE='22023'; END IF;
 SELECT evidence#>>'{recurring_authority,source}' INTO s FROM public.billing_verification_observations
 WHERE operation_id=o.operation_id AND source='authoritative_lookup' AND evidence->>'subscription'=p_subscription
 AND evidence#>>'{recurring_authority,kind}'='payment_method_setup'
 AND evidence#>>'{recurring_authority,source}' IS NOT NULL
 ORDER BY observed_at DESC LIMIT 1;
 RETURN s;
END $$;
REVOKE ALL ON FUNCTION public.billing_observation_setup_source(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_observation_setup_source(uuid,text) TO ceopro_billing_observer;
GRANT CREATE ON SCHEMA public TO ceopro_observation_owner;
ALTER FUNCTION public.billing_observation_setup_source(uuid,text) OWNER TO ceopro_observation_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_observation_owner;

-- Global, read-only cohort classification BEFORE legacy mutation. Deliberately
-- conservative across namespaces: ambiguous IDs quarantine rather than activate.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_journey_router') THEN
  CREATE ROLE ceopro_journey_router NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 ELSIF EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_journey_router' AND
  (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolbypassrls OR rolreplication))
  OR EXISTS(SELECT FROM pg_auth_members WHERE roleid='ceopro_journey_router'::regrole OR member='ceopro_journey_router'::regrole)
 THEN RAISE EXCEPTION 'Unsafe journey router role' USING ERRCODE='42501'; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO ceopro_journey_router;
GRANT SELECT ON public.companies TO ceopro_journey_router;
CREATE POLICY journey_route_company ON public.companies FOR SELECT TO ceopro_journey_router USING(true);
GRANT SELECT ON public.billing_trial_checkouts,public.billing_checkout_attempts,public.billing_customer_operations,
 public.billing_observation_operations,public.billing_verification_observations TO ceopro_journey_router;
CREATE POLICY journey_route_reservation ON public.billing_trial_checkouts FOR SELECT TO ceopro_journey_router USING(true);
CREATE POLICY journey_route_checkout ON public.billing_checkout_attempts FOR SELECT TO ceopro_journey_router USING(true);
CREATE POLICY journey_route_customer ON public.billing_customer_operations FOR SELECT TO ceopro_journey_router USING(true);
CREATE POLICY journey_route_observation ON public.billing_observation_operations FOR SELECT TO ceopro_journey_router USING(true);
CREATE POLICY journey_route_history ON public.billing_verification_observations FOR SELECT TO ceopro_journey_router USING(true);
CREATE FUNCTION public.billing_journey_is_protected(p_customer text,p_checkout text,p_subscription text) RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT FROM public.billing_trial_checkouts r
 JOIN public.billing_checkout_attempts a USING(attempt_id,tenant_id)
 WHERE a.provider_session_id=p_checkout
 OR EXISTS(SELECT FROM public.billing_customer_operations c WHERE c.tenant_id=r.tenant_id AND c.binding_id=r.binding_id AND c.provider_customer_id=p_customer)
 OR EXISTS(SELECT FROM public.billing_observation_operations o WHERE o.attempt_id=r.attempt_id AND
  (o.provider_subscription_id=p_subscription OR EXISTS(SELECT FROM public.billing_verification_observations h
    WHERE h.operation_id=o.operation_id AND h.evidence->>'subscription'=p_subscription))))
 $$;
REVOKE ALL ON FUNCTION public.billing_journey_is_protected(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_journey_is_protected(text,text,text) TO ceopro_billing_webhook;
GRANT CREATE ON SCHEMA public TO ceopro_journey_router;
ALTER FUNCTION public.billing_journey_is_protected(text,text,text) OWNER TO ceopro_journey_router;
REVOKE CREATE ON SCHEMA public FROM ceopro_journey_router;

CREATE TABLE public.billing_journey_cancellations (
 attempt_id uuid PRIMARY KEY REFERENCES public.billing_trial_checkouts(attempt_id),tenant_id uuid NOT NULL,
 requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),confirmed_at timestamptz
);
ALTER TABLE public.billing_journey_cancellations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_journey_cancellations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_journey_cancellations FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,
 ceopro_credit_accounting,ceopro_billing_observer,ceopro_trial_attestor,ceopro_trial_confirmer;
GRANT SELECT,INSERT,UPDATE(confirmed_at) ON public.billing_journey_cancellations TO ceopro_consent_owner;
CREATE POLICY journey_cancellation_owner ON public.billing_journey_cancellations TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_trial_confirmations TO ceopro_consent_owner;
CREATE POLICY journey_cancellation_confirmation ON public.billing_trial_confirmations FOR SELECT TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_journey_cancellation(p_attempt uuid,p_action text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts; c public.billing_trial_confirmations; v public.billing_journey_cancellations;
 u uuid;elected boolean:=false;
BEGIN
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant() FOR UPDATE;
 u:=public.billing_consent_authorize();
 IF r.attempt_id IS NULL OR r.started_by_user_id IS DISTINCT FROM u OR r.state<>'confirmed'
 THEN RAISE EXCEPTION 'Owned confirmed journey required' USING ERRCODE='42501'; END IF;
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE confirmation_id=r.confirmation_id AND attempt_id=r.attempt_id;
 IF c.confirmation_id IS NULL THEN RAISE EXCEPTION 'Original confirmation required' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.billing_journey_cancellations WHERE attempt_id=r.attempt_id;
 IF p_action='elect' AND v.attempt_id IS NULL THEN
  INSERT INTO public.billing_journey_cancellations(attempt_id,tenant_id) VALUES(r.attempt_id,r.tenant_id) RETURNING * INTO v;
  elected:=true;
 ELSIF p_action='record' AND v.attempt_id IS NOT NULL THEN
  UPDATE public.billing_journey_cancellations SET confirmed_at=coalesce(confirmed_at,clock_timestamp()) WHERE attempt_id=r.attempt_id RETURNING * INTO v;
 ELSIF p_action NOT IN ('read','elect') THEN RAISE EXCEPTION 'Cancellation operation conflict' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('confirmation',to_jsonb(c),'cancellation',to_jsonb(v),'elected',elected);
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_cancellation(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_journey_cancellation(uuid,text) TO ceopro_consent_service;
GRANT CREATE ON SCHEMA public TO ceopro_consent_owner;
ALTER FUNCTION public.billing_journey_cancellation(uuid,text) OWNER TO ceopro_consent_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_consent_owner;

-- Durable new-cohort exclusion from legacy trial/subscription/rights writers,
-- including direct existing SQL commands. B4 remains the sole trial writer.
CREATE FUNCTION public.billing_journey_rights_fence() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF EXISTS(SELECT FROM public.companies WHERE tenant_id=NEW.tenant_id AND subscription_journey_required)
 AND session_user<>'ceopro_trial_confirmer'
 AND NOT EXISTS(SELECT FROM pg_roles WHERE rolname=session_user AND rolsuper)
 THEN RAISE EXCEPTION 'Trusted journey confirmation required' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_rights_fence() FROM PUBLIC;
GRANT CREATE ON SCHEMA public TO ceopro_journey_router;
ALTER FUNCTION public.billing_journey_rights_fence() OWNER TO ceopro_journey_router;
REVOKE CREATE ON SCHEMA public FROM ceopro_journey_router;
CREATE TRIGGER journey_trial_fence BEFORE INSERT OR UPDATE ON public.billing_trials FOR EACH ROW EXECUTE FUNCTION public.billing_journey_rights_fence();
CREATE TRIGGER journey_subscription_fence BEFORE INSERT OR UPDATE ON public.billing_subscriptions FOR EACH ROW EXECUTE FUNCTION public.billing_journey_rights_fence();
CREATE TRIGGER journey_entitlement_fence BEFORE INSERT OR UPDATE ON public.tenant_plan_assignments FOR EACH ROW EXECUTE FUNCTION public.billing_journey_rights_fence();
