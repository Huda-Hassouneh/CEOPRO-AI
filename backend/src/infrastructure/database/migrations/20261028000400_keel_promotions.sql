-- Phase 2B managed promotions. This is a separate eligibility/redemption
-- authority only: Stripe remains the monetary authority and the existing
-- billing_payments table remains the invoice/payment ledger.

CREATE TABLE IF NOT EXISTS public.billing_promotions (
    promotion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'disabled')),
    terms JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(terms) = 'object'),
    stripe_coupon_id TEXT,
    stripe_promotion_code_id TEXT UNIQUE,
    approval_reference TEXT,
    approved_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    created_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    updated_by UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_billing_promotions_code
        CHECK (code = upper(btrim(code)) AND code ~ '^[A-Z0-9][A-Z0-9_-]{0,99}$'),
    CONSTRAINT ck_billing_promotions_active_approval
        CHECK (status <> 'active' OR COALESCE((
            approval_reference IS NOT NULL AND length(btrim(approval_reference)) > 0
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND stripe_coupon_id IS NOT NULL AND stripe_promotion_code_id IS NOT NULL
            AND terms ?& ARRAY['discount_type','discount_value','currency','starts_at','expires_at',
                               'max_uses','max_uses_per_tenant','invoice_scope',
                               'stripe_coupon_id','stripe_promotion_code_id']
            AND terms->>'stripe_coupon_id' = stripe_coupon_id
            AND terms->>'stripe_promotion_code_id' = stripe_promotion_code_id
            AND terms->>'discount_type' IN ('percent','fixed_amount')
            AND (terms->>'discount_value') ~ '^[0-9]+(\.[0-9]+)?$'
            AND (terms->>'discount_value')::numeric > 0
            AND (terms->>'discount_type' <> 'percent' OR (terms->>'discount_value')::numeric <= 100)
            AND (terms->>'currency') ~ '^[A-Z]{3}$'
            AND terms->>'invoice_scope' = 'initial_subscription'
            AND (terms->'max_uses' = 'null'::jsonb OR (terms->>'max_uses') ~ '^[1-9][0-9]*$')
            AND (terms->'max_uses_per_tenant' = 'null'::jsonb OR (terms->>'max_uses_per_tenant') ~ '^[1-9][0-9]*$')
            AND (terms->'starts_at' = 'null'::jsonb OR (terms->>'starts_at')::timestamptz IS NOT NULL)
            AND (terms->'expires_at' = 'null'::jsonb OR (terms->>'expires_at')::timestamptz IS NOT NULL)
            AND (terms->'starts_at' = 'null'::jsonb OR terms->'expires_at' = 'null'::jsonb
                 OR (terms->>'starts_at')::timestamptz < (terms->>'expires_at')::timestamptz)
        ), FALSE))
);

CREATE TABLE IF NOT EXISTS public.billing_promotion_plans (
    promotion_id UUID NOT NULL REFERENCES public.billing_promotions(promotion_id) ON DELETE RESTRICT,
    plan_key VARCHAR(50) NOT NULL REFERENCES public.usage_plans(plan_key) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (promotion_id, plan_key)
);

