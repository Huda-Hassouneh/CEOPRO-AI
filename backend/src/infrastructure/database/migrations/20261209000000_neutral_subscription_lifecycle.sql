-- 175: neutral identities and dormant split-authority lifecycle. No policy,
-- merchant approval, LOGIN, membership or ordinary runtime EXECUTE is installed.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_confirmation_owner','ceopro_trial_attestor','ceopro_trial_confirmer',
  'ceopro_consent_owner','ceopro_consent_service','ceopro_observation_owner','ceopro_billing_observer','ceopro_trial_issuer'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
   AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication)
   OR EXISTS(SELECT FROM pg_auth_members WHERE member=r::regrole)
   OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=r::regrole AND member<>current_user::regrole)
   OR has_schema_privilege(r,'public','CREATE')
  THEN RAISE EXCEPTION 'Dormant lifecycle role prerequisites required' USING ERRCODE='42501'; END IF;
 END LOOP;
END $$;
ALTER TABLE public.billing_subscriptions
 ALTER COLUMN stripe_subscription_id DROP NOT NULL, ALTER COLUMN stripe_customer_id DROP NOT NULL,
 ADD COLUMN gateway_binding_id text REFERENCES public.billing_gateway_bindings(binding_id),
 ADD COLUMN provider_subscription_id text, ADD COLUMN provider_customer_id text,
 ADD COLUMN provider_price_id text, ADD COLUMN approved_terms jsonb,
 ADD COLUMN paid_through timestamptz,
 ADD COLUMN lifecycle_version bigint NOT NULL DEFAULT 0,
 ADD CONSTRAINT subscription_neutral_scope CHECK (
  (gateway_binding_id IS NULL AND stripe_subscription_id IS NOT NULL AND stripe_customer_id IS NOT NULL
   AND provider_subscription_id IS NULL AND provider_customer_id IS NULL AND provider_price_id IS NULL AND approved_terms IS NULL)
  OR (gateway_binding_id IS NOT NULL AND nullif(btrim(provider_subscription_id),'') IS NOT NULL
   AND nullif(btrim(provider_customer_id),'') IS NOT NULL AND nullif(btrim(provider_price_id),'') IS NOT NULL
   AND approved_terms IS NOT NULL AND jsonb_typeof(approved_terms)='object'));
ALTER TABLE public.billing_subscriptions ADD UNIQUE(subscription_id,tenant_id,gateway_binding_id);
CREATE UNIQUE INDEX subscription_bound_identity ON public.billing_subscriptions(gateway_binding_id,provider_subscription_id)
 WHERE gateway_binding_id IS NOT NULL;
-- Existing one-current-subscription-per-tenant index continues across ALL providers.
ALTER TABLE public.billing_customer_references ADD UNIQUE(tenant_id,binding_id,provider_customer_id);
ALTER TABLE public.billing_subscriptions ADD FOREIGN KEY(tenant_id,gateway_binding_id,provider_customer_id)
 REFERENCES public.billing_customer_references(tenant_id,binding_id,provider_customer_id);
