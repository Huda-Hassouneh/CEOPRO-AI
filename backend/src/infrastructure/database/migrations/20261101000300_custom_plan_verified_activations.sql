-- One durable activation proof per accepted quote revision and Stripe subscription.
-- Written only by the existing signature-verified webhook authority.
CREATE TABLE IF NOT EXISTS public.billing_custom_contract_activations (
 activation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 quote_id UUID NOT NULL,
 revision_id UUID NOT NULL,
 attempt_id UUID NOT NULL,
 stripe_subscription_id TEXT NOT NULL UNIQUE,
 stripe_invoice_id TEXT NOT NULL UNIQUE,
 provider_event_id TEXT NOT NULL UNIQUE,
 invoice_paid_at TIMESTAMPTZ NOT NULL,
 activated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(tenant_id,quote_id,revision_id),
 FOREIGN KEY(tenant_id,quote_id) REFERENCES public.billing_custom_quotes(tenant_id,quote_id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,quote_id,revision_id) REFERENCES public.billing_custom_quote_revisions(tenant_id,quote_id,revision_id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,attempt_id) REFERENCES public.billing_custom_quote_checkout_attempts(tenant_id,attempt_id) ON DELETE RESTRICT
);
ALTER TABLE public.billing_custom_contract_activations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_custom_contract_activations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_custom_contract_activations FROM PUBLIC,ceopro_app;
