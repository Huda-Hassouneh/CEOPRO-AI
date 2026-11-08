-- Dormant B4. No LOGIN/membership/configuration/runtime entrypoint is enabled.
-- Consent has NO writer command. Installation alone cannot supply consent.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_confirmation_owner','ceopro_trial_attestor','ceopro_trial_confirmer'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION',r);
  END IF;
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication)
   OR EXISTS(SELECT FROM pg_auth_members WHERE member=r::regrole)
   OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=r::regrole AND member<>current_user::regrole)
  THEN RAISE EXCEPTION 'Dormant confirmation role prerequisites required'; END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO ceopro_confirmation_owner,ceopro_trial_attestor,ceopro_trial_confirmer;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid,uuid),public.billing_observation_evidence(jsonb),
 public.billing_observation_object(jsonb,text[]) TO ceopro_confirmation_owner;
GRANT SELECT ON public.tenant_users,public.billing_gateway_bindings,public.billing_customer_references,
 public.billing_customer_operations,public.billing_trial_checkouts,public.billing_checkout_attempts,
 public.billing_observation_operations,public.billing_verification_observations,public.usage_plans,
 public.billing_trials,public.billing_subscriptions,public.billing_customers,public.tenant_plan_assignments TO ceopro_confirmation_owner;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['tenant_users','billing_gateway_bindings','billing_customer_references','billing_customer_operations',
 'billing_trial_checkouts','billing_checkout_attempts','billing_observation_operations','billing_verification_observations',
 'billing_subscriptions','billing_customers','tenant_plan_assignments'] LOOP
  EXECUTE format('CREATE POLICY confirmation_read ON public.%I FOR SELECT TO ceopro_confirmation_owner USING(%s)',tab,
   CASE WHEN tab='billing_gateway_bindings' THEN 'true' ELSE 'tenant_id=public.get_current_tenant()' END);
 END LOOP;