CREATE TABLE public.billing_lifecycle_provider_approvals (
 binding_id text PRIMARY KEY REFERENCES public.billing_gateway_bindings(binding_id),
 evidence_reference text NOT NULL CHECK(length(btrim(evidence_reference))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE public.billing_lifecycle_provider_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_lifecycle_provider_approvals FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_lifecycle_provider_approvals FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting;
GRANT SELECT ON public.billing_lifecycle_provider_approvals TO ceopro_confirmation_owner,ceopro_trial_issuer;
CREATE POLICY lifecycle_approval_read ON public.billing_lifecycle_provider_approvals FOR SELECT TO ceopro_confirmation_owner,ceopro_trial_issuer USING(true);
CREATE TRIGGER lifecycle_approval_immutable BEFORE UPDATE OR DELETE ON public.billing_lifecycle_provider_approvals
 FOR EACH ROW EXECUTE FUNCTION public.billing_customer_reference_guard();
CREATE FUNCTION public.billing_neutral_subscription_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ DECLARE b public.billing_gateway_bindings; BEGIN
 IF TG_OP='UPDATE' AND OLD.gateway_binding_id IS NOT NULL AND (
  current_user<>'ceopro_confirmation_owner' OR
  (NEW.gateway_binding_id,NEW.provider_subscription_id,NEW.provider_customer_id,NEW.provider_price_id,NEW.approved_terms,NEW.plan_key,NEW.period_code,NEW.trial_end)
  IS DISTINCT FROM (OLD.gateway_binding_id,OLD.provider_subscription_id,OLD.provider_customer_id,OLD.provider_price_id,OLD.approved_terms,OLD.plan_key,OLD.period_code,OLD.trial_end))
 THEN RAISE EXCEPTION 'Neutral subscription identity and terms are immutable' USING ERRCODE='22023'; END IF;
 IF NEW.gateway_binding_id IS NOT NULL THEN
  IF current_user<>'ceopro_confirmation_owner' AND NOT EXISTS(SELECT FROM pg_roles WHERE rolname=current_user AND rolsuper)
  THEN RAISE EXCEPTION 'Trusted confirmation required' USING ERRCODE='42501'; END IF;
  SELECT * INTO b FROM public.billing_gateway_bindings WHERE binding_id=NEW.gateway_binding_id;
  IF b.binding_id IS NULL OR b.environment<>'test' OR
   (b.provider='stripe' AND (NEW.stripe_subscription_id IS DISTINCT FROM NEW.provider_subscription_id OR NEW.stripe_customer_id IS DISTINCT FROM NEW.provider_customer_id)) OR
   (b.provider<>'stripe' AND (NEW.stripe_subscription_id IS NOT NULL OR NEW.stripe_customer_id IS NOT NULL OR NEW.stripe_price_id IS NOT NULL))
  THEN RAISE EXCEPTION 'Original TEST provider identity required' USING ERRCODE='22023'; END IF;
 END IF; RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_neutral_subscription_guard() FROM PUBLIC;
CREATE TRIGGER neutral_subscription_guard BEFORE INSERT OR UPDATE ON public.billing_subscriptions
 FOR EACH ROW EXECUTE FUNCTION public.billing_neutral_subscription_guard();
GRANT INSERT(gateway_binding_id,provider_subscription_id,provider_customer_id,provider_price_id,approved_terms)
 ON public.billing_subscriptions TO ceopro_confirmation_owner;

CREATE OR REPLACE FUNCTION public.billing_trial_checkout_terms(p_plan text,p_period text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE u uuid; b jsonb; s jsonb; BEGIN
 u:=public.billing_reservation_principal(); b:=public.billing_selected_gateway_binding();
 -- Only the existing Stripe catalog is supported; no hypothetical provider prices.
 IF b->>'provider' NOT IN ('stripe','paddle') OR (b->>'provider'='paddle' AND NOT EXISTS(SELECT FROM public.billing_lifecycle_provider_approvals WHERE binding_id=b->>'binding_id')) THEN RAISE EXCEPTION 'Provider price mapping unavailable' USING ERRCODE='22023'; END IF;
 SELECT jsonb_build_object('plan_key',p.plan_key,'period_code',v.period_code,'interval_months',v.interval_months,
  'currency',upper(v.currency),'trial_duration_days',p.trial_days,'price_id',v.price_id,
  'provider_price_id',pr.provider_price_id,'approved_amount',v.amount,'catalog_version',p.catalog_version,
  'entitlement_version',(SELECT version FROM public.entitlement_catalog_version WHERE singleton),
  'features',coalesce((SELECT jsonb_agg(jsonb_build_object('feature_code',f.feature_code,'unit',f.unit,
   'aggregation_type',f.aggregation_type,'reset_cycle',f.reset_cycle,'limit_value',l.limit_value,
   'trial_limit_value',l.trial_limit_value) ORDER BY f.feature_code)
   FROM public.usage_plan_limits l JOIN public.usage_features f USING(feature_code) WHERE l.plan_key=p.plan_key),'[]'::jsonb),
  'entitlements',coalesce((SELECT jsonb_agg(feature_code ORDER BY feature_code) FROM public.usage_plan_entitlements WHERE plan_key=p.plan_key),'[]'::jsonb))
 INTO s FROM public.usage_plans p JOIN public.billing_plan_prices v USING(plan_key)
 JOIN public.billing_price_references pr ON pr.price_id=v.price_id AND pr.binding_id=b->>'binding_id'
 WHERE p.plan_key=p_plan AND v.period_code=p_period AND v.retired_at IS NULL AND p.is_active AND p.self_serve
  AND p.trial_days>0;
 IF s IS NULL THEN RAISE EXCEPTION 'Approved trial price required' USING ERRCODE='22023'; END IF;
 RETURN s||jsonb_build_object('tenant_id',public.get_current_tenant(),'started_by_user_id',u,'binding',b,
  'catalog_revision_id','sha256:'||encode(pg_catalog.sha256(convert_to(s::text,'UTF8')),'hex'));
END $$;


CREATE OR REPLACE FUNCTION public.billing_confirmation_apply(p_attestation uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
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
 IF b.environment<>'test' OR b.provider NOT IN ('stripe','paddle') OR (b.provider='paddle' AND NOT EXISTS(SELECT FROM public.billing_lifecycle_provider_approvals WHERE binding_id=b.binding_id)) THEN RAISE EXCEPTION 'Lifecycle provider/environment not enabled' USING ERRCODE='22023'; END IF;
 -- Legacy Checkout webhook writes the customer BEFORE its subscription lock.
 -- Match that row-lock edge: person -> trial tenant -> customer -> TRY subscription
 -- -> billing tenant -> reservation -> operation. Subscription-only webhooks can
 -- take subscription before a missing customer; never wait at that reverse edge.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 IF b.provider='stripe' THEN
 INSERT INTO public.billing_customers(tenant_id,stripe_customer_id) VALUES(t,a.request->>'customer') ON CONFLICT DO NOTHING;
 PERFORM 1 FROM public.billing_customers WHERE tenant_id=t AND stripe_customer_id=a.request->>'customer' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Historical customer provenance conflict' USING ERRCODE='22023'; END IF;
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended(CASE WHEN b.provider='stripe' THEN 'keel_stripe_subscription:'||(a.evidence->>'subscription') ELSE 'keel_provider_subscription:'||b.binding_id||':'||(a.evidence->>'subscription') END,0))
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
 -- mappings are never adopted/replaced. Paddle additionally requires an installed immutable approval reference.
 IF b.provider='stripe' AND NOT EXISTS(SELECT FROM public.billing_customers WHERE tenant_id=t AND stripe_customer_id=o.provider_customer_id)
 THEN RAISE EXCEPTION 'Historical customer provenance conflict' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_subscriptions(subscription_id,tenant_id,stripe_subscription_id,stripe_customer_id,stripe_price_id,
 plan_key,period_code,status,current_period_start,current_period_end,trial_end,cancel_at_period_end,last_event_at,
 gateway_binding_id,provider_subscription_id,provider_customer_id,provider_price_id,approved_terms)
 VALUES(sub,t,CASE WHEN b.provider='stripe' THEN a.evidence->>'subscription' END,CASE WHEN b.provider='stripe' THEN o.provider_customer_id END,CASE WHEN b.provider='stripe' THEN r.provider_price_id END,r.plan_key,r.period_code,'trialing',start_at,end_at,end_at,false,a.observed_at,b.binding_id,a.evidence->>'subscription',o.provider_customer_id,r.provider_price_id,r.approved_terms);
 INSERT INTO public.billing_trial_confirmations(confirmation_id,tenant_id,binding_id,attempt_id,attestation_id,provider_customer_id,
 provider_subscription_id,subscription_id,started_by_user_id,trial_started_at,trial_ends_at)
 VALUES(p_attestation,t,r.binding_id,r.attempt_id,p_attestation,o.provider_customer_id,a.evidence->>'subscription',sub,u,start_at,end_at) RETURNING * INTO c;
 INSERT INTO public.billing_trials(tenant_id,plan_key,started_at,ends_at,started_by_user_id) VALUES(t,r.plan_key,start_at,end_at,u);
 INSERT INTO public.tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,period_code,source,trial_confirmation_id)
 VALUES(t,r.plan_key,'trialing',(start_at AT TIME ZONE 'UTC')::date,(end_at AT TIME ZONE 'UTC')::date,r.period_code,CASE WHEN b.provider='stripe' THEN 'stripe' ELSE 'gateway' END,c.confirmation_id);
 UPDATE public.billing_trial_checkouts SET state='confirmed',confirmation_id=c.confirmation_id WHERE attempt_id=r.attempt_id;
 PERFORM public.billing_trial_confirmation_close_checkout(c.confirmation_id);
 RETURN to_jsonb(c);
END $$;


-- Lifecycle may vary, original positive identity/financial/trial facts may not.
CREATE FUNCTION public.billing_subscription_progresses(a jsonb,b jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
 SET search_path=pg_catalog,public,pg_temp AS $$ DECLARE k text;x jsonb;y jsonb; BEGIN
 FOREACH k IN ARRAY ARRAY['customer','subscription','terms','trial'] LOOP
  x:=a->k;y:=b->k;
  IF a->>k IS NOT NULL AND b->>k IS NOT NULL THEN
   IF k='terms' THEN
    IF (x->>'amount')::numeric IS DISTINCT FROM (y->>'amount')::numeric OR x-'amount' IS DISTINCT FROM y-'amount' THEN RETURN false; END IF;
   ELSIF x IS DISTINCT FROM y THEN RETURN false;
   END IF;
  END IF;
 END LOOP;
 x:=a->'settlement';y:=b->'settlement';
 IF x->>'invoice' IS NOT NULL AND x->>'invoice'=y->>'invoice' AND
  ((x->>'amount_paid')::numeric IS DISTINCT FROM (y->>'amount_paid')::numeric OR x-'amount_paid' IS DISTINCT FROM y-'amount_paid')
 THEN RETURN false; END IF;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.billing_subscription_progresses(jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_subscription_progresses(jsonb,jsonb) TO ceopro_observation_owner;
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
 IF EXISTS(SELECT FROM public.billing_verification_observations h
  WHERE h.operation_id=p_id AND h.observed_at>p_observed)
 THEN RAISE EXCEPTION 'Out-of-order trial observation' USING ERRCODE='22023'; END IF;
 -- Compare ALL immutable history: an incomplete intervening read must not hide
 -- an earlier positive identity or financial contradiction. No row is rewritten.
 conflict:=r.has_conflict OR p_outcome='conflict' OR CASE WHEN r.request_kind='trial_checkout' THEN
  EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=p_id
   AND NOT public.billing_confirmation_progresses(h.evidence,p_evidence))
 ELSE EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=p_id AND NOT public.billing_subscription_progresses(h.evidence,p_evidence)) END;
 INSERT INTO public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id,source,receipt_id,provenance_reference,observed_at,adapter_version,api_version,outcome,evidence,evidence_digest,claim_version,claim_token)
 VALUES(p_observation,p_id,r.tenant_id,r.binding_id,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence,d,p_version,p_token) RETURNING * INTO o;
 UPDATE public.billing_observation_operations SET state=CASE WHEN conflict THEN 'reconciliation_required' ELSE 'observed' END,has_conflict=conflict,
  last_observation_id=p_observation,claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
 RETURN to_jsonb(o);
END $$;

CREATE FUNCTION public.billing_lifecycle_authorize(t uuid,u uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF session_user NOT IN ('ceopro_trial_attestor','ceopro_trial_confirmer') OR t IS NULL OR u IS NULL
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

REVOKE ALL ON FUNCTION public.billing_lifecycle_authorize(uuid,uuid) FROM PUBLIC;
CREATE TABLE public.billing_lifecycle_attestations (
 attestation_id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 subscription_id uuid NOT NULL REFERENCES public.billing_subscriptions(subscription_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 observation_id uuid NOT NULL REFERENCES public.billing_verification_observations(observation_id),
 receipt_id uuid NOT NULL UNIQUE REFERENCES public.billing_observation_receipts(receipt_id),
 operation_id uuid NOT NULL REFERENCES public.billing_observation_operations(operation_id),
 expected_version bigint NOT NULL,actor_id uuid NOT NULL REFERENCES public.users(user_id),
 evidence jsonb NOT NULL,observed_at timestamptz NOT NULL,event_at timestamptz NOT NULL,
 FOREIGN KEY(subscription_id,tenant_id,binding_id) REFERENCES public.billing_subscriptions(subscription_id,tenant_id,gateway_binding_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.billing_lifecycle_applications (
 attestation_id uuid PRIMARY KEY REFERENCES public.billing_lifecycle_attestations(attestation_id),
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_lifecycle_attestations','billing_lifecycle_applications'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tab);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',tab);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting,ceopro_trial_attestor,ceopro_trial_confirmer',tab);
  EXECUTE format('GRANT SELECT,INSERT ON public.%I TO ceopro_confirmation_owner',tab);
  EXECUTE format('CREATE POLICY lifecycle_owner ON public.%I TO ceopro_confirmation_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',tab);
  EXECUTE format('CREATE TRIGGER lifecycle_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_immutable()',tab);
 END LOOP;
END $$;
GRANT SELECT ON public.billing_observation_receipts TO ceopro_confirmation_owner;
CREATE POLICY lifecycle_receipt_read ON public.billing_observation_receipts FOR SELECT TO ceopro_confirmation_owner USING(tenant_id=public.get_current_tenant());
GRANT UPDATE(status,current_period_start,current_period_end,cancel_at_period_end,cancelled_at,last_event_at,updated_at,lifecycle_version,paid_through)
 ON public.billing_subscriptions TO ceopro_confirmation_owner;
CREATE POLICY lifecycle_subscription_update ON public.billing_subscriptions FOR UPDATE TO ceopro_confirmation_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
GRANT UPDATE(status,current_period_start,current_period_end,updated_at) ON public.tenant_plan_assignments TO ceopro_confirmation_owner;
CREATE POLICY lifecycle_assignment_update ON public.tenant_plan_assignments FOR UPDATE TO ceopro_confirmation_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_lifecycle_context(p_subscription uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE s public.billing_subscriptions;c public.billing_trial_confirmations;u uuid;b jsonb; BEGIN
 u:=public.billing_confirmation_principal(session_user::text);
 IF session_user NOT IN ('ceopro_trial_attestor','ceopro_trial_confirmer') THEN RAISE EXCEPTION 'Lifecycle socket required' USING ERRCODE='42501'; END IF;
 SELECT * INTO s FROM public.billing_subscriptions WHERE tenant_id=public.get_current_tenant() AND (subscription_id=p_subscription OR subscription_id IN (SELECT subscription_id FROM public.billing_trial_confirmations WHERE confirmation_id=p_subscription));
 SELECT * INTO c FROM public.billing_trial_confirmations WHERE subscription_id=s.subscription_id AND tenant_id=s.tenant_id;
 IF c.confirmation_id IS NULL OR c.started_by_user_id<>u OR s.gateway_binding_id IS NULL OR c.binding_id<>s.gateway_binding_id
 OR c.provider_subscription_id<>s.provider_subscription_id OR c.provider_customer_id<>s.provider_customer_id
 THEN RAISE EXCEPTION 'Original confirmed subscription required' USING ERRCODE='42501'; END IF;
 PERFORM public.billing_lifecycle_authorize(s.tenant_id,u);
 SELECT to_jsonb(g) INTO b FROM public.billing_gateway_bindings g WHERE binding_id=s.gateway_binding_id AND environment='test';
 IF b IS NULL THEN RAISE EXCEPTION 'TEST lifecycle only' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('subscription',to_jsonb(s),'confirmation',to_jsonb(c),'binding',b);
END $$;
CREATE FUNCTION public.billing_lifecycle_attest(p_id uuid,p_subscription uuid,p_observation uuid,p_receipt uuid,p_version bigint) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE ctx jsonb;s public.billing_subscriptions;h public.billing_verification_observations;o public.billing_observation_operations;
 r public.billing_observation_receipts;a public.billing_lifecycle_attestations;u uuid; BEGIN
 u:=public.billing_confirmation_principal('ceopro_trial_attestor');ctx:=public.billing_lifecycle_context(p_subscription);
 SELECT * INTO s FROM public.billing_subscriptions WHERE subscription_id=(ctx#>>'{subscription,subscription_id}')::uuid;
 SELECT * INTO h FROM public.billing_verification_observations WHERE observation_id=p_observation;
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=h.operation_id;
 SELECT * INTO r FROM public.billing_observation_receipts WHERE receipt_id=p_receipt AND operation_id=o.operation_id;
 IF h.observation_id IS NULL OR r.receipt_id IS NULL OR o.has_conflict OR o.request_kind<>'subscription'
 OR o.initiated_by<>u OR o.tenant_id<>s.tenant_id OR o.binding_id<>s.gateway_binding_id
 OR o.provider_customer_id<>s.provider_customer_id OR o.provider_subscription_id<>s.provider_subscription_id
 OR h.source<>'authoritative_lookup' OR h.outcome<>'verified' OR o.last_observation_id<>h.observation_id
 OR h.observed_at<clock_timestamp()-interval '5 minutes'
 THEN RAISE EXCEPTION 'Fresh exact authoritative lifecycle evidence required' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM public.billing_lifecycle_attestations WHERE receipt_id=p_receipt;
 IF FOUND THEN
  IF a.subscription_id<>p_subscription THEN RAISE EXCEPTION 'Lifecycle replay conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(a);
 END IF;
 INSERT INTO public.billing_lifecycle_attestations(attestation_id,tenant_id,subscription_id,binding_id,observation_id,receipt_id,operation_id,expected_version,actor_id,evidence,observed_at,event_at)
 VALUES(p_id,s.tenant_id,s.subscription_id,s.gateway_binding_id,h.observation_id,r.receipt_id,o.operation_id,p_version,u,h.evidence,h.observed_at,r.occurred_at) RETURNING * INTO a;
 RETURN to_jsonb(a);
END $$;
-- New-cohort settlements never put Paddle identities in historical Stripe columns.
CREATE TABLE public.billing_lifecycle_payments (
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),provider_invoice_id text NOT NULL,
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),subscription_id uuid NOT NULL REFERENCES public.billing_subscriptions(subscription_id),
 provider text NOT NULL CHECK(provider IN ('stripe','paddle')),amount numeric NOT NULL CHECK(amount>0),currency text NOT NULL,
 paid_at timestamptz NOT NULL,period_start timestamptz NOT NULL,period_end timestamptz NOT NULL,
 attestation_id uuid NOT NULL REFERENCES public.billing_lifecycle_attestations(attestation_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(binding_id,provider_invoice_id),CHECK(period_end>period_start),
 FOREIGN KEY(subscription_id,tenant_id,binding_id) REFERENCES public.billing_subscriptions(subscription_id,tenant_id,gateway_binding_id)
);
ALTER TABLE public.billing_lifecycle_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_lifecycle_payments FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_lifecycle_payments FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting;
GRANT SELECT,INSERT ON public.billing_lifecycle_payments TO ceopro_confirmation_owner;
GRANT SELECT ON public.billing_lifecycle_payments TO ceopro_app;
CREATE POLICY lifecycle_payment_owner ON public.billing_lifecycle_payments TO ceopro_confirmation_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE POLICY lifecycle_payment_read ON public.billing_lifecycle_payments FOR SELECT TO ceopro_app
 USING(tenant_id=public.get_current_tenant() AND public.keel_active_principal(nullif(current_setting('app.current_user_id',true),'')::uuid,tenant_id));
CREATE TRIGGER lifecycle_payment_immutable BEFORE UPDATE OR DELETE ON public.billing_lifecycle_payments FOR EACH ROW EXECUTE FUNCTION public.billing_confirmation_immutable();
-- Calendar boundaries use the original trial-end anchor, not last month's
-- clamped day. Jan 31 -> Feb 28 -> Mar 31 must not drift to Mar 28.
CREATE FUNCTION public.billing_lifecycle_boundary(p_start timestamptz,p_anchor timestamptz,p_months integer) RETURNS timestamptz
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
 WITH target AS (SELECT date_trunc('month',p_start AT TIME ZONE 'UTC')+make_interval(months=>p_months) AS m)
 SELECT ((m::date+(least(extract(day FROM p_anchor AT TIME ZONE 'UTC')::int,
   extract(day FROM m+interval '1 month - 1 day')::int)-1))+(p_anchor AT TIME ZONE 'UTC')::time) AT TIME ZONE 'UTC' FROM target
 $$;
REVOKE ALL ON FUNCTION public.billing_lifecycle_boundary(timestamptz,timestamptz,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_lifecycle_boundary(timestamptz,timestamptz,integer) TO ceopro_confirmation_owner;
CREATE FUNCTION public.billing_lifecycle_apply(p_id uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a public.billing_lifecycle_attestations;s public.billing_subscriptions;v public.billing_lifecycle_applications;
 o public.billing_observation_operations;e jsonb;f jsonb;pay jsonb;u uuid;n timestamptz;st text;ps timestamptz;pe timestamptz;through_at timestamptz; BEGIN
 u:=public.billing_confirmation_principal('ceopro_trial_confirmer');
 SELECT * INTO a FROM public.billing_lifecycle_attestations WHERE attestation_id=p_id AND tenant_id=public.get_current_tenant();
 IF a.attestation_id IS NULL OR a.actor_id<>u THEN RAISE EXCEPTION 'Owned lifecycle attestation required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||a.tenant_id::text,0));
 SELECT * INTO s FROM public.billing_subscriptions WHERE subscription_id=a.subscription_id FOR UPDATE;
 PERFORM public.billing_lifecycle_authorize(a.tenant_id,u);
 SELECT * INTO v FROM public.billing_lifecycle_applications WHERE attestation_id=p_id;
 IF FOUND THEN RETURN v.result; END IF;
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=a.operation_id FOR UPDATE;
 n:=clock_timestamp();e:=a.evidence;f:=s.approved_terms;pay:=e->'settlement';
 IF s.gateway_binding_id<>a.binding_id OR s.lifecycle_version IS DISTINCT FROM a.expected_version
 OR a.observed_at<n-interval '5 minutes' OR a.observed_at>n+interval '30 seconds'
 OR a.event_at>n+interval '30 seconds' OR a.event_at<=s.last_event_at
 OR o.has_conflict OR o.last_observation_id<>a.observation_id
 THEN RAISE EXCEPTION 'Stale or conflicting lifecycle evidence' USING ERRCODE='55000'; END IF;
 IF e->>'customer' IS DISTINCT FROM s.provider_customer_id OR e->>'subscription' IS DISTINCT FROM s.provider_subscription_id
 OR e#>>'{terms,price}' IS DISTINCT FROM s.provider_price_id OR e#>>'{terms,currency}' IS DISTINCT FROM f->>'currency'
 OR (e#>>'{terms,amount}')::numeric IS DISTINCT FROM (f->>'approved_amount')::numeric
 OR (e#>>'{terms,interval_months}')::int IS DISTINCT FROM (f->>'interval_months')::int
 OR e#>>'{terms,quantity}' IS DISTINCT FROM '1' OR e#>>'{capabilities,authoritative_reconciliation}' IS DISTINCT FROM 'supported'
 OR e#>>'{recurring_authority,consent}'='recorded'
 THEN RAISE EXCEPTION 'Frozen lifecycle terms conflict' USING ERRCODE='22023'; END IF;
 IF e->>'trial' IS NOT NULL AND NOT EXISTS(SELECT FROM public.billing_trial_confirmations c WHERE c.subscription_id=s.subscription_id
  AND c.trial_started_at=(e#>>'{trial,started_at}')::timestamptz AND c.trial_ends_at=(e#>>'{trial,ends_at}')::timestamptz)
 THEN RAISE EXCEPTION 'Original trial evidence conflict' USING ERRCODE='22023'; END IF;
 st:=e->>'subscription_state';ps:=(e->>'period_start')::timestamptz;pe:=(e->>'period_end')::timestamptz;through_at:=s.paid_through;
 IF st='trialing' THEN
  IF s.status<>'trialing' OR (e#>>'{trial,ends_at}')::timestamptz IS DISTINCT FROM s.trial_end
   OR (e#>>'{trial,started_at}')::timestamptz IS DISTINCT FROM s.current_period_start
  THEN RAISE EXCEPTION 'Trial boundary conflict' USING ERRCODE='22023'; END IF;
  ps:=s.current_period_start;pe:=s.trial_end;
 ELSIF st='active' THEN
  IF ps IS NULL OR pe IS NULL OR ps>n OR pe<=n OR ps<s.trial_end
   OR ps<>public.billing_lifecycle_boundary(ps,s.trial_end,0)
   OR pe<>public.billing_lifecycle_boundary(ps,s.trial_end,(f->>'interval_months')::int)
   OR ps<s.current_period_start
  THEN RAISE EXCEPTION 'Paid period conflict' USING ERRCODE='22023'; END IF;
  IF pay IS NULL OR pay='null'::jsonb THEN
   IF through_at IS DISTINCT FROM pe OR ps IS DISTINCT FROM s.current_period_start
   THEN RAISE EXCEPTION 'Paid renewal settlement required' USING ERRCODE='22023'; END IF;
  ELSE
   IF pay->>'confirmed' IS DISTINCT FROM 'true' OR pay->>'payment_state' IS DISTINCT FROM 'paid'
    OR pay->>'purpose' IS DISTINCT FROM 'renewal' OR pay->>'currency' IS DISTINCT FROM f->>'currency'
    OR (pay->>'amount_paid')::numeric IS DISTINCT FROM (f->>'approved_amount')::numeric OR (pay->>'amount_paid')::numeric<=0
    OR nullif(pay->>'invoice','') IS NULL OR (pay->>'paid_at')::timestamptz IS NULL OR (pay->>'paid_at')::timestamptz>n
    OR jsonb_array_length(pay->'coverage')<>1 OR (pay#>>'{coverage,0,0}')::timestamptz IS DISTINCT FROM ps
    OR (pay#>>'{coverage,0,1}')::timestamptz IS DISTINCT FROM pe
   THEN RAISE EXCEPTION 'Exact positive paid renewal required' USING ERRCODE='22023'; END IF;
   IF EXISTS(SELECT FROM public.billing_lifecycle_payments p WHERE p.binding_id=s.gateway_binding_id AND p.provider_invoice_id=pay->>'invoice'
    AND (p.subscription_id<>s.subscription_id OR p.tenant_id<>s.tenant_id OR p.amount<>(pay->>'amount_paid')::numeric
     OR p.currency<>pay->>'currency' OR p.period_start<>ps OR p.period_end<>pe))
   THEN RAISE EXCEPTION 'Settlement identity replay conflict' USING ERRCODE='22023'; END IF;
   INSERT INTO public.billing_lifecycle_payments(binding_id,provider_invoice_id,tenant_id,subscription_id,provider,amount,currency,paid_at,period_start,period_end,attestation_id)
   VALUES(s.gateway_binding_id,pay->>'invoice',s.tenant_id,s.subscription_id,f#>>'{binding,provider}',(pay->>'amount_paid')::numeric,pay->>'currency',(pay->>'paid_at')::timestamptz,ps,pe,a.attestation_id) ON CONFLICT DO NOTHING;
   -- ON CONFLICT may see a concurrent/foreign row hidden by tenant RLS.
   -- Recheck after the unique-index wait; a hidden winner cannot grant rights.
   IF NOT EXISTS(SELECT FROM public.billing_lifecycle_payments p WHERE p.binding_id=s.gateway_binding_id AND p.provider_invoice_id=pay->>'invoice'
    AND p.subscription_id=s.subscription_id AND p.tenant_id=s.tenant_id AND p.amount=(pay->>'amount_paid')::numeric
    AND p.currency=pay->>'currency' AND p.period_start=ps AND p.period_end=pe)
   THEN RAISE EXCEPTION 'Settlement already belongs to another scope' USING ERRCODE='22023'; END IF;
   through_at:=pe;
  END IF;
 ELSIF st='cancelled' AND through_at>n THEN
  -- An acknowledged stop-renewal never truncates an already paid period.
  st:='active';ps:=s.current_period_start;pe:=through_at;
 ELSIF st IN ('past_due','payment_failed','paused','cancelled','expired','pending') THEN
  ps:=s.current_period_start;pe:=s.current_period_end;
 ELSE RAISE EXCEPTION 'Unsupported lifecycle state' USING ERRCODE='22023'; END IF;
 IF e->>'cancel_at_period_end' NOT IN ('true','false') OR e->>'cancel_at_period_end' IS NULL
 THEN RAISE EXCEPTION 'Explicit cancellation evidence required' USING ERRCODE='22023'; END IF;
 UPDATE public.billing_subscriptions SET status=st,current_period_start=ps,current_period_end=pe,paid_through=through_at,
 cancel_at_period_end=(e->>'cancel_at_period_end')::boolean OR e->>'subscription_state'='cancelled',
 cancelled_at=(e->>'cancelled_at')::timestamptz,last_event_at=a.event_at,lifecycle_version=lifecycle_version+1,updated_at=n WHERE subscription_id=s.subscription_id;
 UPDATE public.tenant_plan_assignments SET status=st,current_period_start=(ps AT TIME ZONE 'UTC')::date,
 current_period_end=(pe AT TIME ZONE 'UTC')::date,updated_at=n WHERE tenant_id=s.tenant_id AND trial_confirmation_id IS NOT NULL;
 IF NOT FOUND THEN RAISE EXCEPTION 'Frozen confirmed assignment required' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_lifecycle_applications(attestation_id,tenant_id,result) VALUES(p_id,s.tenant_id,
 jsonb_build_object('subscription_id',s.subscription_id,'state',st,'version',s.lifecycle_version+1)) RETURNING * INTO v;
 RETURN v.result;
END $$;
REVOKE ALL ON FUNCTION public.billing_lifecycle_context(uuid),public.billing_lifecycle_attest(uuid,uuid,uuid,uuid,bigint),public.billing_lifecycle_apply(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_lifecycle_context(uuid) TO ceopro_trial_attestor,ceopro_trial_confirmer;
GRANT EXECUTE ON FUNCTION public.billing_lifecycle_attest(uuid,uuid,uuid,uuid,bigint) TO ceopro_trial_attestor;
GRANT EXECUTE ON FUNCTION public.billing_lifecycle_apply(uuid) TO ceopro_trial_confirmer;
GRANT CREATE ON SCHEMA public TO ceopro_confirmation_owner,ceopro_observation_owner;
ALTER FUNCTION public.billing_lifecycle_authorize(uuid,uuid) OWNER TO ceopro_confirmation_owner;
ALTER FUNCTION public.billing_lifecycle_context(uuid) OWNER TO ceopro_confirmation_owner;
ALTER FUNCTION public.billing_lifecycle_attest(uuid,uuid,uuid,uuid,bigint) OWNER TO ceopro_confirmation_owner;
ALTER FUNCTION public.billing_lifecycle_apply(uuid) OWNER TO ceopro_confirmation_owner;
ALTER FUNCTION public.billing_subscription_progresses(jsonb,jsonb) OWNER TO ceopro_observation_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_confirmation_owner,ceopro_observation_owner;

-- Pre-confirmation remote compensation is distinct from subscription cancellation.
-- A lost elected response permits GET recovery only; no lease resets a sender.
CREATE TABLE public.billing_journey_compensations (
 attempt_id uuid PRIMARY KEY REFERENCES public.billing_trial_checkouts(attempt_id),
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),confirmed_at timestamptz,
 provider_subscription_id text
);
ALTER TABLE public.billing_journey_compensations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_journey_compensations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_journey_compensations FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting;
GRANT SELECT,INSERT,UPDATE(confirmed_at,provider_subscription_id) ON public.billing_journey_compensations TO ceopro_consent_owner;
CREATE POLICY compensation_owner ON public.billing_journey_compensations TO ceopro_consent_owner
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_journey_compensate(p_attempt uuid,p_action text,p_subscription text DEFAULT NULL) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts;d public.billing_journey_dispatches;a public.billing_consent_acceptances;
 v public.billing_journey_compensations;u uuid;elected boolean:=false; BEGIN
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=public.get_current_tenant() FOR UPDATE;
 u:=public.billing_consent_authorize();
 SELECT * INTO d FROM public.billing_journey_dispatches WHERE attempt_id=r.attempt_id;
 SELECT * INTO a FROM public.billing_consent_acceptances WHERE acceptance_id=d.acceptance_id;
 IF r.attempt_id IS NULL OR r.started_by_user_id<>u OR r.state<>'pending' OR a.acceptance_id IS NULL
 OR NOT EXISTS(SELECT FROM public.billing_consent_invalidations WHERE presentation_id=a.presentation_id)
 THEN RAISE EXCEPTION 'Owned withdrawn unconfirmed journey required' USING ERRCODE='42501'; END IF;
 SELECT * INTO v FROM public.billing_journey_compensations WHERE attempt_id=r.attempt_id;
 IF p_action='elect' AND v.attempt_id IS NULL THEN
  INSERT INTO public.billing_journey_compensations(attempt_id,tenant_id) VALUES(r.attempt_id,r.tenant_id) RETURNING * INTO v;elected:=true;
 ELSIF p_action='record' AND v.attempt_id IS NOT NULL THEN
  IF nullif(btrim(p_subscription),'') IS NULL OR (d.provider_subscription_id IS NOT NULL AND d.provider_subscription_id<>p_subscription)
   OR (v.provider_subscription_id IS NOT NULL AND v.provider_subscription_id<>p_subscription)
  THEN RAISE EXCEPTION 'Compensation subscription conflict' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_journey_compensations SET provider_subscription_id=p_subscription,confirmed_at=coalesce(confirmed_at,clock_timestamp())
  WHERE attempt_id=r.attempt_id RETURNING * INTO v;
 ELSIF p_action NOT IN ('elect','read') THEN RAISE EXCEPTION 'Compensation action conflict' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('elected',elected,'compensation',to_jsonb(v));
END $$;
REVOKE ALL ON FUNCTION public.billing_journey_compensate(uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_journey_compensate(uuid,text,text) TO ceopro_consent_service;
GRANT CREATE ON SCHEMA public TO ceopro_consent_owner;
ALTER FUNCTION public.billing_journey_compensate(uuid,text,text) OWNER TO ceopro_consent_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_consent_owner;
