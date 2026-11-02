-- Durable provider-customer CREATE coordination. No commercial access is granted.
CREATE TABLE public.billing_customer_operations (
 operation_id UUID PRIMARY KEY,
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK(provider<>''),
 idempotency_key TEXT NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 255),
 request_params JSONB,
 replay_window_seconds INTEGER NOT NULL CHECK(replay_window_seconds>0),
 state TEXT NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared','submitted','unknown','succeeded','rejected','legacy_unresolved')),
 provider_customer_id TEXT,
 first_submitted_at TIMESTAMPTZ,
 last_error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK((state='succeeded')=(provider_customer_id IS NOT NULL)),
 CHECK(request_params IS NOT NULL OR state IN ('legacy_unresolved','succeeded')),
 UNIQUE(provider,idempotency_key),
 UNIQUE(provider,provider_customer_id)
);
CREATE UNIQUE INDEX billing_customer_operation_effective ON public.billing_customer_operations(tenant_id,provider) WHERE state<>'rejected';
ALTER TABLE public.billing_customer_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_customer_operations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_customer_operations FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_customer_operations TO ceopro_billing_setup;
GRANT INSERT(operation_id,tenant_id,provider,idempotency_key,request_params,replay_window_seconds) ON public.billing_customer_operations TO ceopro_billing_setup;
GRANT UPDATE(state,provider_customer_id,first_submitted_at,last_error,updated_at) ON public.billing_customer_operations TO ceopro_billing_setup;
DO $$ DECLARE g TEXT:=$guard$tenant_id=public.get_current_tenant()
 AND public.keel_active_principal(nullif(current_setting('app.current_user_id',true),'')::uuid,public.get_current_tenant())
 AND EXISTS(SELECT FROM public.tenant_users m WHERE m.tenant_id=public.get_current_tenant()
 AND m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid AND m.role_key IN ('owner','admin','accountant')
 AND m.removed_at IS NULL AND m.platform_suspended_at IS NULL)$guard$;
BEGIN
 EXECUTE format('CREATE POLICY customer_operation_scope ON public.billing_customer_operations TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',g,g);
 EXECUTE format('CREATE POLICY customer_operation_boundary ON public.billing_customer_operations AS RESTRICTIVE TO ceopro_billing_setup USING(%s) WITH CHECK(%s)',g,g);
END $$;
CREATE FUNCTION public.billing_customer_operation_immutable() RETURNS TRIGGER
 LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF (NEW.operation_id,NEW.tenant_id,NEW.provider,NEW.idempotency_key,NEW.request_params,NEW.replay_window_seconds,NEW.created_at)
  IS DISTINCT FROM (OLD.operation_id,OLD.tenant_id,OLD.provider,OLD.idempotency_key,OLD.request_params,OLD.replay_window_seconds,OLD.created_at)
  OR (OLD.first_submitted_at IS NOT NULL AND NEW.first_submitted_at IS DISTINCT FROM OLD.first_submitted_at)
  OR (OLD.state IN ('succeeded','rejected') AND NEW IS DISTINCT FROM OLD)
  OR (OLD.state='legacy_unresolved' AND NEW.state NOT IN ('legacy_unresolved','succeeded'))
 THEN RAISE EXCEPTION 'Customer CREATE identity and frozen evidence are immutable' USING ERRCODE='22023'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_customer_operation_immutable() FROM PUBLIC;
CREATE TRIGGER billing_customer_operation_frozen BEFORE UPDATE ON public.billing_customer_operations
 FOR EACH ROW EXECUTE FUNCTION public.billing_customer_operation_immutable();

-- Existing mappings/trials/subscriptions are untouched. Unmapped historical
-- attempts have UNKNOWN original payloads; never invent one under their old key.
INSERT INTO public.billing_customer_operations(operation_id,tenant_id,provider,idempotency_key,request_params,replay_window_seconds,state,created_at)
 SELECT gen_random_uuid(),a.tenant_id,'stripe','apex-customer-'||a.tenant_id::text,NULL,82800,'legacy_unresolved',min(a.created_at)
 FROM public.billing_checkout_attempts a WHERE NOT EXISTS(SELECT FROM public.billing_customers c WHERE c.tenant_id=a.tenant_id)
 GROUP BY a.tenant_id;