END $$;
CREATE POLICY confirmation_trial_person ON public.billing_trials FOR SELECT TO ceopro_confirmation_owner
 USING(tenant_id=public.get_current_tenant() OR started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY confirmation_reservation_person ON public.billing_trial_checkouts FOR SELECT TO ceopro_confirmation_owner
 USING(started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);

-- Full digests and immutable evidence stay untouched. Only retrieval time is
-- non-material; trial/coverage/settlement dates and authority remain material.
CREATE FUNCTION public.billing_confirmation_semantic(p jsonb) RETURNS jsonb
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT p #- '{payment_method,observed_at}'::text[]
$$;
REVOKE ALL ON FUNCTION public.billing_confirmation_semantic(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_confirmation_semantic(jsonb) TO ceopro_observation_owner;

CREATE TABLE public.billing_trial_consents (
 consent_id uuid PRIMARY KEY,operation_id uuid NOT NULL,tenant_id uuid NOT NULL,binding_id text NOT NULL,
 provider_customer_id text NOT NULL,actor_id uuid NOT NULL REFERENCES public.users(user_id),
 agreement_reference text NOT NULL CHECK(length(agreement_reference) BETWEEN 1 AND 255),
 agreement_revision text NOT NULL CHECK(length(agreement_revision) BETWEEN 1 AND 128),
 accepted_at timestamptz NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 provenance text NOT NULL CHECK(length(provenance) BETWEEN 1 AND 255),
 UNIQUE(consent_id,operation_id,tenant_id,binding_id),
 FOREIGN KEY(operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_operations(operation_id,tenant_id,binding_id)
);
CREATE TABLE public.billing_trial_attestations (
 attestation_id uuid PRIMARY KEY,operation_id uuid NOT NULL,tenant_id uuid NOT NULL,binding_id text NOT NULL,
 consent_id uuid NOT NULL,observation_id uuid NOT NULL,claim_version bigint NOT NULL,claim_token uuid NOT NULL,
 request jsonb NOT NULL,evidence jsonb NOT NULL,history_digest text NOT NULL,
 observed_at timestamptz NOT NULL,checkout_completed_at timestamptz NOT NULL,checkout_expires_at timestamptz NOT NULL,
 attested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(attestation_id,tenant_id,binding_id),
 FOREIGN KEY(operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_operations(operation_id,tenant_id,binding_id),
 FOREIGN KEY(observation_id,operation_id,tenant_id,binding_id) REFERENCES public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id),
 FOREIGN KEY(consent_id,operation_id,tenant_id,binding_id) REFERENCES public.billing_trial_consents(consent_id,operation_id,tenant_id,binding_id)
);
CREATE TABLE public.billing_trial_confirmations (
 confirmation_id uuid PRIMARY KEY,tenant_id uuid NOT NULL UNIQUE,binding_id text NOT NULL,
 attempt_id uuid NOT NULL UNIQUE,attestation_id uuid NOT NULL UNIQUE,
 provider_customer_id text NOT NULL,provider_subscription_id text NOT NULL,
 subscription_id uuid NOT NULL UNIQUE REFERENCES public.billing_subscriptions(subscription_id),
 started_by_user_id uuid NOT NULL REFERENCES public.users(user_id),
 trial_started_at timestamptz NOT NULL,trial_ends_at timestamptz NOT NULL,
 confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(binding_id,provider_subscription_id),UNIQUE(confirmation_id,tenant_id),
 FOREIGN KEY(attestation_id,tenant_id,binding_id) REFERENCES public.billing_trial_attestations(attestation_id,tenant_id,binding_id),
 FOREIGN KEY(attempt_id,tenant_id,binding_id) REFERENCES public.billing_trial_checkouts(attempt_id,tenant_id,binding_id)
);
CREATE FUNCTION public.billing_confirmation_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Confirmation provenance is immutable' USING ERRCODE='22023';
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_trial_consents','billing_trial_attestations','billing_trial_confirmations'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tab);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',tab);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting,ceopro_billing_observer,ceopro_trial_attestor,ceopro_trial_confirmer',tab);
  EXECUTE format('GRANT SELECT ON public.%I TO ceopro_confirmation_owner',tab);
  EXECUTE format('CREATE POLICY confirmation_owner ON public.%I TO ceopro_confirmation_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',tab);
  EXECUTE format('CREATE TRIGGER confirmation_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_immutable()',tab);
 END LOOP;
END $$;
GRANT INSERT ON public.billing_trial_attestations,public.billing_trial_confirmations TO ceopro_confirmation_owner;
-- No INSERT grant on consents, including to the function owner. Synthetic
-- consent is seeded only by the disposable test installer, never a runtime role.

CREATE FUNCTION public.billing_confirmation_principal(p_role text) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant();u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid; BEGIN
 IF session_user<>p_role OR public.keel_active_principal(u,t) IS DISTINCT FROM true
 OR NOT EXISTS(SELECT FROM public.tenant_users WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'Restricted confirmation principal required' USING ERRCODE='42501'; END IF;RETURN u;
END $$;
-- Lock privileges belong only to the inaccessible function owner. No command
-- exposes an UPDATE of these columns. Raw principal keys keep lock visibility
-- independent of a concurrently revoked active-principal predicate.
GRANT SELECT(user_id),UPDATE(user_id) ON public.users TO ceopro_confirmation_owner;
GRANT SELECT(tenant_id),UPDATE(tenant_id) ON public.companies TO ceopro_confirmation_owner;
GRANT UPDATE(user_id) ON public.tenant_users TO ceopro_confirmation_owner;
CREATE POLICY confirmation_identity_user ON public.users TO ceopro_confirmation_owner
 USING(user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY confirmation_identity_company ON public.companies TO ceopro_confirmation_owner
 USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid)
 WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid);
CREATE POLICY confirmation_identity_membership ON public.tenant_users TO ceopro_confirmation_owner
 USING(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid
 AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=nullif(current_setting('app.current_tenant_id',true),'')::uuid
 AND user_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE FUNCTION public.billing_confirmation_authorize(t uuid,u uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF session_user<>'ceopro_trial_confirmer' OR t IS NULL OR u IS NULL
 OR t IS DISTINCT FROM nullif(current_setting('app.current_tenant_id',true),'')::uuid
 OR u IS DISTINCT FROM nullif(current_setting('app.current_user_id',true),'')::uuid
 THEN RAISE EXCEPTION 'Restricted confirmation principal required' USING ERRCODE='42501'; END IF;
 -- Fresh command snapshots are required, including conditional platform state.
 IF current_setting('transaction_isolation')<>'read committed'
 THEN RAISE EXCEPTION 'Read committed confirmation required' USING ERRCODE='25001'; END IF;
 -- Platform status commands take this BEFORE billing-tenant; TRY is essential.
 -- It also stabilizes platform membership/workspace without platform DML grants.
 IF NOT pg_try_advisory_xact_lock(hashtextextended('keel_platform_authority',0))
 THEN RAISE EXCEPTION 'Authorization busy; fresh reconciliation required' USING ERRCODE='55P03'; END IF;
 -- SHARE conflicts with non-key role/status UPDATE and DELETE (KEY SHARE does
 -- not). Never wait on reverse invitation/user/membership lock dependencies.
 PERFORM 1 FROM public.companies WHERE tenant_id=t FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Confirmation authorization revoked' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.users WHERE user_id=u FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Confirmation authorization revoked' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.tenant_users WHERE tenant_id=t AND user_id=u FOR SHARE NOWAIT;
 IF NOT FOUND THEN RAISE EXCEPTION 'Confirmation authorization revoked' USING ERRCODE='42501'; END IF;
 -- All permission inputs are now stable until COMMIT, not just until SELECT.
 IF public.keel_active_principal(u,t) IS DISTINCT FROM true OR NOT EXISTS(
  SELECT FROM public.tenant_users WHERE tenant_id=t AND user_id=u
  AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'Confirmation authorization revoked' USING ERRCODE='42501'; END IF;
END $$;
CREATE FUNCTION public.billing_confirmation_history(p_operation uuid) RETURNS text LANGUAGE sql STABLE
 SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT 'sha256:'||encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array(observation_id,evidence_digest,outcome) ORDER BY observation_id),'[]'::jsonb)::text,'UTF8')),'hex')
 FROM public.billing_verification_observations WHERE operation_id=p_operation
