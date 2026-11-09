-- Dormant A1 evidence. No seeded policy, runtime membership or activation.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_consent_owner','ceopro_consent_service'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION',r);
  END IF;
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
   AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication)
   OR EXISTS(SELECT FROM pg_auth_members WHERE member=r::regrole)
   OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=r::regrole AND member<>current_user::regrole)
  THEN RAISE EXCEPTION 'Dormant consent role prerequisites required'; END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO ceopro_consent_owner,ceopro_consent_service;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid,uuid) TO ceopro_consent_owner;
-- Installation-only registry. No writer or approved text is supplied. Approval
-- requires a NEW immutable revision, never an in-place status/text change.
CREATE TABLE public.billing_consent_policy_versions (
 policy_id uuid PRIMARY KEY,agreement_reference text NOT NULL CHECK(length(btrim(agreement_reference)) BETWEEN 1 AND 255),
 agreement_revision text NOT NULL CHECK(length(btrim(agreement_revision)) BETWEEN 1 AND 128),
 language_tag text NOT NULL CHECK(length(btrim(language_tag)) BETWEEN 2 AND 35),
 status text NOT NULL CHECK(status IN ('pending','unsupported','approved')),
 agreement_digest text CHECK(agreement_digest ~ '^sha256:[0-9a-f]{64}$'),
 cancellation_reference text CHECK(length(btrim(cancellation_reference)) BETWEEN 1 AND 255),
 renewal_disclosure_reference text CHECK(length(btrim(renewal_disclosure_reference)) BETWEEN 1 AND 255),
 trial_start_rule_reference text CHECK(length(btrim(trial_start_rule_reference)) BETWEEN 1 AND 255),
 retention_policy_reference text CHECK(length(btrim(retention_policy_reference)) BETWEEN 1 AND 255),
 environment text CHECK(environment IN ('test','live')),eligible_interval_months integer[],
 presentation_ttl_seconds integer CHECK(presentation_ttl_seconds>0),
 approval_reference text CHECK(length(btrim(approval_reference)) BETWEEN 1 AND 255),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(agreement_reference,agreement_revision,language_tag),
 CHECK(status<>'approved' OR (agreement_digest IS NOT NULL AND cancellation_reference IS NOT NULL
  AND renewal_disclosure_reference IS NOT NULL AND trial_start_rule_reference IS NOT NULL
  AND retention_policy_reference IS NOT NULL AND environment IS NOT NULL AND approval_reference IS NOT NULL
  AND presentation_ttl_seconds IS NOT NULL AND cardinality(eligible_interval_months)>0
  AND array_position(eligible_interval_months,NULL) IS NULL AND 0<ALL(eligible_interval_months)) IS TRUE)
);
ALTER TABLE public.billing_trial_checkouts ADD CONSTRAINT consent_reservation_actor
 UNIQUE(attempt_id,tenant_id,binding_id,started_by_user_id);
