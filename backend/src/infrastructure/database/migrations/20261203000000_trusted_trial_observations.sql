-- Dormant evidence only. No trial/subscription/assignment/Credit writes or activation commands.
-- Neither new role can log in. No existing runtime identity receives membership.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['ceopro_observation_owner','ceopro_billing_observer'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION',r);
  END IF;
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication)
   OR EXISTS(SELECT FROM pg_auth_members WHERE member=r::regrole)
   OR EXISTS(SELECT FROM pg_auth_members WHERE roleid=r::regrole AND member<>current_user::regrole)
  THEN RAISE EXCEPTION 'Dormant observation role prerequisites required'; END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO ceopro_observation_owner,ceopro_billing_observer;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid,uuid) TO ceopro_observation_owner;
GRANT SELECT ON public.tenant_users,public.billing_gateway_bindings,public.billing_customer_references,
 public.billing_checkout_attempts,public.billing_trial_checkouts,public.billing_customer_operations TO ceopro_observation_owner;
CREATE POLICY observation_membership_read ON public.tenant_users FOR SELECT TO ceopro_observation_owner USING(tenant_id=public.get_current_tenant());
CREATE POLICY observation_binding_read ON public.billing_gateway_bindings FOR SELECT TO ceopro_observation_owner USING(true);
CREATE POLICY observation_attempt_read ON public.billing_checkout_attempts FOR SELECT TO ceopro_observation_owner USING(tenant_id=public.get_current_tenant());
CREATE POLICY observation_reservation_read ON public.billing_trial_checkouts FOR SELECT TO ceopro_observation_owner USING(tenant_id=public.get_current_tenant());
CREATE POLICY observation_customer_operation_read ON public.billing_customer_operations FOR SELECT TO ceopro_observation_owner USING(tenant_id=public.get_current_tenant());
ALTER TABLE public.billing_trial_checkouts ADD CONSTRAINT observation_reservation_scope UNIQUE(attempt_id,tenant_id,binding_id);
ALTER TABLE public.billing_customer_operations ADD CONSTRAINT observation_customer_operation_scope
 UNIQUE(operation_id,tenant_id,binding_id,reference_id,provider_customer_id);