$$;

CREATE FUNCTION public.billing_confirmation_attest(p_id uuid,p_operation uuid,p_version bigint,p_token uuid,p_consent uuid,
 p_request jsonb,p_evidence jsonb,p_observed timestamptz,p_completed timestamptz,p_expires timestamptz) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.billing_observation_operations;v public.billing_verification_observations;r public.billing_trial_checkouts;
 c public.billing_trial_consents;a public.billing_trial_attestations;u uuid;n timestamptz;clean jsonb;baseline jsonb;cap text; BEGIN
 u:=public.billing_confirmation_principal('ceopro_trial_attestor');
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=p_operation FOR UPDATE;n:=clock_timestamp();
 IF NOT FOUND OR p_version IS NULL OR p_token IS NULL OR o.version<>p_version OR o.claim_token IS DISTINCT FROM p_token OR o.claim_until<=n
 OR p_request IS DISTINCT FROM o.request OR o.request_kind<>'trial_checkout'
 THEN RAISE EXCEPTION 'Original live observation claim required' USING ERRCODE='55000'; END IF;
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=o.attempt_id;
 SELECT * INTO v FROM public.billing_verification_observations WHERE observation_id=o.last_observation_id;
 SELECT * INTO c FROM public.billing_trial_consents WHERE consent_id=p_consent AND operation_id=o.operation_id;
 IF o.customer_operation_id IS NULL OR NOT EXISTS(SELECT FROM public.billing_customer_operations co WHERE co.operation_id=o.customer_operation_id
  AND co.tenant_id=o.tenant_id AND co.binding_id=o.binding_id AND co.reference_id=o.reference_id AND co.provider_customer_id=o.provider_customer_id AND co.state='succeeded')
 OR v.observation_id IS NULL OR v.source<>'authoritative_lookup' OR v.outcome NOT IN ('pending','verified')
 OR coalesce(v.evidence#>>'{recurring_authority,consent}','unknown') NOT IN ('unknown','pending')
 OR v.observed_at<n-interval '5 minutes' OR p_observed IS NULL OR p_observed<n-interval '5 minutes' OR p_observed>n+interval '30 seconds'
 OR c.consent_id IS NULL OR c.actor_id<>r.started_by_user_id OR c.provider_customer_id<>o.provider_customer_id
 OR r.state<>'pending' OR p_completed IS NULL OR p_expires IS NULL OR p_completed>n OR p_completed>p_expires OR p_expires<=n
 THEN RAISE EXCEPTION 'Fresh trusted provenance and consent required' USING ERRCODE='22023'; END IF;
 -- Only explicit trusted local consent differs from the provider-only B3 read.
 clean:=p_evidence #- '{recurring_authority,consent_reference}'::text[] #- '{recurring_authority,consent_terms_revision}'::text[];
 clean:=jsonb_set(clean,'{recurring_authority,consent}','"unknown"'::jsonb);
 baseline:=v.evidence #- '{recurring_authority,consent_reference}'::text[] #- '{recurring_authority,consent_terms_revision}'::text[];
 baseline:=jsonb_set(baseline,'{recurring_authority,consent}','"unknown"'::jsonb);
 PERFORM public.billing_observation_evidence(clean);
 IF public.billing_confirmation_semantic(clean) IS DISTINCT FROM public.billing_confirmation_semantic(baseline)
 OR EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=o.operation_id AND
  (h.outcome='conflict' OR public.billing_confirmation_semantic(h.evidence) IS DISTINCT FROM public.billing_confirmation_semantic(v.evidence)))
 THEN RAISE EXCEPTION 'Unresolved material evidence conflict' USING ERRCODE='22023'; END IF;
 IF p_evidence->>'customer' IS DISTINCT FROM o.provider_customer_id OR p_evidence->>'checkout' IS DISTINCT FROM o.provider_checkout_id
 OR nullif(p_evidence->>'subscription','') IS NULL OR (o.provider_subscription_id IS NOT NULL AND p_evidence->>'subscription'<>o.provider_subscription_id)
 OR p_evidence->>'checkout_state' IS DISTINCT FROM 'complete' OR p_evidence->>'subscription_state' IS DISTINCT FROM 'trialing'
 OR p_evidence->>'cancel_at_period_end' IS DISTINCT FROM 'false' OR p_evidence->>'cancelled_at' IS NOT NULL
 OR p_evidence#>>'{recurring_authority,readiness}' IS DISTINCT FROM 'reusable_authority_confirmed'
 OR coalesce(p_evidence#>>'{recurring_authority,kind}','unknown') NOT IN ('payment_method_setup','mandate','provider_agreement')
 OR nullif(p_evidence#>>'{recurring_authority,source}','') IS NULL
 OR p_evidence#>>'{recurring_authority,consent}' IS DISTINCT FROM 'recorded'
 OR p_evidence#>>'{recurring_authority,consent_reference}' IS DISTINCT FROM c.agreement_reference
 OR p_evidence#>>'{recurring_authority,consent_terms_revision}' IS DISTINCT FROM c.agreement_revision
 OR (p_evidence->>'payment_method' IS NOT NULL AND p_evidence#>>'{payment_method,readiness}' IS DISTINCT FROM 'reusable_authority_confirmed')
 THEN RAISE EXCEPTION 'Complete recurring authority required' USING ERRCODE='22023'; END IF;
 FOREACH cap IN ARRAY ARRAY['hosted_checkout','reusable_payment_method','setup_without_charge','off_session_recurring','trial_subscription_setup','authenticated_webhooks','authoritative_reconciliation','idempotent_submission','cancellation'] LOOP
  IF p_evidence#>>ARRAY['capabilities',cap] IS DISTINCT FROM 'supported' THEN RAISE EXCEPTION 'Required capability unavailable' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF (p_evidence#>>'{terms,amount}')::numeric IS DISTINCT FROM r.approved_amount
 OR (p_evidence#>>'{terms,currency}') IS DISTINCT FROM r.currency
 OR (p_evidence#>>'{terms,interval_months}')::int IS DISTINCT FROM r.interval_months
 OR (p_evidence#>>'{terms,quantity}')::int IS DISTINCT FROM 1
 OR p_evidence#>>'{terms,price}' IS DISTINCT FROM r.provider_price_id
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz IS NULL OR (p_evidence#>>'{trial,started_at}')::timestamptz IS NULL
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz-(p_evidence#>>'{trial,started_at}')::timestamptz<>make_interval(days=>r.trial_duration_days)
 OR (p_evidence#>>'{trial,cutoff}')::timestamptz IS DISTINCT FROM (p_evidence#>>'{trial,ends_at}')::timestamptz
 OR (p_evidence#>>'{trial,started_at}')::timestamptz<r.created_at-interval '30 seconds'
 OR (p_evidence#>>'{trial,started_at}')::timestamptz>p_observed
 OR (p_evidence#>>'{trial,started_at}')::timestamptz>p_completed
 OR c.accepted_at>(p_evidence#>>'{trial,started_at}')::timestamptz
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz<=n
 THEN RAISE EXCEPTION 'Frozen commercial and trial terms required' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM public.billing_trial_attestations WHERE attestation_id=p_id;
 IF FOUND THEN
  IF (a.operation_id,a.claim_version,a.claim_token,a.consent_id,a.request,a.evidence,a.observed_at,a.checkout_completed_at,a.checkout_expires_at)
   IS DISTINCT FROM (p_operation,p_version,p_token,p_consent,p_request,p_evidence,p_observed,p_completed,p_expires)
  THEN RAISE EXCEPTION 'Attestation replay conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(a);
 END IF;
 INSERT INTO public.billing_trial_attestations(attestation_id,operation_id,tenant_id,binding_id,consent_id,observation_id,claim_version,claim_token,
 request,evidence,history_digest,observed_at,checkout_completed_at,checkout_expires_at)
 VALUES(p_id,p_operation,o.tenant_id,o.binding_id,p_consent,v.observation_id,p_version,p_token,p_request,p_evidence,
 public.billing_confirmation_history(p_operation),p_observed,p_completed,p_expires) RETURNING * INTO a;RETURN to_jsonb(a);
END $$;

-- Terminal reservation state; legacy issuance and pending/released operations
-- are preserved. Only the new restricted owner can make the new transition.
ALTER TABLE public.billing_trial_checkouts ADD COLUMN confirmation_id uuid;
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT conname FROM pg_constraint WHERE conrelid='public.billing_trial_checkouts'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%state%' LOOP
  EXECUTE format('ALTER TABLE public.billing_trial_checkouts DROP CONSTRAINT %I',r.conname);
 END LOOP;
END $$;
ALTER TABLE public.billing_trial_checkouts ADD CHECK(
 (state='pending' AND released_at IS NULL AND release_reason IS NULL AND confirmation_id IS NULL)
 OR (state='released' AND released_at IS NOT NULL AND release_reason='unsubmitted' AND confirmation_id IS NULL)
 OR (state='confirmed' AND released_at IS NULL AND release_reason IS NULL AND confirmation_id IS NOT NULL));
ALTER TABLE public.billing_trial_checkouts ADD FOREIGN KEY(confirmation_id,tenant_id) REFERENCES public.billing_trial_confirmations(confirmation_id,tenant_id);
CREATE FUNCTION public.billing_confirmation_reservation_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF OLD.state='confirmed' OR ((NEW.state='confirmed' OR NEW.confirmation_id IS DISTINCT FROM OLD.confirmation_id)
  AND (current_user<>'ceopro_confirmation_owner' OR OLD.state<>'pending' OR NEW.state<>'confirmed' OR NEW.confirmation_id IS NULL))
 THEN RAISE EXCEPTION 'Terminal restricted confirmation required' USING ERRCODE='22023'; END IF;RETURN NEW;
END $$;
CREATE TRIGGER zz_confirmation_reservation_guard BEFORE UPDATE ON public.billing_trial_checkouts
 FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_reservation_guard();
ALTER TABLE public.tenant_plan_assignments ADD COLUMN trial_confirmation_id uuid;
ALTER TABLE public.tenant_plan_assignments ADD FOREIGN KEY(trial_confirmation_id,tenant_id) REFERENCES public.billing_trial_confirmations(confirmation_id,tenant_id);
GRANT INSERT(tenant_id,plan_key,started_at,ends_at,started_by_user_id) ON public.billing_trials TO ceopro_confirmation_owner;
GRANT INSERT(subscription_id,tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,plan_key,period_code,status,
 current_period_start,current_period_end,trial_end,cancel_at_period_end,last_event_at) ON public.billing_subscriptions TO ceopro_confirmation_owner;
GRANT INSERT(tenant_id,stripe_customer_id) ON public.billing_customers TO ceopro_confirmation_owner;
GRANT UPDATE(stripe_customer_id) ON public.billing_customers TO ceopro_confirmation_owner;
CREATE POLICY confirmation_customer_lock ON public.billing_customers FOR UPDATE TO ceopro_confirmation_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
GRANT INSERT(tenant_id,plan_key,status,current_period_start,current_period_end,period_code,source,trial_confirmation_id)
 ON public.tenant_plan_assignments TO ceopro_confirmation_owner;
GRANT UPDATE(state,confirmation_id) ON public.billing_trial_checkouts TO ceopro_confirmation_owner;
-- Required solely to lock immutable operation rows (no UPDATE command is exposed).
GRANT UPDATE(operation_id) ON public.billing_observation_operations TO ceopro_confirmation_owner;
CREATE POLICY confirmation_operation_lock ON public.billing_observation_operations FOR UPDATE TO ceopro_confirmation_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE POLICY confirmation_reservation_update ON public.billing_trial_checkouts FOR UPDATE TO ceopro_confirmation_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_trials','billing_subscriptions','billing_customers','tenant_plan_assignments'] LOOP
  EXECUTE format('CREATE POLICY confirmation_insert ON public.%I FOR INSERT TO ceopro_confirmation_owner WITH CHECK(tenant_id=public.get_current_tenant())',tab);
 END LOOP;
END $$;

CREATE FUNCTION public.billing_confirmation_snapshot() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c public.billing_trial_confirmations;r public.billing_trial_checkouts; BEGIN
 IF NEW.trial_confirmation_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE confirmation_id=NEW.trial_confirmation_id AND tenant_id=NEW.tenant_id;
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=c.attempt_id;
 IF TG_OP='UPDATE' AND NEW.plan_key<>r.plan_key AND NEW.trial_confirmation_id=OLD.trial_confirmation_id THEN
  NEW.trial_confirmation_id:=NULL;RETURN NEW; -- normal later plan change retains legacy catalog behavior
 END IF;
 IF c.confirmation_id IS NULL OR NEW.plan_key IS DISTINCT FROM r.plan_key
 THEN RAISE EXCEPTION 'Protected frozen assignment association required' USING ERRCODE='22023'; END IF;
 NEW.catalog_snapshot:=jsonb_build_object('plan_key',r.plan_key,'display_name',r.plan_key,
  'catalog_version',r.approved_terms->'entitlement_version','commercial_catalog_version',r.approved_terms->'catalog_version',
  'catalog_revision_id',r.catalog_revision_id,'features',r.approved_terms->'features','entitlements',r.approved_terms->'entitlements',
  'approved_commercial_terms',r.approved_terms);
 RETURN NEW;
END $$;
CREATE TRIGGER zz_trial_confirmation_snapshot BEFORE INSERT OR UPDATE OF plan_key,catalog_snapshot,trial_confirmation_id ON public.tenant_plan_assignments
 FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_snapshot();

CREATE FUNCTION public.billing_confirmation_apply(p_attestation uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.billing_trial_attestations;o public.billing_observation_operations;r public.billing_trial_checkouts;
 c public.billing_trial_confirmations;b public.billing_gateway_bindings;u uuid;t uuid:=public.get_current_tenant();
 n timestamptz;sub uuid:=gen_random_uuid();start_at timestamptz;end_at timestamptz; BEGIN
 u:=public.billing_confirmation_principal('ceopro_trial_confirmer');
 SELECT * INTO a FROM public.billing_trial_attestations WHERE attestation_id=p_attestation;
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=(a.request->>'attempt_id')::uuid;
 IF a.attestation_id IS NULL OR r.attempt_id IS NULL OR r.started_by_user_id<>u THEN RAISE EXCEPTION 'Owned trusted attestation required' USING ERRCODE='42501'; END IF;
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE attempt_id=r.attempt_id;
 IF FOUND THEN
  IF c.attestation_id<>p_attestation THEN RAISE EXCEPTION 'Confirmation replay conflict' USING ERRCODE='22023'; END IF;
  PERFORM public.billing_confirmation_authorize(t,u);
  RETURN to_jsonb(c); -- immutable history, never reissues rights
 END IF;
 SELECT * INTO b FROM public.billing_gateway_bindings WHERE binding_id=a.binding_id;
 IF b.provider<>'stripe' OR b.environment<>'test' THEN RAISE EXCEPTION 'Lifecycle provider/environment not enabled' USING ERRCODE='22023'; END IF;
 -- Legacy Checkout webhook writes the customer BEFORE its subscription lock.
 -- Match that row-lock edge: person -> trial tenant -> customer -> TRY subscription
 -- -> billing tenant -> reservation -> operation. Subscription-only webhooks can
 -- take subscription before a missing customer; never wait at that reverse edge.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 INSERT INTO public.billing_customers(tenant_id,stripe_customer_id) VALUES(t,a.request->>'customer') ON CONFLICT DO NOTHING;
 PERFORM 1 FROM public.billing_customers WHERE tenant_id=t AND stripe_customer_id=a.request->>'customer' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Historical customer provenance conflict' USING ERRCODE='22023'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('keel_stripe_subscription:'||(a.evidence->>'subscription'),0))
 THEN RAISE EXCEPTION 'Provider subscription busy; fresh reconciliation required' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||t::text,0));
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=r.attempt_id FOR UPDATE;
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=a.operation_id FOR UPDATE;n:=clock_timestamp();
 -- Decisive authorization follows blocking legacy locks. Acquiring authority
 -- rows before those locks would invert platform suspension/invitation order.
 -- The new edges are TRY/NOWAIT; no authorization wait cycle is introduced.
 PERFORM public.billing_confirmation_authorize(t,u);
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE attempt_id=r.attempt_id;
 IF FOUND THEN
  IF c.attestation_id<>p_attestation OR c.binding_id<>a.binding_id OR c.provider_subscription_id IS DISTINCT FROM a.evidence->>'subscription'
  THEN RAISE EXCEPTION 'Confirmation replay conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(c);
 END IF;
 IF r.state<>'pending' OR a.request IS DISTINCT FROM o.request OR a.binding_id<>r.binding_id
 OR o.version<>a.claim_version OR o.claim_token IS DISTINCT FROM a.claim_token OR o.claim_until<=n
 OR o.last_observation_id<>a.observation_id OR public.billing_confirmation_history(o.operation_id)<>a.history_digest
 OR a.observed_at<n-interval '5 minutes' OR a.checkout_expires_at<=n
 THEN RAISE EXCEPTION 'Confirmation evidence stale or conflicting' USING ERRCODE='55000'; END IF;
 start_at:=(a.evidence#>>'{trial,started_at}')::timestamptz;end_at:=(a.evidence#>>'{trial,ends_at}')::timestamptz;
 IF end_at<=n OR EXISTS(SELECT FROM public.billing_trials WHERE tenant_id=t OR started_by_user_id=u)
 OR EXISTS(SELECT FROM public.tenant_plan_assignments WHERE tenant_id=t)
 OR EXISTS(SELECT FROM public.billing_subscriptions WHERE tenant_id=t)
 OR NOT EXISTS(SELECT FROM public.usage_plans WHERE plan_key=r.plan_key AND is_active AND self_serve AND trial_days=r.trial_duration_days)
 OR EXISTS(SELECT FROM public.billing_trial_checkouts WHERE attempt_id<>r.attempt_id AND state='pending' AND (tenant_id=t OR started_by_user_id=u))
 THEN RAISE EXCEPTION 'Trial eligibility unavailable' USING ERRCODE='22023'; END IF;
 -- Legacy columns carry ONLY genuine Stripe IDs. Conflicting historical
 -- mappings are never adopted/replaced. Other providers fail closed above.
 IF NOT EXISTS(SELECT FROM public.billing_customers WHERE tenant_id=t AND stripe_customer_id=o.provider_customer_id)
 THEN RAISE EXCEPTION 'Historical customer provenance conflict' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_subscriptions(subscription_id,tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,
 plan_key,period_code,status,current_period_start,current_period_end,trial_end,cancel_at_period_end,last_event_at)
 VALUES(sub,t,a.evidence->>'subscription',o.provider_customer_id,r.provider_price_id,r.plan_key,r.period_code,'trialing',start_at,end_at,end_at,false,a.observed_at);
 INSERT INTO public.billing_trial_confirmations(confirmation_id,tenant_id,binding_id,attempt_id,attestation_id,provider_customer_id,
 provider_subscription_id,subscription_id,started_by_user_id,trial_started_at,trial_ends_at)
 VALUES(p_attestation,t,r.binding_id,r.attempt_id,p_attestation,o.provider_customer_id,a.evidence->>'subscription',sub,u,start_at,end_at) RETURNING * INTO c;
 INSERT INTO public.billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(t,r.plan_key,start_at,end_at,u);
 INSERT INTO public.tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,period_code,source,trial_confirmation_id)
 VALUES(t,r.plan_key,'trialing',(start_at AT TIME ZONE 'UTC')::date,(end_at AT TIME ZONE 'UTC')::date,r.period_code,'stripe',c.confirmation_id);
 UPDATE public.billing_trial_checkouts SET state='confirmed',confirmation_id=c.confirmation_id WHERE attempt_id=r.attempt_id;
 PERFORM public.billing_trial_confirmation_close_checkout(c.confirmation_id);
 RETURN to_jsonb(c);
END $$;

-- Consume the bound Checkout without widening the old scope-guard authority.
-- Its existing issuer remains the only writer of bound Checkout state.
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT conname FROM pg_constraint WHERE conrelid='public.billing_checkout_attempts'::regclass AND contype='c'
 AND pg_get_constraintdef(oid) LIKE '%state%' LOOP
  EXECUTE format('ALTER TABLE public.billing_checkout_attempts DROP CONSTRAINT %I',r.conname);
 END LOOP;
END $$;
ALTER TABLE public.billing_checkout_attempts ADD CHECK(state IN ('preparing','open','expired','confirmed'));
CREATE FUNCTION public.billing_confirmation_attempt_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF OLD.state='confirmed' OR (NEW.state='confirmed' AND (session_user<>'ceopro_trial_confirmer' OR NOT EXISTS(
  SELECT FROM public.billing_trial_confirmations c WHERE c.attempt_id=NEW.attempt_id AND c.tenant_id=NEW.tenant_id AND c.binding_id=NEW.gateway_binding_id)))
 THEN RAISE EXCEPTION 'Terminal confirmed Checkout required' USING ERRCODE='22023'; END IF;RETURN NEW;
END $$;
CREATE TRIGGER zz_confirmation_attempt_guard BEFORE UPDATE ON public.billing_checkout_attempts
 FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_attempt_guard();
GRANT SELECT ON public.billing_trial_confirmations TO ceopro_trial_issuer;
CREATE POLICY confirmation_issuer_read ON public.billing_trial_confirmations FOR SELECT TO ceopro_trial_issuer USING(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_trial_confirmation_close_checkout(p_id uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE c public.billing_trial_confirmations;u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid; BEGIN
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE confirmation_id=p_id;
 IF session_user<>'ceopro_trial_confirmer' OR c.confirmation_id IS NULL OR c.started_by_user_id IS DISTINCT FROM u
 OR public.keel_active_principal(u,c.tenant_id) IS DISTINCT FROM true
 THEN RAISE EXCEPTION 'Restricted confirmed Checkout required' USING ERRCODE='42501'; END IF;
 UPDATE public.billing_checkout_attempts SET state='confirmed',updated_at=clock_timestamp()
 WHERE attempt_id=c.attempt_id AND tenant_id=c.tenant_id AND gateway_binding_id=c.binding_id AND state IN ('preparing','open');
 IF NOT FOUND THEN RAISE EXCEPTION 'Checkout is no longer confirmable' USING ERRCODE='22023'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.billing_trial_confirmation_close_checkout(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_trial_confirmation_close_checkout(uuid) TO ceopro_confirmation_owner;
GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_trial_confirmation_close_checkout(uuid) OWNER TO ceopro_trial_issuer;
REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer;

-- Withhold every new activation capability from ALL existing identities.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature,p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname LIKE 'billing_confirmation_%' LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
  IF f.proname='billing_confirmation_attest' THEN EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO ceopro_trial_attestor',f.signature); END IF;
  IF f.proname='billing_confirmation_apply' THEN EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO ceopro_trial_confirmer',f.signature); END IF;
 END LOOP;
END $$;
GRANT CREATE ON SCHEMA public TO ceopro_confirmation_owner;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.proname LIKE 'billing_confirmation_%' LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO ceopro_confirmation_owner',f.signature);
 END LOOP;
END $$;
REVOKE CREATE ON SCHEMA public FROM ceopro_confirmation_owner;
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT roleid::regrole::text AS role,member::regrole::text AS member FROM pg_auth_members
 WHERE roleid IN ('ceopro_confirmation_owner'::regrole,'ceopro_trial_attestor'::regrole,'ceopro_trial_confirmer'::regrole) AND grantor=current_user::regrole LOOP
  EXECUTE format('REVOKE %I FROM %I',r.role,r.member);
 END LOOP;
END $$;

-- Same B3 authority/fencing/immutability; timestamp-only changes are not new conflicts.
CREATE OR REPLACE FUNCTION public.billing_observation_record(p_id uuid,p_version bigint,p_token uuid,p_observation uuid,p_source text,p_receipt uuid,
 p_reference text,p_observed timestamptz,p_adapter text,p_api text,p_outcome text,p_evidence jsonb,p_request jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_observation_operations;o public.billing_verification_observations;old public.billing_verification_observations;e public.billing_observation_receipts;
 n timestamptz;d text;conflict boolean; BEGIN
 PERFORM public.billing_observation_principal();PERFORM public.billing_observation_evidence(p_evidence);
 d:='sha256:'||encode(sha256(convert_to(p_evidence::text,'UTF8')),'hex');
 SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_id FOR UPDATE;n:=clock_timestamp();
 IF NOT FOUND THEN RAISE EXCEPTION 'Observation unavailable' USING ERRCODE='22023'; END IF;
 IF p_request IS DISTINCT FROM r.request THEN RAISE EXCEPTION 'Original observation request scope required' USING ERRCODE='22023'; END IF;
 SELECT * INTO o FROM public.billing_verification_observations WHERE observation_id=p_observation;
 IF FOUND THEN
  IF (o.operation_id,o.claim_version,o.claim_token,o.source,o.receipt_id,o.provenance_reference,o.observed_at,o.adapter_version,o.api_version,o.outcome,o.evidence)
   IS DISTINCT FROM (p_id,p_version,p_token,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence)
  THEN RAISE EXCEPTION 'Observation identity replay conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(o);
 END IF;
 IF p_version IS NULL OR r.version<>p_version OR p_token IS NULL OR r.claim_token IS DISTINCT FROM p_token OR r.claim_until<=n
 THEN RAISE EXCEPTION 'Observation execution stale' USING ERRCODE='55000'; END IF;
 IF p_observed IS NULL OR p_observed<n-interval '5 minutes' OR p_observed>n+interval '30 seconds' OR p_outcome NOT IN ('verified','pending','conflict','unavailable','unsupported') OR p_outcome IS NULL
 THEN RAISE EXCEPTION 'Observation freshness or outcome unavailable' USING ERRCODE='22023'; END IF;
 IF p_source='authenticated_notification' THEN
  SELECT * INTO e FROM public.billing_observation_receipts WHERE receipt_id=p_receipt AND operation_id=p_id;
  IF NOT FOUND OR e.provider_event_id IS DISTINCT FROM p_reference OR p_outcome='verified'
  THEN RAISE EXCEPTION 'Authenticated notification provenance required' USING ERRCODE='22023'; END IF;
 ELSIF p_source='authoritative_lookup' THEN
  IF p_receipt IS NOT NULL OR p_reference IS DISTINCT FROM coalesce(r.provider_checkout_id,r.provider_subscription_id)
  THEN RAISE EXCEPTION 'Lookup cannot impersonate a notification' USING ERRCODE='22023'; END IF;
 ELSE RAISE EXCEPTION 'Explicit evidence source required' USING ERRCODE='22023'; END IF;
 IF (p_evidence->>'customer' IS NOT NULL AND p_evidence->>'customer' IS DISTINCT FROM r.provider_customer_id)
 OR (p_evidence->>'checkout' IS NOT NULL AND p_evidence->>'checkout' IS DISTINCT FROM r.provider_checkout_id)
 OR (r.provider_subscription_id IS NOT NULL AND p_evidence->>'subscription' IS NOT NULL AND p_evidence->>'subscription' IS DISTINCT FROM r.provider_subscription_id)
 OR (r.request_kind='trial_checkout' AND p_outcome='verified')
 THEN RAISE EXCEPTION 'Observation association or readiness conflict' USING ERRCODE='22023'; END IF;
 IF r.request_kind='trial_checkout' AND p_evidence->>'terms' IS NOT NULL AND (
  (p_evidence#>>'{terms,amount}')::numeric IS DISTINCT FROM (r.request#>>'{trial_terms,amount}')::numeric
  OR ((p_evidence->'terms')-'amount') IS DISTINCT FROM ((r.request->'trial_terms')-'plan_key'-'catalog_revision_id'-'trial_duration_days'-'amount'))
 THEN RAISE EXCEPTION 'Frozen terms conflict' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM public.billing_verification_observations WHERE observation_id=r.last_observation_id;
 conflict:=r.has_conflict OR p_outcome='conflict' OR (old.observation_id IS NOT NULL AND public.billing_confirmation_semantic(old.evidence) IS DISTINCT FROM public.billing_confirmation_semantic(p_evidence));
 INSERT INTO public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id,source,receipt_id,provenance_reference,observed_at,adapter_version,api_version,outcome,evidence,evidence_digest,claim_version,claim_token)
 VALUES(p_observation,p_id,r.tenant_id,r.binding_id,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence,d,p_version,p_token) RETURNING * INTO o;
 UPDATE public.billing_observation_operations SET state=CASE WHEN conflict THEN 'reconciliation_required' ELSE 'observed' END,has_conflict=conflict,
  last_observation_id=p_observation,claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
 RETURN to_jsonb(o);
END $$;