CREATE TABLE public.billing_consent_presentations (
 presentation_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,binding_id text NOT NULL,attempt_id uuid NOT NULL,actor_id uuid NOT NULL,
 policy_id uuid NOT NULL REFERENCES public.billing_consent_policy_versions(policy_id),
 -- B2 fixed-plan reservations/B3 currently support quantity one only.
 quantity integer NOT NULL CHECK(quantity=1),
 approved_terms jsonb NOT NULL CHECK(jsonb_typeof(approved_terms)='object'),
 terms_digest text NOT NULL CHECK(terms_digest ~ '^sha256:[0-9a-f]{64}$'),
 status text NOT NULL CHECK(status IN ('pending_policy','unsupported','presented')),
 challenge_digest text UNIQUE CHECK(challenge_digest ~ '^sha256:[0-9a-f]{64}$'),created_at timestamptz NOT NULL,expires_at timestamptz,
 UNIQUE(presentation_id,tenant_id,binding_id,attempt_id,actor_id),
 CHECK((status='presented' AND challenge_digest IS NOT NULL AND expires_at>created_at) IS TRUE
  OR (status IN ('pending_policy','unsupported') AND challenge_digest IS NULL AND expires_at IS NULL)),
 FOREIGN KEY(attempt_id,tenant_id,binding_id,actor_id)
  REFERENCES public.billing_trial_checkouts(attempt_id,tenant_id,binding_id,started_by_user_id)
);
CREATE TABLE public.billing_consent_acceptances (
 acceptance_id uuid PRIMARY KEY,presentation_id uuid NOT NULL UNIQUE,tenant_id uuid NOT NULL,binding_id text NOT NULL,
 attempt_id uuid NOT NULL,actor_id uuid NOT NULL,accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(acceptance_id,tenant_id,binding_id,attempt_id,actor_id),
 FOREIGN KEY(presentation_id,tenant_id,binding_id,attempt_id,actor_id)
  REFERENCES public.billing_consent_presentations(presentation_id,tenant_id,binding_id,attempt_id,actor_id)
);
CREATE TABLE public.billing_consent_invalidations (
 presentation_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,binding_id text NOT NULL,attempt_id uuid NOT NULL,actor_id uuid NOT NULL,
 reason text NOT NULL CHECK(reason IN ('withdrawn','superseded')),recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(presentation_id,tenant_id,binding_id,attempt_id,actor_id)
  REFERENCES public.billing_consent_presentations(presentation_id,tenant_id,binding_id,attempt_id,actor_id)
);
CREATE TABLE public.billing_consent_associations (
 acceptance_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,binding_id text NOT NULL,attempt_id uuid NOT NULL UNIQUE,actor_id uuid NOT NULL,
 operation_id uuid NOT NULL UNIQUE,reference_id uuid NOT NULL,provider_customer_id text NOT NULL,
 customer_operation_id uuid NOT NULL,provider_checkout_id text NOT NULL,terms_digest text NOT NULL,
 associated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(acceptance_id,tenant_id,binding_id,attempt_id,actor_id)
  REFERENCES public.billing_consent_acceptances(acceptance_id,tenant_id,binding_id,attempt_id,actor_id),
 FOREIGN KEY(operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_operations(operation_id,tenant_id,binding_id),
 FOREIGN KEY(reference_id,tenant_id,binding_id,provider_customer_id)
  REFERENCES public.billing_customer_references(reference_id,tenant_id,binding_id,provider_customer_id),
 FOREIGN KEY(customer_operation_id,tenant_id,binding_id,reference_id,provider_customer_id)
  REFERENCES public.billing_customer_operations(operation_id,tenant_id,binding_id,reference_id,provider_customer_id),
 FOREIGN KEY(acceptance_id,operation_id,tenant_id,binding_id)
  REFERENCES public.billing_trial_consents(consent_id,operation_id,tenant_id,binding_id)
);
CREATE FUNCTION public.billing_consent_immutable() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Consent evidence is immutable' USING ERRCODE='22023'; END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_consent_policy_versions','billing_consent_presentations','billing_consent_acceptances',
 'billing_consent_invalidations','billing_consent_associations'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tab);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',tab);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting,ceopro_billing_observer,ceopro_trial_attestor,ceopro_trial_confirmer,ceopro_consent_service',tab);
  EXECUTE format('GRANT SELECT ON public.%I TO ceopro_consent_owner',tab);
  IF tab='billing_consent_policy_versions' THEN
   EXECUTE format('CREATE POLICY consent_policy_read ON public.%I FOR SELECT TO ceopro_consent_owner USING(true)',tab);
  ELSE
   EXECUTE format('GRANT INSERT ON public.%I TO ceopro_consent_owner',tab);
   EXECUTE format('CREATE POLICY consent_owner ON public.%I TO ceopro_consent_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',tab);
  END IF;
  EXECUTE format('CREATE TRIGGER consent_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.billing_consent_immutable()',tab);
 END LOOP;
END $$;
GRANT SELECT ON public.billing_trial_checkouts,public.billing_checkout_attempts,public.billing_gateway_bindings,
 public.billing_customer_references,public.billing_customer_operations,public.billing_observation_operations,public.tenant_users,
 public.billing_trial_consents TO ceopro_consent_owner;
GRANT INSERT ON public.billing_trial_consents TO ceopro_consent_owner;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_trial_checkouts','billing_checkout_attempts','billing_customer_operations',
 'billing_observation_operations','billing_trial_consents'] LOOP
  EXECUTE format('CREATE POLICY consent_read ON public.%I FOR SELECT TO ceopro_consent_owner USING(tenant_id=public.get_current_tenant())',tab);
 END LOOP;