CREATE TABLE IF NOT EXISTS public.billing_promotion_redemptions (
    redemption_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    promotion_id UUID NOT NULL REFERENCES public.billing_promotions(promotion_id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','settled','rejected','reconciliation_required')),
    request_key TEXT NOT NULL CHECK (length(request_key) BETWEEN 1 AND 200),
    request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    plan_key VARCHAR(50) NOT NULL REFERENCES public.usage_plans(plan_key) ON DELETE RESTRICT,
    period_code VARCHAR(20) NOT NULL,
    stripe_checkout_session_id TEXT UNIQUE,
    checkout_request_started_at TIMESTAMPTZ,
    stripe_subscription_id TEXT,
    stripe_initial_invoice_id TEXT UNIQUE,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMPTZ,
    CONSTRAINT uq_billing_promotion_redemption_request
        UNIQUE (tenant_id, promotion_id, request_key),
    CONSTRAINT uq_billing_promotion_redemption_tenant_identity
        UNIQUE (tenant_id, redemption_id),
    CONSTRAINT ck_billing_promotion_redemption_settled
        CHECK ((state = 'settled') = (settled_at IS NOT NULL AND stripe_initial_invoice_id IS NOT NULL
                                      AND stripe_subscription_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_billing_promotion_redemptions_global_state
    ON public.billing_promotion_redemptions (promotion_id, state);
CREATE INDEX IF NOT EXISTS idx_billing_promotion_redemptions_tenant_state
    ON public.billing_promotion_redemptions (tenant_id, promotion_id, state);
CREATE INDEX IF NOT EXISTS idx_billing_promotion_redemptions_subscription
    ON public.billing_promotion_redemptions (stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.billing_promotion_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    redemption_id UUID NOT NULL,
    actor_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    stripe_event_id TEXT,
    reason_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_billing_promotion_event_redemption_tenant
        FOREIGN KEY (tenant_id, redemption_id)
        REFERENCES public.billing_promotion_redemptions(tenant_id, redemption_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_promotion_event_stripe_transition
    ON public.billing_promotion_events (redemption_id, stripe_event_id, event_type)
    WHERE stripe_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_billing_promotion_events_tenant
    ON public.billing_promotion_events (tenant_id, redemption_id, created_at);

-- Customer data follows the existing tenant deletion cascade used by billing
-- records. There is no separate promotion-retention clock or cleanup policy.
ALTER TABLE public.billing_promotions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_promotions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_promotions_active_read ON public.billing_promotions;
CREATE POLICY billing_promotions_active_read ON public.billing_promotions
    FOR SELECT TO ceopro_app USING (status = 'active');

ALTER TABLE public.billing_promotion_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_promotion_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_promotion_plans_active_read ON public.billing_promotion_plans;
CREATE POLICY billing_promotion_plans_active_read ON public.billing_promotion_plans
    FOR SELECT TO ceopro_app USING (EXISTS (
        SELECT 1 FROM public.billing_promotions p
         WHERE p.promotion_id = billing_promotion_plans.promotion_id AND p.status = 'active'
    ));

ALTER TABLE public.billing_promotion_redemptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_promotion_redemptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_promotion_redemptions_tenant_read ON public.billing_promotion_redemptions;
CREATE POLICY billing_promotion_redemptions_tenant_read ON public.billing_promotion_redemptions
    FOR SELECT TO ceopro_app USING (tenant_id = public.get_current_tenant());

ALTER TABLE public.billing_promotion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_promotion_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_promotion_events_tenant_read ON public.billing_promotion_events;
CREATE POLICY billing_promotion_events_tenant_read ON public.billing_promotion_events
    FOR SELECT TO ceopro_app USING (tenant_id = public.get_current_tenant());

REVOKE ALL ON public.billing_promotions, public.billing_promotion_plans,
    public.billing_promotion_redemptions, public.billing_promotion_events FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON public.billing_promotions, public.billing_promotion_plans,
            public.billing_promotion_redemptions, public.billing_promotion_events FROM ceopro_app;
        GRANT SELECT ON public.billing_promotions, public.billing_promotion_plans,
            public.billing_promotion_redemptions, public.billing_promotion_events TO ceopro_app;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.billing_promotion_event_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Preserve the event when its actor account is removed. The only allowed
    -- row update is the FK's actor_user_id anonymization; all evidence fields
    -- remain unchanged. ceopro_app has no UPDATE privilege on this table.
    IF TG_OP = 'UPDATE'
       AND OLD.actor_user_id IS NOT NULL
       AND NEW.actor_user_id IS NULL
       AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id') THEN
        RETURN NEW;
    END IF;

    -- Tenant deletion follows the existing billing cascade. The FK-driven
    -- child deletion is allowed, while direct event deletion remains blocked.
    IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;

    RAISE EXCEPTION 'billing_promotion_events is append-only' USING ERRCODE='42501';
END $$;
REVOKE ALL ON FUNCTION public.billing_promotion_event_immutable() FROM PUBLIC;
DROP TRIGGER IF EXISTS billing_promotion_events_immutable ON public.billing_promotion_events;
CREATE TRIGGER billing_promotion_events_immutable
    BEFORE UPDATE OR DELETE ON public.billing_promotion_events
    FOR EACH ROW EXECUTE FUNCTION public.billing_promotion_event_immutable();
DROP TRIGGER IF EXISTS billing_promotion_events_immutable_truncate ON public.billing_promotion_events;
CREATE TRIGGER billing_promotion_events_immutable_truncate
    BEFORE TRUNCATE ON public.billing_promotion_events
    FOR EACH STATEMENT EXECUTE FUNCTION public.billing_promotion_event_immutable();
