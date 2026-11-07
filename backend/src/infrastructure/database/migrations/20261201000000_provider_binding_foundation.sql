-- Dormant foundation: no bindings, provider calls or historical backfills.
CREATE TABLE public.billing_gateway_bindings (
 binding_id text PRIMARY KEY CHECK(binding_id<>'' AND binding_id=btrim(binding_id)),
 provider text NOT NULL CHECK(provider<>'' AND provider=btrim(provider)),
 environment text NOT NULL CHECK(environment IN ('test','live')),
 merchant_account_id text NOT NULL CHECK(merchant_account_id<>'' AND merchant_account_id=btrim(merchant_account_id)),
 reservation_enabled boolean NOT NULL DEFAULT false,
 provenance text NOT NULL CHECK(provenance<>''),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(provider,environment,merchant_account_id)
);
CREATE UNIQUE INDEX binding_one_selected ON public.billing_gateway_bindings((true)) WHERE reservation_enabled;
ALTER TABLE public.billing_gateway_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_gateway_bindings FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_gateway_bindings FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_gateway_bindings TO ceopro_trial_issuer;
CREATE POLICY binding_issuer_read ON public.billing_gateway_bindings FOR SELECT TO ceopro_trial_issuer USING(true);
CREATE FUNCTION public.billing_binding_identity_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF (NEW.binding_id,NEW.provider,NEW.environment,NEW.merchant_account_id,NEW.created_at)
 IS DISTINCT FROM (OLD.binding_id,OLD.provider,OLD.environment,OLD.merchant_account_id,OLD.created_at)
 THEN RAISE EXCEPTION 'Gateway identity is immutable' USING ERRCODE='22023'; END IF;
 RETURN NEW; END $$;
REVOKE ALL ON FUNCTION public.billing_binding_identity_guard() FROM PUBLIC;
CREATE TRIGGER binding_identity BEFORE UPDATE ON public.billing_gateway_bindings
 FOR EACH ROW EXECUTE FUNCTION public.billing_binding_identity_guard();

CREATE TABLE public.billing_customer_references (
 reference_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 provider_customer_id text NOT NULL CHECK(provider_customer_id<>'' AND provider_customer_id=btrim(provider_customer_id)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,binding_id), UNIQUE(binding_id,provider_customer_id),
 UNIQUE(reference_id,tenant_id,binding_id)
);
ALTER TABLE public.billing_customer_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_customer_references FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_customer_references FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_customer_references TO ceopro_app,ceopro_billing_setup,ceopro_trial_issuer;
GRANT INSERT ON public.billing_customer_references TO ceopro_trial_issuer;
CREATE POLICY customer_reference_read ON public.billing_customer_references FOR SELECT
 USING(tenant_id=public.get_current_tenant());
CREATE POLICY customer_reference_insert ON public.billing_customer_references FOR INSERT TO ceopro_trial_issuer
 WITH CHECK(tenant_id=public.get_current_tenant());
CREATE FUNCTION public.billing_customer_reference_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'Scoped customer identity is immutable' USING ERRCODE='22023'; END $$;
REVOKE ALL ON FUNCTION public.billing_customer_reference_guard() FROM PUBLIC;
CREATE TRIGGER customer_reference_identity BEFORE UPDATE OR DELETE ON public.billing_customer_references
 FOR EACH ROW EXECUTE FUNCTION public.billing_customer_reference_guard();

-- Explicit operator-approved mappings; never infer merchant ownership of a
-- legacy Stripe price from the currently selected binding.
CREATE TABLE public.billing_price_references (
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 price_id uuid NOT NULL REFERENCES public.billing_plan_prices(price_id),
 provider_price_id text NOT NULL CHECK(provider_price_id<>'' AND provider_price_id=btrim(provider_price_id)),
 provenance text NOT NULL CHECK(provenance<>''),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(binding_id,price_id), UNIQUE(binding_id,provider_price_id),
 UNIQUE(price_id,binding_id,provider_price_id)
);
ALTER TABLE public.billing_price_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_price_references FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_price_references FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_price_references TO ceopro_trial_issuer;
CREATE POLICY price_reference_issuer ON public.billing_price_references FOR SELECT TO ceopro_trial_issuer USING(true);
CREATE TRIGGER price_reference_identity BEFORE UPDATE OR DELETE ON public.billing_price_references
 FOR EACH ROW EXECUTE FUNCTION public.billing_customer_reference_guard();

ALTER TABLE public.billing_checkout_attempts
 ADD COLUMN gateway_binding_id text REFERENCES public.billing_gateway_bindings(binding_id),
 ADD COLUMN provider_idempotency_key text,
 ADD COLUMN provider_session_id text,
 ADD COLUMN first_submitted_at timestamptz,
 ADD COLUMN replay_window_seconds integer,
 ADD CONSTRAINT checkout_scope_complete CHECK(
  (gateway_binding_id IS NULL AND provider_idempotency_key IS NULL AND provider_session_id IS NULL
   AND first_submitted_at IS NULL AND replay_window_seconds IS NULL)
  OR (gateway_binding_id IS NOT NULL AND nullif(btrim(provider_idempotency_key),'') IS NOT NULL
   AND (replay_window_seconds IS NULL OR replay_window_seconds>0)
   AND (provider_session_id IS NULL OR nullif(btrim(provider_session_id),'') IS NOT NULL)
   AND (first_submitted_at IS NULL OR (provider_params IS NOT NULL AND replay_window_seconds IS NOT NULL)))),
 ADD CONSTRAINT checkout_scope_identity UNIQUE(attempt_id,tenant_id,gateway_binding_id);
