-- B2b-2: append-only pre-confirmation withdrawal, no policy seed or runtime grants.
-- Ordered after A2 (172). Existing B4 evidence remains immutable.
CREATE OR REPLACE FUNCTION public.billing_consent_locked(p_presentation uuid) RETURNS public.billing_consent_presentations
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v public.billing_consent_presentations;r public.billing_trial_checkouts;u uuid; BEGIN
 SELECT * INTO v FROM public.billing_consent_presentations WHERE presentation_id=p_presentation AND tenant_id=public.get_current_tenant();
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent presentation unavailable' USING ERRCODE='42501'; END IF;
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=v.attempt_id FOR SHARE;
 SELECT * INTO v FROM public.billing_consent_presentations WHERE presentation_id=p_presentation FOR UPDATE;
 u:=public.billing_consent_authorize();
 IF v.actor_id IS DISTINCT FROM u OR r.started_by_user_id IS DISTINCT FROM u OR r.tenant_id IS DISTINCT FROM v.tenant_id
 OR r.binding_id IS DISTINCT FROM v.binding_id OR r.approved_terms IS DISTINCT FROM v.approved_terms OR r.state<>'pending'
 THEN RAISE EXCEPTION 'Consent reservation conflict' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT FROM public.billing_consent_invalidations WHERE presentation_id=v.presentation_id)
 THEN RAISE EXCEPTION 'Consent invalidated' USING ERRCODE='22023'; END IF;
 RETURN v;
END $$;

CREATE OR REPLACE FUNCTION public.billing_consent_invalidate(p_presentation uuid,p_reason text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v public.billing_consent_presentations;r public.billing_trial_checkouts;
 i public.billing_consent_invalidations;u uuid; BEGIN
 IF p_reason IS NULL OR p_reason NOT IN ('withdrawn','superseded')
 THEN RAISE EXCEPTION 'Invalid consent reason' USING ERRCODE='22023'; END IF;
 SELECT * INTO v FROM public.billing_consent_presentations WHERE presentation_id=p_presentation AND tenant_id=public.get_current_tenant();
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent presentation unavailable' USING ERRCODE='42501'; END IF;
 -- Exclusive reservation fence serializes accept/associate and B4 consumption.
 -- No upstream observation/advisory/customer locks are acquired here.
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=v.attempt_id FOR UPDATE;
 SELECT * INTO v FROM public.billing_consent_presentations WHERE presentation_id=p_presentation FOR UPDATE;
 u:=public.billing_consent_authorize();
 IF v.actor_id IS DISTINCT FROM u OR r.started_by_user_id IS DISTINCT FROM u
 OR r.tenant_id IS DISTINCT FROM v.tenant_id OR r.binding_id IS DISTINCT FROM v.binding_id
 OR r.approved_terms IS DISTINCT FROM v.approved_terms
 THEN RAISE EXCEPTION 'Consent reservation conflict' USING ERRCODE='22023'; END IF;
 IF r.state='confirmed' THEN
  RAISE EXCEPTION 'Post-confirmation subscription cancellation required' USING ERRCODE='55000'; END IF;
 IF r.state<>'pending' THEN RAISE EXCEPTION 'Pending reservation required' USING ERRCODE='22023'; END IF;
 SELECT * INTO i FROM public.billing_consent_invalidations WHERE presentation_id=v.presentation_id;
 IF FOUND THEN
  IF i.reason<>p_reason THEN RAISE EXCEPTION 'Invalidation replay conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(i);
 END IF;
 INSERT INTO public.billing_consent_invalidations(presentation_id,tenant_id,binding_id,attempt_id,actor_id,reason)
 VALUES(v.presentation_id,v.tenant_id,v.binding_id,v.attempt_id,v.actor_id,p_reason) RETURNING * INTO i;
 RETURN to_jsonb(i);
END $$;

CREATE FUNCTION public.billing_consent_read(p_attempt uuid,p_presentation uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts;v public.billing_consent_presentations;u uuid; BEGIN
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant() FOR SHARE;
 u:=public.billing_consent_authorize();
 IF r.attempt_id IS NULL OR r.started_by_user_id IS DISTINCT FROM u
 THEN RAISE EXCEPTION 'Owned reservation required' USING ERRCODE='42501'; END IF;
 SELECT * INTO v FROM public.billing_consent_presentations WHERE presentation_id=p_presentation
 AND attempt_id=r.attempt_id AND actor_id=u AND tenant_id=r.tenant_id AND binding_id=r.binding_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent presentation unavailable' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('presentation',to_jsonb(v)-'challenge_digest',
  'policy',(SELECT to_jsonb(p) FROM public.billing_consent_policy_versions p WHERE p.policy_id=v.policy_id),
  'acceptance',(SELECT to_jsonb(a) FROM public.billing_consent_acceptances a WHERE a.presentation_id=v.presentation_id),
  'invalidation',(SELECT to_jsonb(i) FROM public.billing_consent_invalidations i WHERE i.presentation_id=v.presentation_id),
  'database_now',clock_timestamp());
END $$;

GRANT SELECT ON public.billing_trial_attestations TO ceopro_consent_owner;
CREATE POLICY consent_attestation_fence_read ON public.billing_trial_attestations FOR SELECT TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_consent_consumption_fence() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE cid uuid;a public.billing_consent_acceptances; BEGIN
 IF NEW.tenant_id IS DISTINCT FROM public.get_current_tenant()
 THEN RAISE EXCEPTION 'Consent tenant unavailable' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='billing_trial_attestations' THEN cid:=NEW.consent_id;
 ELSE SELECT consent_id INTO cid FROM public.billing_trial_attestations WHERE attestation_id=NEW.attestation_id; END IF;
 SELECT * INTO a FROM public.billing_consent_acceptances WHERE acceptance_id=cid;
 -- Preserve pre-A1 trusted B4 evidence; no new writer for that authority exists.
 IF NOT FOUND THEN RETURN NEW; END IF;
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'Read committed consent required' USING ERRCODE='25001'; END IF;
 -- Attestation currently owns operation first. NOWAIT avoids inverting B4's
 -- reservation -> operation order. A busy fence requires a fresh retry.
 PERFORM 1 FROM public.billing_trial_checkouts WHERE attempt_id=a.attempt_id FOR SHARE NOWAIT;
 IF NOT FOUND OR EXISTS(SELECT FROM public.billing_consent_invalidations WHERE presentation_id=a.presentation_id)
 THEN RAISE EXCEPTION 'Consent invalidated' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_consent_read(uuid,uuid),public.billing_consent_consumption_fence() FROM PUBLIC;
-- Only the existing dormant NOLOGIN service gets the new scoped read command.
GRANT EXECUTE ON FUNCTION public.billing_consent_read(uuid,uuid) TO ceopro_consent_service;
GRANT CREATE ON SCHEMA public TO ceopro_consent_owner;
ALTER FUNCTION public.billing_consent_read(uuid,uuid) OWNER TO ceopro_consent_owner;
ALTER FUNCTION public.billing_consent_consumption_fence() OWNER TO ceopro_consent_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_consent_owner;
CREATE TRIGGER consent_consumption_fence BEFORE INSERT ON public.billing_trial_attestations
 FOR EACH ROW EXECUTE FUNCTION public.billing_consent_consumption_fence();
CREATE TRIGGER consent_consumption_fence BEFORE INSERT ON public.billing_trial_confirmations
 FOR EACH ROW EXECUTE FUNCTION public.billing_consent_consumption_fence();