CREATE TABLE public.billing_observation_operations (
 operation_id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id), initiated_by uuid NOT NULL REFERENCES public.users(user_id),
 request_kind text NOT NULL CHECK(request_kind IN ('trial_checkout','subscription')),
 attempt_id uuid, reference_id uuid NOT NULL, provider_customer_id text NOT NULL, customer_operation_id uuid,
 provider_checkout_id text, provider_subscription_id text, terms_digest text,
 request jsonb NOT NULL CHECK(jsonb_typeof(request)='object'),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','observed','reconciliation_required')),
 version bigint NOT NULL DEFAULT 0 CHECK(version>=0), claim_token uuid, claim_until timestamptz,
 has_conflict boolean NOT NULL DEFAULT false, last_observation_id uuid,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(operation_id,tenant_id,binding_id),
 FOREIGN KEY(attempt_id,tenant_id,binding_id) REFERENCES public.billing_trial_checkouts(attempt_id,tenant_id,binding_id),
 FOREIGN KEY(reference_id,tenant_id,binding_id,provider_customer_id) REFERENCES public.billing_customer_references(reference_id,tenant_id,binding_id,provider_customer_id),
 FOREIGN KEY(customer_operation_id,tenant_id,binding_id,reference_id,provider_customer_id)
  REFERENCES public.billing_customer_operations(operation_id,tenant_id,binding_id,reference_id,provider_customer_id),
 CHECK((claim_token IS NULL)=(claim_until IS NULL)),
 CHECK((request_kind='trial_checkout' AND attempt_id IS NOT NULL AND provider_checkout_id IS NOT NULL AND terms_digest ~ '^sha256:[0-9a-f]{64}$')
 OR (request_kind='subscription' AND attempt_id IS NULL AND provider_checkout_id IS NULL AND terms_digest IS NULL AND provider_subscription_id IS NOT NULL))
);
CREATE UNIQUE INDEX observation_trial_operation ON public.billing_observation_operations(attempt_id) WHERE attempt_id IS NOT NULL;
CREATE UNIQUE INDEX observation_subscription_operation ON public.billing_observation_operations(tenant_id,binding_id,provider_subscription_id) WHERE request_kind='subscription';
CREATE TABLE public.billing_observation_receipts (
 receipt_id uuid PRIMARY KEY,operation_id uuid NOT NULL,tenant_id uuid NOT NULL,binding_id text NOT NULL,
 provider_event_id text NOT NULL CHECK(length(provider_event_id) BETWEEN 1 AND 255 AND provider_event_id=btrim(provider_event_id)),
 body_digest text NOT NULL CHECK(body_digest ~ '^sha256:[0-9a-f]{64}$'),
 occurred_at timestamptz NOT NULL, authenticated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 authenticated_by uuid NOT NULL REFERENCES public.users(user_id),
 UNIQUE(binding_id,provider_event_id),UNIQUE(receipt_id,operation_id,tenant_id,binding_id),
 FOREIGN KEY(operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_operations(operation_id,tenant_id,binding_id)
);
CREATE TABLE public.billing_verification_observations (
 observation_id uuid PRIMARY KEY,operation_id uuid NOT NULL,tenant_id uuid NOT NULL,binding_id text NOT NULL,
 source text NOT NULL CHECK(source IN ('authenticated_notification','authoritative_lookup')),receipt_id uuid,
 provenance_reference text NOT NULL CHECK(length(provenance_reference) BETWEEN 1 AND 255),
 observed_at timestamptz NOT NULL,recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 adapter_version text NOT NULL CHECK(length(adapter_version) BETWEEN 1 AND 128),api_version text NOT NULL CHECK(length(api_version) BETWEEN 1 AND 128),
 outcome text NOT NULL CHECK(outcome IN ('verified','pending','conflict','unavailable','unsupported')),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
 evidence_digest text NOT NULL CHECK(evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
 claim_version bigint NOT NULL,claim_token uuid NOT NULL,
 UNIQUE(observation_id,operation_id,tenant_id,binding_id),
 CHECK((source='authenticated_notification')=(receipt_id IS NOT NULL)),
 FOREIGN KEY(operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_operations(operation_id,tenant_id,binding_id),
 FOREIGN KEY(receipt_id,operation_id,tenant_id,binding_id) REFERENCES public.billing_observation_receipts(receipt_id,operation_id,tenant_id,binding_id)
);
ALTER TABLE public.billing_observation_operations ADD FOREIGN KEY(last_observation_id,operation_id,tenant_id,binding_id)
 REFERENCES public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id);

CREATE FUNCTION public.billing_observation_principal() RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant();u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF session_user<>'ceopro_billing_observer' OR public.keel_active_principal(u,t) IS DISTINCT FROM true
 OR NOT EXISTS(SELECT FROM public.tenant_users WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant') AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'Restricted observation principal required' USING ERRCODE='42501'; END IF;
 RETURN u;
END $$;
CREATE FUNCTION public.billing_observation_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF current_user<>'ceopro_observation_owner' OR TG_OP='DELETE'
 THEN RAISE EXCEPTION 'Restricted immutable observation command required' USING ERRCODE='42501'; END IF;
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME<>'billing_observation_operations' THEN RAISE EXCEPTION 'Observation evidence is immutable' USING ERRCODE='22023'; END IF;
  IF NEW.version<>OLD.version+1
   OR (to_jsonb(NEW)-ARRAY['state','version','claim_token','claim_until','has_conflict','last_observation_id','updated_at'])
    IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','claim_token','claim_until','has_conflict','last_observation_id','updated_at'])
   OR (OLD.has_conflict AND NOT NEW.has_conflict)
  THEN RAISE EXCEPTION 'Observation identity is immutable' USING ERRCODE='22023'; END IF;
 END IF; RETURN NEW;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['billing_observation_operations','billing_observation_receipts','billing_verification_observations'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tab);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',tab);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook,ceopro_credit_accounting',tab);
  EXECUTE format('GRANT SELECT ON public.%I TO ceopro_billing_observer',tab);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO ceopro_observation_owner',tab);
  EXECUTE format('CREATE POLICY observation_owner ON public.%I TO ceopro_observation_owner USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',tab);
  EXECUTE format('CREATE POLICY observation_reader ON public.%I FOR SELECT TO ceopro_billing_observer USING(tenant_id=public.get_current_tenant() AND public.billing_observation_principal() IS NOT NULL)',tab);
  EXECUTE format('CREATE TRIGGER observation_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.billing_observation_guard()',tab);
 END LOOP;
END $$;

CREATE FUNCTION public.billing_observation_object(p jsonb,keys text[]) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF jsonb_typeof(p) IS DISTINCT FROM 'object' OR EXISTS(SELECT FROM jsonb_object_keys(p) k WHERE NOT k=ANY(keys))
 THEN RAISE EXCEPTION 'Unsupported normalized observation shape' USING ERRCODE='22023'; END IF;
END $$;
CREATE FUNCTION public.billing_observation_trial_context(p_attempt uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_trial_checkouts;a public.billing_checkout_attempts;c public.billing_customer_references;b jsonb;cop uuid;
BEGIN
 PERFORM public.billing_observation_principal();
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt;
 IF NOT FOUND THEN RAISE EXCEPTION 'Observation association unavailable' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM public.billing_checkout_attempts WHERE attempt_id=r.attempt_id;
 SELECT * INTO c FROM public.billing_customer_references WHERE tenant_id=r.tenant_id AND binding_id=r.binding_id;
 IF c.reference_id IS NULL OR a.gateway_binding_id IS DISTINCT FROM r.binding_id OR a.provider_session_id IS NULL
 THEN RAISE EXCEPTION 'Observation association unavailable' USING ERRCODE='22023'; END IF;
 SELECT jsonb_build_object('provider',provider,'environment',environment,'merchant_account_id',merchant_account_id,'binding_id',binding_id)
 INTO b FROM public.billing_gateway_bindings WHERE binding_id=r.binding_id;
 SELECT operation_id INTO cop FROM public.billing_customer_operations WHERE reference_id=c.reference_id AND state='succeeded';
 RETURN jsonb_build_object('kind','trial_checkout','tenant_id',r.tenant_id,'binding',b,'attempt_id',r.attempt_id,
  'customer',c.provider_customer_id,'customer_operation_id',cop,'checkout',a.provider_session_id,'subscription',NULL,
  'terms_digest','sha256:'||encode(sha256(convert_to(r.approved_terms::text,'UTF8')),'hex'),
  'trial_terms',jsonb_build_object('plan_key',r.plan_key,'catalog_revision_id',r.catalog_revision_id,'interval_months',r.interval_months,
   'currency',r.currency,'trial_duration_days',r.trial_duration_days,'amount',r.approved_amount::text,'quantity',1,'price',r.provider_price_id));
END $$;
CREATE FUNCTION public.billing_observation_begin(p_id uuid,p_request jsonb) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant();u uuid;b jsonb;c public.billing_customer_references;r public.billing_observation_operations;expected jsonb;cop public.billing_customer_operations;
BEGIN
 u:=public.billing_observation_principal();
 PERFORM public.billing_observation_object(p_request,ARRAY['kind','tenant_id','binding','attempt_id','customer','customer_operation_id','checkout','subscription','terms_digest','trial_terms']);
 SELECT jsonb_build_object('provider',provider,'environment',environment,'merchant_account_id',merchant_account_id,'binding_id',binding_id)
 INTO b FROM public.billing_gateway_bindings WHERE binding_id=p_request#>>'{binding,binding_id}';
 IF b IS NULL OR p_request->'binding' IS DISTINCT FROM b OR p_request->>'tenant_id' IS DISTINCT FROM t::text
 THEN RAISE EXCEPTION 'Observation binding conflict' USING ERRCODE='22023'; END IF;
 SELECT * INTO c FROM public.billing_customer_references WHERE tenant_id=t AND binding_id=b->>'binding_id' AND provider_customer_id=p_request->>'customer';
 IF NOT FOUND THEN RAISE EXCEPTION 'Observation association unavailable' USING ERRCODE='22023'; END IF;
 IF nullif(p_request->>'customer_operation_id','') IS NOT NULL THEN
  SELECT * INTO cop FROM public.billing_customer_operations WHERE operation_id=(p_request->>'customer_operation_id')::uuid;
  IF cop.state IS DISTINCT FROM 'succeeded' OR cop.reference_id IS DISTINCT FROM c.reference_id
  THEN RAISE EXCEPTION 'Customer lineage conflict' USING ERRCODE='22023'; END IF;
 END IF;
 IF p_request->>'kind'='trial_checkout' THEN
  expected:=public.billing_observation_trial_context((p_request->>'attempt_id')::uuid);
  -- Unknown provider subscription is explicit until the exact Checkout lookup.
  IF p_request->>'subscription' IS NOT NULL THEN expected:=jsonb_set(expected,'{subscription}',p_request->'subscription'); END IF;
  IF p_request IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Frozen observation request conflict' USING ERRCODE='22023'; END IF;
 ELSIF p_request->>'kind'='subscription' THEN
  IF p_request->>'attempt_id' IS NOT NULL OR p_request->>'checkout' IS NOT NULL OR p_request->>'terms_digest' IS NOT NULL
   OR p_request->>'trial_terms' IS NOT NULL OR nullif(p_request->>'subscription','') IS NULL
  THEN RAISE EXCEPTION 'Exact subscription request required' USING ERRCODE='22023'; END IF;
 ELSE RAISE EXCEPTION 'Unsupported observation request' USING ERRCODE='22023'; END IF;
 -- This namespace never takes person/tenant/subscription/event locks. Serialize
 -- begin only, then row claims; no provider reads occur inside this transaction.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_observation:'||t::text,0));
 SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_id OR
  (request_kind='trial_checkout' AND attempt_id=(p_request->>'attempt_id')::uuid) OR
  (request_kind='subscription' AND p_request->>'kind'='subscription' AND binding_id=b->>'binding_id' AND provider_subscription_id=p_request->>'subscription');
 IF FOUND THEN
  IF r.operation_id<>p_id OR r.request IS DISTINCT FROM p_request THEN RAISE EXCEPTION 'Observation replay conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(r);
 END IF;
 INSERT INTO public.billing_observation_operations(operation_id,tenant_id,binding_id,initiated_by,request_kind,attempt_id,reference_id,provider_customer_id,
 customer_operation_id,provider_checkout_id,provider_subscription_id,terms_digest,request)
 VALUES(p_id,t,b->>'binding_id',u,p_request->>'kind',(p_request->>'attempt_id')::uuid,c.reference_id,c.provider_customer_id,
 (p_request->>'customer_operation_id')::uuid,p_request->>'checkout',p_request->>'subscription',p_request->>'terms_digest',p_request) RETURNING * INTO r;
 RETURN to_jsonb(r);
END $$;
CREATE FUNCTION public.billing_observation_read(p_id uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_observation_operations; BEGIN
 PERFORM public.billing_observation_principal(); SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_id;
 IF NOT FOUND THEN RETURN NULL; END IF; RETURN to_jsonb(r)||jsonb_build_object('database_now',clock_timestamp());
END $$;
CREATE FUNCTION public.billing_observation_claim(p_id uuid,p_version bigint,p_token uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ DECLARE r public.billing_observation_operations;n timestamptz; BEGIN
 PERFORM public.billing_observation_principal(); SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_id FOR UPDATE;
 n:=clock_timestamp();
 IF NOT FOUND OR p_version IS NULL OR r.version<>p_version OR p_token IS NULL OR (r.claim_until IS NOT NULL AND r.claim_until>n)
 THEN RAISE EXCEPTION 'Observation claim stale or unavailable' USING ERRCODE='55000'; END IF;
 UPDATE public.billing_observation_operations SET claim_token=p_token,claim_until=n+interval '30 seconds',version=version+1,updated_at=n WHERE operation_id=p_id;
 RETURN public.billing_observation_read(p_id);
END $$;
CREATE FUNCTION public.billing_observation_notification(p_operation uuid,p_receipt uuid,p_event text,p_digest text,p_occurred timestamptz) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_observation_operations;e public.billing_observation_receipts;u uuid; BEGIN
 u:=public.billing_observation_principal();SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_operation FOR UPDATE;
 IF NOT FOUND OR p_occurred IS NULL OR p_occurred>clock_timestamp()+interval '30 seconds'
 THEN RAISE EXCEPTION 'Notification association unavailable' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_observation_receipts(receipt_id,operation_id,tenant_id,binding_id,provider_event_id,body_digest,occurred_at,authenticated_by)
 VALUES(p_receipt,p_operation,r.tenant_id,r.binding_id,p_event,p_digest,p_occurred,u) ON CONFLICT(binding_id,provider_event_id) DO NOTHING;
 SELECT * INTO e FROM public.billing_observation_receipts WHERE binding_id=r.binding_id AND provider_event_id=p_event;
 IF (e.operation_id,e.body_digest,e.occurred_at) IS DISTINCT FROM (p_operation,p_digest,p_occurred)
 THEN RAISE EXCEPTION 'Notification identity conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(e);
END $$;

-- No caller-supplied raw provider objects. Only this bounded normalized schema.
CREATE FUNCTION public.billing_observation_evidence(p jsonb) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v jsonb;k text;keys text[];period jsonb; BEGIN
 PERFORM public.billing_observation_object(p,ARRAY['customer','checkout','subscription','checkout_state','subscription_state','terms','trial','payment_method','recurring_authority','settlement','period_start','period_end','cancel_at_period_end','cancelled_at','capabilities']);
 IF octet_length(p::text)>65536 THEN RAISE EXCEPTION 'Observation evidence too large' USING ERRCODE='22023'; END IF;
 FOREACH k IN ARRAY ARRAY['terms','trial','payment_method','recurring_authority','settlement','capabilities'] LOOP
  v:=p->k;IF v IS NULL OR v='null'::jsonb THEN CONTINUE; END IF;
  keys:=CASE k WHEN 'terms' THEN ARRAY['amount','currency','interval_months','quantity','price']
   WHEN 'trial' THEN ARRAY['started_at','ends_at','cutoff']
   WHEN 'payment_method' THEN ARRAY['source','payment_method','readiness','observed_at']
   WHEN 'recurring_authority' THEN ARRAY['source','kind','readiness','consent','consent_reference','consent_terms_revision']
   WHEN 'settlement' THEN ARRAY['invoice','amount_paid','currency','payment_state','confirmed','initial','purpose','paid_at','coverage']
   ELSE ARRAY['hosted_checkout','reusable_payment_method','setup_without_charge','off_session_recurring','trial_subscription_setup','authenticated_webhooks','authoritative_reconciliation','idempotent_submission','cancellation'] END;
  PERFORM public.billing_observation_object(v,keys);
  IF EXISTS(SELECT FROM jsonb_each(v) x WHERE x.key<>'coverage' AND jsonb_typeof(x.value) IN ('object','array'))
  THEN RAISE EXCEPTION 'Scalar evidence required' USING ERRCODE='22023'; END IF;
  IF EXISTS(SELECT FROM jsonb_each(v) x WHERE x.key<>'coverage' AND length(x.value#>>'{}')>255)
  THEN RAISE EXCEPTION 'Bounded evidence required' USING ERRCODE='22023'; END IF;
  IF k='capabilities' AND EXISTS(SELECT FROM jsonb_each_text(v) x WHERE x.value NOT IN ('supported','unsupported','unknown','requires_approval'))
  THEN RAISE EXCEPTION 'Explicit capabilities required' USING ERRCODE='22023'; END IF;
  IF k='terms' AND ((v->>'amount')::numeric<0 OR (v->>'currency') !~ '^[A-Z]{3}$' OR (v->>'interval_months')::int<=0 OR (v->>'quantity')::int<=0)
  THEN RAISE EXCEPTION 'Precise commercial evidence required' USING ERRCODE='22023'; END IF;
  IF k='trial' AND ((v->>'ends_at')::timestamptz<=(v->>'started_at')::timestamptz OR (v->>'cutoff')::timestamptz IS DISTINCT FROM (v->>'ends_at')::timestamptz)
  THEN RAISE EXCEPTION 'Consistent trial window required' USING ERRCODE='22023'; END IF;
  IF k='settlement' THEN
   IF jsonb_typeof(v->'coverage') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'coverage')>100
   THEN RAISE EXCEPTION 'Bounded settlement periods required' USING ERRCODE='22023'; END IF;
   FOR period IN SELECT value FROM jsonb_array_elements(v->'coverage') LOOP
    IF jsonb_typeof(period)<>'array' OR jsonb_array_length(period)<>2 OR jsonb_typeof(period->0)<>'string' OR jsonb_typeof(period->1)<>'string'
     OR (period->>1)::timestamptz<=(period->>0)::timestamptz
    THEN RAISE EXCEPTION 'Explicit settlement periods required' USING ERRCODE='22023'; END IF;
   END LOOP;
  END IF;
 END LOOP;
 IF EXISTS(SELECT FROM jsonb_each(p) x WHERE x.key NOT IN ('terms','trial','payment_method','recurring_authority','settlement','capabilities') AND jsonb_typeof(x.value) IN ('object','array'))
 THEN RAISE EXCEPTION 'Scalar observation identity required' USING ERRCODE='22023'; END IF;
 IF p#>>'{recurring_authority,consent}'='recorded'
 THEN RAISE EXCEPTION 'Trusted local consent provenance is not implemented in B3' USING ERRCODE='22023'; END IF;
 EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow OR numeric_value_out_of_range THEN
  RAISE EXCEPTION 'Malformed normalized observation' USING ERRCODE='22023';
END $$;
CREATE FUNCTION public.billing_observation_record(p_id uuid,p_version bigint,p_token uuid,p_observation uuid,p_source text,p_receipt uuid,
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
 conflict:=r.has_conflict OR p_outcome='conflict' OR (old.observation_id IS NOT NULL AND old.evidence_digest<>d);
 INSERT INTO public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id,source,receipt_id,provenance_reference,observed_at,adapter_version,api_version,outcome,evidence,evidence_digest,claim_version,claim_token)
 VALUES(p_observation,p_id,r.tenant_id,r.binding_id,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence,d,p_version,p_token) RETURNING * INTO o;
 UPDATE public.billing_observation_operations SET state=CASE WHEN conflict THEN 'reconciliation_required' ELSE 'observed' END,has_conflict=conflict,
  last_observation_id=p_observation,claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
 RETURN to_jsonb(o);
END $$;

-- ACLs before ownership transfer; no PUBLIC entrypoints and no runtime role memberships.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature,p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'billing_observation_%' LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
  IF f.proname IN ('billing_observation_principal','billing_observation_trial_context','billing_observation_begin','billing_observation_read','billing_observation_claim','billing_observation_notification','billing_observation_record')
  THEN EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO ceopro_billing_observer',f.signature); END IF;
 END LOOP;
END $$;
GRANT CREATE ON SCHEMA public TO ceopro_observation_owner;
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'billing_observation_%' LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO ceopro_observation_owner',f.signature);
 END LOOP;
END $$;
REVOKE CREATE ON SCHEMA public FROM ceopro_observation_owner;
-- Remove creator grants made by this installer. Pre-existing operator-granted
-- installer membership must be revoked by its original grantor after install;
-- the guarded verifier checks that restoration. No runtime member is accepted.
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT roleid::regrole::text AS role,member::regrole::text AS member FROM pg_auth_members
  WHERE roleid IN ('ceopro_observation_owner'::regrole,'ceopro_billing_observer'::regrole) AND grantor=current_user::regrole LOOP
  EXECUTE format('REVOKE %I FROM %I',r.role,r.member);
 END LOOP;
END $$;
