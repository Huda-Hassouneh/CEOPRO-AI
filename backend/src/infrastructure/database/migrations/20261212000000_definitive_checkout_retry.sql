-- 178: one audited Paddle TEST retry after a conclusive domain-validation rejection.
-- No original submission reset, new runtime EXECUTE, provider capability or activation grant.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_trial_issuer' AND NOT rolcanlogin
   AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit)
 THEN RAISE EXCEPTION 'Restricted issuer prerequisites required' USING ERRCODE='42501'; END IF;
END $$;
CREATE TABLE public.billing_checkout_retry_authorizations (
 attempt_id uuid PRIMARY KEY REFERENCES public.billing_journey_dispatches(attempt_id),
 retry_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 actor_id uuid NOT NULL REFERENCES public.users(user_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 provider_customer_id text NOT NULL,original_submitted_at timestamptz NOT NULL,
 request jsonb NOT NULL,evidence jsonb NOT NULL,
 approved_by uuid NOT NULL REFERENCES public.users(user_id),approval_reference text NOT NULL CHECK(btrim(approval_reference)<>''),
 authorized_at timestamptz NOT NULL DEFAULT clock_timestamp(),retry_submitted_at timestamptz,result jsonb,
 CHECK(result IS NULL OR retry_submitted_at IS NOT NULL)
);
ALTER TABLE public.billing_checkout_retry_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_checkout_retry_authorizations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_checkout_retry_authorizations FROM PUBLIC,ceopro_app,ceopro_billing_setup,
 ceopro_billing_webhook,ceopro_credit_accounting,ceopro_consent_service,ceopro_billing_observer,
 ceopro_trial_issuer,ceopro_trial_attestor,ceopro_trial_confirmer,ceopro_journey_router;
GRANT SELECT,UPDATE(retry_submitted_at) ON public.billing_checkout_retry_authorizations TO ceopro_consent_owner;
CREATE POLICY checkout_retry_scope ON public.billing_checkout_retry_authorizations TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_checkout_retry_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Retry history is immutable' USING ERRCODE='22023'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.retry_submitted_at IS NOT NULL OR NEW.result IS NOT NULL THEN RAISE EXCEPTION 'New retry must be unsent' USING ERRCODE='22023'; END IF;
  NEW.authorized_at:=clock_timestamp();RETURN NEW;
 END IF;
 IF (to_jsonb(NEW)-'retry_submitted_at'-'result') IS DISTINCT FROM (to_jsonb(OLD)-'retry_submitted_at'-'result')
 THEN RAISE EXCEPTION 'Retry identity/evidence is immutable' USING ERRCODE='22023'; END IF;
 IF OLD.retry_submitted_at IS NULL AND NEW.retry_submitted_at IS NOT NULL AND NEW.result IS NULL
   AND current_user='ceopro_consent_owner' THEN NEW.retry_submitted_at:=clock_timestamp();RETURN NEW; END IF;
 IF OLD.retry_submitted_at IS NOT NULL AND NEW.retry_submitted_at=OLD.retry_submitted_at
   AND OLD.result IS NULL AND NEW.result IS NOT NULL AND current_user<>'ceopro_consent_owner' THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Single retry and append-only result required' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.billing_checkout_retry_guard() FROM PUBLIC;
CREATE TRIGGER checkout_retry_history BEFORE INSERT OR UPDATE OR DELETE ON public.billing_checkout_retry_authorizations
 FOR EACH ROW EXECUTE FUNCTION public.billing_checkout_retry_guard();

-- Invoker/installer-only: never grant this function or table INSERT to runtime.
-- The separately authenticated operator validates the captured TLS response and
-- performs fresh bound GETs outside the SQL transaction before submitting evidence.
CREATE FUNCTION public.billing_authorize_checkout_retry(p_attempt uuid,p_evidence jsonb,p_reference text) RETURNS jsonb
 LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE d public.billing_journey_dispatches;r public.billing_trial_checkouts;b public.billing_gateway_bindings;
 owner_id uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 owner_tenant uuid:=public.get_current_tenant();v public.billing_checkout_retry_authorizations;BEGIN
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt FOR UPDATE;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('keel_platform_authority',0))
 THEN RAISE EXCEPTION 'Authority busy' USING ERRCODE='55P03'; END IF;
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'Read committed operator required' USING ERRCODE='25001'; END IF;
 PERFORM 1 FROM public.companies WHERE tenant_id=owner_tenant FOR SHARE NOWAIT;
 PERFORM 1 FROM public.users WHERE user_id=owner_id FOR SHARE NOWAIT;
 PERFORM 1 FROM public.tenant_users WHERE tenant_id=owner_tenant AND user_id=owner_id FOR SHARE NOWAIT;
 PERFORM 1 FROM public.keel_platform_members WHERE user_id=owner_id FOR SHARE NOWAIT;
 IF NOT EXISTS(SELECT FROM public.keel_platform_members m CROSS JOIN public.keel_platform_workspace w
   WHERE m.user_id=owner_id AND m.role_key='owner' AND m.status='active' AND w.tenant_id=owner_tenant
     AND public.keel_active_principal(owner_id,owner_tenant))
 THEN RAISE EXCEPTION 'Authenticated current Platform Owner required' USING ERRCODE='42501'; END IF;
 SELECT * INTO d FROM public.billing_journey_dispatches WHERE attempt_id=p_attempt;
 SELECT * INTO b FROM public.billing_gateway_bindings WHERE binding_id=d.binding_id;
 IF r.attempt_id IS NULL OR r.state<>'pending' OR b.provider IS DISTINCT FROM 'paddle' OR b.environment IS DISTINCT FROM 'test'
  OR d.submitted_at IS NULL OR d.provider_checkout_id IS NOT NULL OR d.expired_at IS NOT NULL
  OR d.tenant_id<>r.tenant_id OR d.binding_id<>r.binding_id
 THEN RAISE EXCEPTION 'Original unresolved Paddle TEST dispatch required' USING ERRCODE='22023'; END IF;
 IF p_evidence IS NULL OR jsonb_typeof(p_evidence)<>'object' OR p_reference IS NULL OR btrim(p_reference)=''
  OR p_evidence->>'binding_id' IS DISTINCT FROM d.binding_id
  OR p_evidence->>'merchant_account_id' IS DISTINCT FROM b.merchant_account_id
  OR p_evidence->>'customer_id' IS DISTINCT FROM d.provider_customer_id
  OR p_evidence->'request' IS DISTINCT FROM d.request->'transport'
  OR p_evidence#>>'{rejection,status}' IS DISTINCT FROM '400'
  OR p_evidence#>>'{rejection,error,type}' IS DISTINCT FROM 'request_error'
  OR p_evidence#>>'{rejection,error,code}' IS DISTINCT FROM 'transaction_checkout_url_domain_is_not_approved'
  OR nullif(p_evidence#>>'{rejection,request_id}','') IS NULL
  OR p_evidence#>>'{rejection,response_sha256}' IS NULL
  OR (p_evidence#>>'{rejection,response_sha256}') !~ '^sha256:[0-9a-f]{64}$'
  OR p_evidence#>>'{recovery,status}' IS DISTINCT FROM '200'
  OR p_evidence#>'{recovery,data}' IS DISTINCT FROM '[]'::jsonb
  OR p_evidence#>'{recovery,has_more}' IS DISTINCT FROM 'false'::jsonb
  OR p_evidence#>>'{recovery,customer_id}' IS DISTINCT FROM d.provider_customer_id
  OR nullif(p_evidence#>>'{recovery,request_id}','') IS NULL
  OR p_evidence#>>'{recovery,observed_at}' IS NULL
  OR (p_evidence#>>'{recovery,observed_at}')::timestamptz NOT BETWEEN clock_timestamp()-interval '5 minutes' AND clock_timestamp()+interval '5 seconds'
  OR p_evidence#>>'{namespace,id}' IS DISTINCT FROM b.merchant_account_id
 THEN RAISE EXCEPTION 'Conclusive bound rejection and fresh empty recovery required' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_checkout_retry_authorizations(attempt_id,tenant_id,actor_id,binding_id,provider_customer_id,
  original_submitted_at,request,evidence,approved_by,approval_reference)
 VALUES(d.attempt_id,d.tenant_id,r.started_by_user_id,d.binding_id,d.provider_customer_id,d.submitted_at,d.request,
  p_evidence,owner_id,p_reference) RETURNING * INTO v;
 RETURN to_jsonb(v);
END $$;
REVOKE ALL ON FUNCTION public.billing_authorize_checkout_retry(uuid,jsonb,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.billing_journey_dispatch(p_attempt uuid,p_acceptance uuid,p_customer uuid,p_request jsonb,p_action text,p_session text DEFAULT NULL)
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
  ELSE
   -- The original submission/history is never reset. Only a separately audited,
   -- operator-authorized definitive rejection can elect this single retry.
   UPDATE public.billing_checkout_retry_authorizations SET retry_submitted_at=clock_timestamp()
    WHERE attempt_id=p_attempt AND tenant_id=r.tenant_id AND actor_id=u
      AND binding_id=d.binding_id AND provider_customer_id=d.provider_customer_id
      AND original_submitted_at=d.submitted_at AND request=d.request
      AND retry_submitted_at IS NULL AND authorized_at>clock_timestamp()-interval '5 minutes';
   elected:=FOUND;
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
