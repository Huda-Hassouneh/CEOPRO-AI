-- Forward-only reservation identity; no changes to existing contracts or prices.
CREATE TABLE public.billing_checkout_attempts (
    attempt_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    request_key TEXT NOT NULL,
    plan_key TEXT NOT NULL,
    period_code TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'preparing' CHECK (state IN ('preparing','open','expired')),
    stripe_session_id TEXT UNIQUE,
    provider_params JSONB CHECK (provider_params IS NULL OR jsonb_typeof(provider_params)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX billing_checkout_one_pending_per_tenant ON public.billing_checkout_attempts(tenant_id)
    WHERE state IN ('preparing','open');
ALTER TABLE public.billing_checkout_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_checkout_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY billing_checkout_tenant_read ON public.billing_checkout_attempts FOR SELECT TO ceopro_app
    USING (tenant_id = nullif(current_setting('app.current_tenant_id', true),'')::uuid);
REVOKE ALL ON public.billing_checkout_attempts FROM PUBLIC,ceopro_app;
GRANT SELECT ON public.billing_checkout_attempts TO ceopro_app;
CREATE FUNCTION public.billing_checkout_attempt_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id OR OLD.request_key IS DISTINCT FROM NEW.request_key
       OR OLD.plan_key IS DISTINCT FROM NEW.plan_key OR OLD.period_code IS DISTINCT FROM NEW.period_code
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
       OR (OLD.provider_params IS NOT NULL AND OLD.provider_params IS DISTINCT FROM NEW.provider_params)
       OR (OLD.stripe_session_id IS NOT NULL AND OLD.stripe_session_id IS DISTINCT FROM NEW.stripe_session_id)
       OR OLD.state='expired' THEN
        RAISE EXCEPTION 'Checkout reservation evidence is immutable';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER billing_checkout_attempt_immutable BEFORE UPDATE ON public.billing_checkout_attempts
    FOR EACH ROW EXECUTE FUNCTION public.billing_checkout_attempt_guard();