END $$;
CREATE POLICY consent_binding_read ON public.billing_gateway_bindings FOR SELECT TO ceopro_consent_owner USING(true);
CREATE POLICY consent_b4_insert ON public.billing_trial_consents FOR INSERT TO ceopro_consent_owner
 WITH CHECK(tenant_id=public.get_current_tenant());
-- Column UPDATE supports row locking only; commands expose no such mutation.
GRANT UPDATE(attempt_id) ON public.billing_trial_checkouts TO ceopro_consent_owner;
CREATE POLICY consent_reservation_lock ON public.billing_trial_checkouts FOR UPDATE TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
GRANT UPDATE(presentation_id) ON public.billing_consent_presentations TO ceopro_consent_owner;
GRANT SELECT(user_id),UPDATE(user_id) ON public.users TO ceopro_consent_owner;
GRANT SELECT(tenant_id),UPDATE(tenant_id) ON public.companies TO ceopro_consent_owner;
GRANT UPDATE(user_id) ON public.tenant_users TO ceopro_consent_owner;
CREATE POLICY consent_identity_user ON public.users TO ceopro_consent_owner
 USING(user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY consent_identity_company ON public.companies TO ceopro_consent_owner
 USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid)
 WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY consent_identity_membership ON public.tenant_users TO ceopro_consent_owner
 USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE FUNCTION public.billing_consent_authorize() RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant();u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid; BEGIN
 IF session_user<>'ceopro_consent_service' OR t IS NULL OR u IS NULL
 THEN RAISE EXCEPTION 'Restricted consent principal required' USING ERRCODE='42501'; END IF;
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'Read committed consent required' USING ERRCODE='25001'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('keel_platform_authority',0))
 THEN RAISE EXCEPTION 'Authorization busy' USING ERRCODE='55P03'; END IF;
 PERFORM 1 FROM public.companies WHERE tenant_id=t FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent authorization revoked' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE user_id=u FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent authorization revoked' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.tenant_users WHERE tenant_id=t AND user_id=u FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent authorization revoked' USING ERRCODE='42501'; END IF;
 IF public.keel_active_principal(u,t) IS DISTINCT FROM true OR NOT EXISTS(SELECT FROM public.tenant_users
  WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'Consent authorization revoked' USING ERRCODE='42501'; END IF;
 RETURN u;
END $$;
CREATE FUNCTION public.billing_consent_present(p_id uuid,p_attempt uuid,p_policy uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts;a public.billing_checkout_attempts;p public.billing_consent_policy_versions;
 v public.billing_consent_presentations;u uuid;challenge text;n timestamptz;env text; BEGIN
 -- Reservation -> presentation -> nonblocking authority, compatible with B4.
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant() FOR SHARE;
 u:=public.billing_consent_authorize();
 IF r.attempt_id IS NULL OR r.started_by_user_id<>u OR r.state<>'pending'
 THEN RAISE EXCEPTION 'Owned pending reservation required' USING ERRCODE='42501'; END IF;
 SELECT * INTO a FROM public.billing_checkout_attempts WHERE attempt_id=r.attempt_id;
 IF a.first_submitted_at IS NOT NULL OR a.provider_session_id IS NOT NULL OR a.provider_params IS NOT NULL OR a.state<>'preparing'
 THEN RAISE EXCEPTION 'Pre-Checkout reservation required' USING ERRCODE='22023'; END IF;
 SELECT * INTO p FROM public.billing_consent_policy_versions WHERE policy_id=p_policy;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown consent policy revision' USING ERRCODE='22023'; END IF;
 SELECT environment INTO env FROM public.billing_gateway_bindings WHERE binding_id=r.binding_id;
 IF p.status='approved' AND (p.environment IS DISTINCT FROM env OR NOT r.interval_months=ANY(p.eligible_interval_months))
 THEN RAISE EXCEPTION 'Unsupported consent policy scope' USING ERRCODE='22023'; END IF;
 n:=clock_timestamp();
 IF p.status='approved' THEN challenge:=gen_random_uuid()::text||gen_random_uuid()::text; END IF;
 INSERT INTO public.billing_consent_presentations(presentation_id,tenant_id,binding_id,attempt_id,actor_id,policy_id,quantity,approved_terms,terms_digest,status,challenge_digest,created_at,expires_at)
 VALUES(p_id,r.tenant_id,r.binding_id,r.attempt_id,u,p_policy,1,r.approved_terms,'sha256:'||encode(sha256(convert_to(r.approved_terms::text,'UTF8')),'hex'),
  CASE p.status WHEN 'approved' THEN 'presented' WHEN 'pending' THEN 'pending_policy' ELSE 'unsupported' END,
  CASE WHEN challenge IS NOT NULL THEN 'sha256:'||encode(sha256(convert_to(challenge,'UTF8')),'hex') END,n,
  CASE WHEN challenge IS NOT NULL THEN n+make_interval(secs=>p.presentation_ttl_seconds) END) RETURNING * INTO v;
 RETURN (to_jsonb(v)-'challenge_digest')||jsonb_build_object('challenge',challenge,'policy',to_jsonb(p));
END $$;
CREATE FUNCTION public.billing_consent_locked(p_presentation uuid) RETURNS public.billing_consent_presentations
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
 RETURN v;
END $$;
CREATE FUNCTION public.billing_consent_accept(p_id uuid,p_presentation uuid,p_challenge text,p_terms_digest text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v public.billing_consent_presentations;a public.billing_consent_acceptances;c public.billing_checkout_attempts;n timestamptz; BEGIN
 v:=public.billing_consent_locked(p_presentation);n:=clock_timestamp();
 SELECT * INTO c FROM public.billing_checkout_attempts WHERE attempt_id=v.attempt_id;
 IF v.status<>'presented' OR v.expires_at<=n OR p_challenge IS NULL OR p_terms_digest IS DISTINCT FROM v.terms_digest
 OR v.challenge_digest IS DISTINCT FROM 'sha256:'||encode(sha256(convert_to(p_challenge,'UTF8')),'hex')
 OR EXISTS(SELECT FROM public.billing_consent_invalidations WHERE presentation_id=v.presentation_id)
 OR c.first_submitted_at IS NOT NULL OR c.provider_session_id IS NOT NULL OR c.provider_params IS NOT NULL OR c.state<>'preparing'
 THEN RAISE EXCEPTION 'Consent challenge expired or conflicting' USING ERRCODE='22023'; END IF;
 -- All challenge replays fail, including an identical lost-response retry.
 INSERT INTO public.billing_consent_acceptances(acceptance_id,presentation_id,tenant_id,binding_id,attempt_id,actor_id)
 VALUES(p_id,v.presentation_id,v.tenant_id,v.binding_id,v.attempt_id,v.actor_id) RETURNING * INTO a;
 RETURN to_jsonb(a);
END $$;
CREATE FUNCTION public.billing_consent_invalidate(p_presentation uuid,p_reason text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v public.billing_consent_presentations;i public.billing_consent_invalidations; BEGIN
 v:=public.billing_consent_locked(p_presentation);
 -- B4 does not consume withdrawals yet. Do not leave its consent usable.
 IF EXISTS(SELECT FROM public.billing_consent_associations WHERE attempt_id=v.attempt_id)
 THEN RAISE EXCEPTION 'Associated consent requires coordinated withdrawal cutover' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_consent_invalidations(presentation_id,tenant_id,binding_id,attempt_id,actor_id,reason)
 VALUES(v.presentation_id,v.tenant_id,v.binding_id,v.attempt_id,v.actor_id,p_reason) RETURNING * INTO i;
 RETURN to_jsonb(i);
END $$;
CREATE FUNCTION public.billing_consent_associate(p_acceptance uuid,p_operation uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.billing_consent_acceptances;v public.billing_consent_presentations;o public.billing_observation_operations;
 c public.billing_checkout_attempts;cop public.billing_customer_operations;p public.billing_consent_policy_versions;s public.billing_consent_associations; BEGIN
 SELECT * INTO a FROM public.billing_consent_acceptances WHERE acceptance_id=p_acceptance AND tenant_id=public.get_current_tenant();
 IF NOT FOUND THEN RAISE EXCEPTION 'Consent acceptance unavailable' USING ERRCODE='42501'; END IF;
 v:=public.billing_consent_locked(a.presentation_id);
 SELECT * INTO s FROM public.billing_consent_associations WHERE acceptance_id=p_acceptance;
 IF FOUND THEN
  IF s.operation_id IS DISTINCT FROM p_operation THEN RAISE EXCEPTION 'Consent association conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(s);
 END IF;
 IF EXISTS(SELECT FROM public.billing_consent_invalidations WHERE presentation_id=v.presentation_id)
 THEN RAISE EXCEPTION 'Consent invalidated' USING ERRCODE='22023'; END IF;
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=p_operation;
 SELECT * INTO c FROM public.billing_checkout_attempts WHERE attempt_id=v.attempt_id;
 SELECT * INTO cop FROM public.billing_customer_operations WHERE operation_id=o.customer_operation_id;
 IF o.operation_id IS NULL OR o.request_kind<>'trial_checkout' OR o.tenant_id IS DISTINCT FROM v.tenant_id
 OR o.binding_id IS DISTINCT FROM v.binding_id OR o.attempt_id IS DISTINCT FROM v.attempt_id OR o.initiated_by IS DISTINCT FROM v.actor_id
 OR o.terms_digest IS DISTINCT FROM v.terms_digest OR o.provider_checkout_id IS DISTINCT FROM c.provider_session_id
 OR c.gateway_binding_id IS DISTINCT FROM v.binding_id OR c.first_submitted_at IS NULL OR a.accepted_at>=c.first_submitted_at
 OR c.provider_session_id IS NULL OR cop.state IS DISTINCT FROM 'succeeded' OR cop.reference_id IS DISTINCT FROM o.reference_id
 OR cop.tenant_id IS DISTINCT FROM v.tenant_id OR cop.binding_id IS DISTINCT FROM v.binding_id
 OR cop.provider_customer_id IS DISTINCT FROM o.provider_customer_id
 THEN RAISE EXCEPTION 'Exact post-Checkout lineage required' USING ERRCODE='22023'; END IF;
 SELECT * INTO p FROM public.billing_consent_policy_versions WHERE policy_id=v.policy_id;
 INSERT INTO public.billing_trial_consents(consent_id,operation_id,tenant_id,binding_id,provider_customer_id,actor_id,
  agreement_reference,agreement_revision,accepted_at,provenance)
 VALUES(a.acceptance_id,o.operation_id,v.tenant_id,v.binding_id,o.provider_customer_id,v.actor_id,
  p.agreement_reference,p.agreement_revision,a.accepted_at,'A1 pre-Checkout acceptance '||a.acceptance_id::text);
 INSERT INTO public.billing_consent_associations(acceptance_id,tenant_id,binding_id,attempt_id,actor_id,operation_id,
  reference_id,provider_customer_id,customer_operation_id,provider_checkout_id,terms_digest)
 VALUES(a.acceptance_id,v.tenant_id,v.binding_id,v.attempt_id,v.actor_id,o.operation_id,o.reference_id,
  o.provider_customer_id,o.customer_operation_id,o.provider_checkout_id,v.terms_digest) RETURNING * INTO s;
 RETURN to_jsonb(s);
END $$;
-- Function ownership is separate from callable authority. No runtime receives either.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature,p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname LIKE 'billing_consent_%' LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
  IF f.proname IN ('billing_consent_present','billing_consent_accept','billing_consent_invalidate','billing_consent_associate') THEN
   EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO ceopro_consent_service',f.signature);
  END IF;
 END LOOP;
END $$;
GRANT CREATE ON SCHEMA public TO ceopro_consent_owner;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname LIKE 'billing_consent_%' LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO ceopro_consent_owner',f.signature);
 END LOOP;
END $$;
REVOKE CREATE ON SCHEMA public FROM ceopro_consent_owner;
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT roleid::regrole::text role,member::regrole::text member FROM pg_auth_members
 WHERE roleid IN ('ceopro_consent_owner'::regrole,'ceopro_consent_service'::regrole) AND grantor=current_user::regrole LOOP
  EXECUTE format('REVOKE %I FROM %I',r.role,r.member);
 END LOOP;
END $$;
