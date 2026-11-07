-- Dormant reservations only. Legacy issuance and reconciliation are untouched.
CREATE TABLE public.billing_trial_checkouts (
 attempt_id uuid PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 started_by_user_id uuid NOT NULL REFERENCES public.users(user_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 plan_key text NOT NULL REFERENCES public.usage_plans(plan_key),
 period_code text NOT NULL,
 interval_months integer NOT NULL CHECK(interval_months>0),
 currency text NOT NULL CHECK(currency~'^[A-Z]{3}$'),
 trial_duration_days integer NOT NULL CHECK(trial_duration_days>0),
 price_id uuid NOT NULL REFERENCES public.billing_plan_prices(price_id),
 provider_price_id text NOT NULL CHECK(provider_price_id<>''),
 approved_amount numeric NOT NULL CHECK(approved_amount>=0 AND approved_amount::text NOT IN ('NaN','Infinity')),
 catalog_revision_id text NOT NULL,
 approved_terms jsonb NOT NULL CHECK(jsonb_typeof(approved_terms)='object'),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','released')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 released_at timestamptz,
 release_reason text CHECK(release_reason='unsubmitted'),
 CHECK((state='pending' AND released_at IS NULL AND release_reason IS NULL)
  OR (state='released' AND released_at IS NOT NULL AND release_reason IS NOT NULL)),
 CHECK(((approved_terms->>'tenant_id')=tenant_id::text AND (approved_terms->>'started_by_user_id')=started_by_user_id::text
  AND (approved_terms#>>'{binding,binding_id}')=binding_id AND approved_terms->>'plan_key'=plan_key
  AND approved_terms->>'period_code'=period_code AND (approved_terms->>'interval_months')::int=interval_months
  AND approved_terms->>'currency'=currency AND (approved_terms->>'trial_duration_days')::int=trial_duration_days
  AND (approved_terms->>'price_id')::uuid=price_id AND approved_terms->>'provider_price_id'=provider_price_id
  AND (approved_terms->>'approved_amount')::numeric=approved_amount AND approved_terms->>'catalog_revision_id'=catalog_revision_id) IS TRUE),
 FOREIGN KEY(price_id,binding_id,provider_price_id) REFERENCES public.billing_price_references(price_id,binding_id,provider_price_id),
 FOREIGN KEY(attempt_id,tenant_id,binding_id) REFERENCES public.billing_checkout_attempts(attempt_id,tenant_id,gateway_binding_id)
);
CREATE UNIQUE INDEX trial_checkout_pending_tenant ON public.billing_trial_checkouts(tenant_id) WHERE state='pending';
CREATE UNIQUE INDEX trial_checkout_pending_person ON public.billing_trial_checkouts(started_by_user_id) WHERE state='pending';
ALTER TABLE public.billing_trial_checkouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_trial_checkouts FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_trial_checkouts FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_trial_checkouts TO ceopro_app,ceopro_billing_setup,ceopro_trial_issuer;
GRANT INSERT,UPDATE(state,released_at,release_reason) ON public.billing_trial_checkouts TO ceopro_trial_issuer;
CREATE POLICY reservation_tenant_read ON public.billing_trial_checkouts FOR SELECT TO ceopro_app,ceopro_billing_setup
 USING(tenant_id=public.get_current_tenant());
CREATE POLICY reservation_issuer ON public.billing_trial_checkouts TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant() OR started_by_user_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=public.get_current_tenant());
GRANT SELECT ON public.billing_checkout_attempts,public.billing_plan_prices,public.usage_features,
 public.usage_plan_limits,public.usage_plan_entitlements,public.entitlement_catalog_version TO ceopro_trial_issuer;
GRANT INSERT(attempt_id,tenant_id,request_key,plan_key,period_code,gateway_binding_id,provider_idempotency_key),
 UPDATE(provider_params,provider_session_id,first_submitted_at,replay_window_seconds,state,updated_at)
 ON public.billing_checkout_attempts TO ceopro_trial_issuer;
CREATE POLICY reservation_attempt_issuer ON public.billing_checkout_attempts TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_trial_reservation_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF OLD.state='released' OR
 (NEW.attempt_id,NEW.tenant_id,NEW.started_by_user_id,NEW.binding_id,NEW.plan_key,NEW.period_code,NEW.interval_months,
  NEW.currency,NEW.trial_duration_days,NEW.price_id,NEW.provider_price_id,NEW.approved_amount,NEW.catalog_revision_id,NEW.approved_terms,NEW.created_at)
 IS DISTINCT FROM
 (OLD.attempt_id,OLD.tenant_id,OLD.started_by_user_id,OLD.binding_id,OLD.plan_key,OLD.period_code,OLD.interval_months,
  OLD.currency,OLD.trial_duration_days,OLD.price_id,OLD.provider_price_id,OLD.approved_amount,OLD.catalog_revision_id,OLD.approved_terms,OLD.created_at)
 THEN RAISE EXCEPTION 'Approved reservation terms are immutable' USING ERRCODE='22023'; END IF;
 RETURN NEW; END $$;
REVOKE ALL ON FUNCTION public.billing_trial_reservation_guard() FROM PUBLIC;
CREATE TRIGGER trial_reservation_identity BEFORE UPDATE ON public.billing_trial_checkouts
 FOR EACH ROW EXECUTE FUNCTION public.billing_trial_reservation_guard();

CREATE FUNCTION public.billing_trial_checkout_terms(p_plan text,p_period text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE u uuid; b jsonb; s jsonb; BEGIN
 u:=public.billing_reservation_principal(); b:=public.billing_selected_gateway_binding();
 -- Only the existing Stripe catalog is supported; no hypothetical provider prices.
 IF b->>'provider'<>'stripe' THEN RAISE EXCEPTION 'Provider price mapping unavailable' USING ERRCODE='22023'; END IF;
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

CREATE FUNCTION public.billing_reserve_trial_checkout(p_attempt uuid,p_terms jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE u uuid; t uuid:=public.get_current_tenant(); r public.billing_trial_checkouts; s jsonb;
BEGIN
 u:=public.billing_reservation_principal();
 -- Preserve the established person-before-tenant order. Never acquire the
 -- Checkout session lock: the existing unique pending index resolves that race.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt FOR UPDATE;
 IF FOUND THEN
  IF r.tenant_id<>t OR r.started_by_user_id<>u OR r.approved_terms IS DISTINCT FROM p_terms OR r.state<>'pending'
  THEN RAISE EXCEPTION 'Reservation replay conflict' USING ERRCODE='22023'; END IF;
  RETURN to_jsonb(r);
 END IF;
 IF EXISTS(SELECT FROM public.billing_trials WHERE tenant_id=t OR started_by_user_id=u)
 OR EXISTS(SELECT FROM public.tenant_plan_assignments WHERE tenant_id=t)
 OR EXISTS(SELECT FROM public.billing_subscriptions WHERE tenant_id=t)
 OR EXISTS(SELECT FROM public.billing_trial_checkouts WHERE state='pending' AND (tenant_id=t OR started_by_user_id=u))
 THEN RAISE EXCEPTION 'Trial eligibility unavailable' USING ERRCODE='22023'; END IF;
 s:=public.billing_trial_checkout_terms(p_terms->>'plan_key',p_terms->>'period_code');
 IF s IS DISTINCT FROM p_terms THEN RAISE EXCEPTION 'Approved trial terms changed' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_checkout_attempts(attempt_id,tenant_id,request_key,plan_key,period_code,gateway_binding_id,provider_idempotency_key)
 VALUES(p_attempt,t,p_attempt::text,s->>'plan_key',s->>'period_code',s#>>'{binding,binding_id}','keel-trial-checkout-'||p_attempt::text);
 INSERT INTO public.billing_trial_checkouts(attempt_id,tenant_id,started_by_user_id,binding_id,plan_key,period_code,
  interval_months,currency,trial_duration_days,price_id,provider_price_id,approved_amount,catalog_revision_id,approved_terms)
 VALUES(p_attempt,t,u,s#>>'{binding,binding_id}',s->>'plan_key',s->>'period_code',(s->>'interval_months')::int,
  s->>'currency',(s->>'trial_duration_days')::int,(s->>'price_id')::uuid,s->>'provider_price_id',
  (s->>'approved_amount')::numeric,s->>'catalog_revision_id',s) RETURNING * INTO r;
 RETURN to_jsonb(r);
END $$;

CREATE FUNCTION public.billing_trial_operation(p_attempt uuid,p_action text,p_payload jsonb DEFAULT NULL,p_window integer DEFAULT NULL,p_session text DEFAULT NULL)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE u uuid; t uuid:=public.get_current_tenant(); r public.billing_trial_checkouts; a public.billing_checkout_attempts;
BEGIN
 u:=public.billing_reservation_principal();
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial:'||u::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_trial_tenant:'||t::text,0));
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=p_attempt AND tenant_id=t FOR UPDATE;
 IF NOT FOUND OR r.started_by_user_id<>u OR r.state<>'pending'
 THEN RAISE EXCEPTION 'Owned pending reservation required' USING ERRCODE='42501'; END IF;
 SELECT * INTO a FROM public.billing_checkout_attempts WHERE attempt_id=p_attempt AND tenant_id=t FOR UPDATE;
 IF a.gateway_binding_id IS DISTINCT FROM r.binding_id OR a.state NOT IN ('preparing','open')
 THEN RAISE EXCEPTION 'Checkout scope conflict' USING ERRCODE='22023'; END IF;
 IF p_action='prepare' THEN
  IF p_payload IS NULL OR jsonb_typeof(p_payload)<>'object' OR p_window IS NULL OR p_window<=0
   OR (a.provider_params IS NOT NULL AND a.provider_params IS DISTINCT FROM p_payload)
   OR (a.replay_window_seconds IS NOT NULL AND a.replay_window_seconds<>p_window)
  THEN RAISE EXCEPTION 'Frozen request conflict' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_checkout_attempts SET provider_params=p_payload,replay_window_seconds=p_window WHERE attempt_id=p_attempt;
 ELSIF p_action='submitted' THEN
  IF a.provider_params IS NULL OR a.replay_window_seconds IS NULL
  THEN RAISE EXCEPTION 'Prepared request required' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_checkout_attempts SET first_submitted_at=coalesce(first_submitted_at,clock_timestamp()) WHERE attempt_id=p_attempt;
 ELSIF p_action='session' THEN
  IF a.first_submitted_at IS NULL OR nullif(btrim(p_session),'') IS NULL
   OR (a.provider_session_id IS NOT NULL AND a.provider_session_id<>p_session)
  THEN RAISE EXCEPTION 'Submitted matching session required' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_checkout_attempts SET provider_session_id=p_session,state='open' WHERE attempt_id=p_attempt;
 ELSIF p_action='release' THEN
  IF a.provider_params IS NOT NULL OR a.first_submitted_at IS NOT NULL OR a.provider_session_id IS NOT NULL
  THEN RAISE EXCEPTION 'Authoritative reconciliation required' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_trial_checkouts SET state='released',released_at=clock_timestamp(),release_reason='unsubmitted' WHERE attempt_id=p_attempt;
  UPDATE public.billing_checkout_attempts SET state='expired' WHERE attempt_id=p_attempt;
 ELSE RAISE EXCEPTION 'Unsupported reservation operation' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM public.billing_checkout_attempts WHERE attempt_id=p_attempt;
 RETURN to_jsonb(a);
END $$;
-- Set ACLs while the installer still owns the new functions. A restricted
-- installer loses grant authority after ownership transfer.
REVOKE ALL ON FUNCTION public.billing_trial_checkout_terms(text,text),public.billing_reserve_trial_checkout(uuid,jsonb),
 public.billing_trial_operation(uuid,text,jsonb,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_trial_checkout_terms(text,text),public.billing_reserve_trial_checkout(uuid,jsonb),
 public.billing_trial_operation(uuid,text,jsonb,integer,text) TO ceopro_billing_setup;
GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_trial_checkout_terms(text,text) OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_reserve_trial_checkout(uuid,jsonb) OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_trial_operation(uuid,text,jsonb,integer,text) OWNER TO ceopro_trial_issuer;
REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer;