CREATE UNIQUE INDEX checkout_scoped_key ON public.billing_checkout_attempts(gateway_binding_id,provider_idempotency_key)
 WHERE gateway_binding_id IS NOT NULL;
CREATE UNIQUE INDEX checkout_scoped_session ON public.billing_checkout_attempts(gateway_binding_id,provider_session_id)
 WHERE provider_session_id IS NOT NULL;
CREATE FUNCTION public.billing_checkout_scope_guard() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF (OLD.gateway_binding_id IS NOT NULL AND current_user<>'ceopro_trial_issuer' AND NEW IS DISTINCT FROM OLD)
 OR (OLD.gateway_binding_id IS NULL AND NEW.gateway_binding_id IS NOT NULL)
 OR (OLD.gateway_binding_id IS NOT NULL AND (
  (NEW.gateway_binding_id,NEW.provider_idempotency_key) IS DISTINCT FROM (OLD.gateway_binding_id,OLD.provider_idempotency_key)
  OR (OLD.provider_session_id IS NOT NULL AND NEW.provider_session_id IS DISTINCT FROM OLD.provider_session_id)
  OR (OLD.first_submitted_at IS NOT NULL AND NEW.first_submitted_at IS DISTINCT FROM OLD.first_submitted_at)
  OR (OLD.replay_window_seconds IS NOT NULL AND NEW.replay_window_seconds IS DISTINCT FROM OLD.replay_window_seconds)
  OR NEW.stripe_session_id IS DISTINCT FROM OLD.stripe_session_id))
 THEN RAISE EXCEPTION 'Checkout scope is immutable' USING ERRCODE='22023'; END IF;
 RETURN NEW; END $$;
REVOKE ALL ON FUNCTION public.billing_checkout_scope_guard() FROM PUBLIC;
CREATE TRIGGER checkout_scope_identity BEFORE UPDATE ON public.billing_checkout_attempts
 FOR EACH ROW EXECUTE FUNCTION public.billing_checkout_scope_guard();

-- No existing role attributes, memberships, issuance functions or ACLs are replaced.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_trial_issuer' AND NOT rolcanlogin AND NOT rolsuper
  AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication)
 OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_trial_issuer'))
 OR has_schema_privilege('ceopro_trial_issuer','public','CREATE')
 THEN RAISE EXCEPTION 'Restricted trial issuer prerequisites required'; END IF;
END $$;
CREATE FUNCTION public.billing_reservation_principal() RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant(); u uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF session_user<>'ceopro_billing_setup' OR public.keel_active_principal(u,t) IS DISTINCT FROM TRUE
 OR NOT EXISTS(SELECT FROM public.tenant_users WHERE tenant_id=t AND user_id=u AND role_key IN ('owner','admin','accountant')
  AND removed_at IS NULL AND platform_suspended_at IS NULL)
 THEN RAISE EXCEPTION 'Restricted authenticated billing principal required' USING ERRCODE='42501'; END IF;
 RETURN u;
END $$;
CREATE FUNCTION public.billing_selected_gateway_binding() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,pg_temp AS $$ DECLARE b jsonb; n integer; BEGIN
 PERFORM public.billing_reservation_principal();
 SELECT count(*) INTO n FROM public.billing_gateway_bindings WHERE reservation_enabled;
 IF n<>1 THEN RAISE EXCEPTION 'Exactly one platform-approved binding required' USING ERRCODE='22023'; END IF;
 SELECT jsonb_build_object('binding_id',binding_id,'provider',provider,'environment',environment,
  'merchant_account_id',merchant_account_id) INTO b FROM public.billing_gateway_bindings WHERE reservation_enabled;
 RETURN b;
END $$;
CREATE FUNCTION public.billing_record_customer_reference(p_binding text,p_customer text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant(); r public.billing_customer_references;
BEGIN
 PERFORM public.billing_reservation_principal();
 IF (public.billing_selected_gateway_binding()->>'binding_id') IS DISTINCT FROM p_binding
 THEN RAISE EXCEPTION 'Server-selected binding required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.billing_customer_references(tenant_id,binding_id,provider_customer_id) VALUES(t,p_binding,p_customer)
 ON CONFLICT(tenant_id,binding_id) DO NOTHING;
 SELECT * INTO r FROM public.billing_customer_references WHERE tenant_id=t AND binding_id=p_binding;
 IF r.provider_customer_id IS DISTINCT FROM p_customer
 THEN RAISE EXCEPTION 'Customer reference conflict' USING ERRCODE='22023'; END IF;
 RETURN to_jsonb(r);
END $$;
-- Set ACLs while the installer still owns the new functions. A restricted
-- installer loses grant authority after ownership transfer.
REVOKE ALL ON FUNCTION public.billing_reservation_principal(),public.billing_selected_gateway_binding(),
 public.billing_record_customer_reference(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_selected_gateway_binding(),public.billing_record_customer_reference(text,text)
 TO ceopro_billing_setup;
GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_reservation_principal() OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_selected_gateway_binding() OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_record_customer_reference(text,text) OWNER TO ceopro_trial_issuer;
REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer;
