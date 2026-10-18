-- Billing: plan prices, Stripe customers/subscriptions, signed webhook audit,
-- payments, and once-per-company trials.
--
-- Design ported from the CEOPRO backend's Stripe integration (checkout in
-- subscription mode, webhooks as the source of truth, a permanent price ->
-- plan/period map) with its known gaps closed: one current subscription per
-- company (partial unique index), one trial per company, webhook events
-- deduplicated atomically by event id, and stale events ignored by comparing
-- the event creation time.
--
-- tenant_plan_assignments stays the single place the rest of the app reads a
-- company's plan and status from; billing keeps it in step.

-- Plan catalog: price, currency, trial and ordering live with the plan.
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS monthly_price NUMERIC(10, 2) CHECK (monthly_price IS NULL OR monthly_price >= 0);
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS currency CHAR(3) NOT NULL DEFAULT 'USD';
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS trial_days INT NOT NULL DEFAULT 0 CHECK (trial_days >= 0);
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS tier_level INT NOT NULL DEFAULT 0;
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS self_serve BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS display_name_ar VARCHAR(100);

UPDATE usage_plans SET monthly_price = 49, trial_days = 0, tier_level = 1, self_serve = TRUE, display_name_ar = 'الأساسية' WHERE plan_key = 'standard';
UPDATE usage_plans SET monthly_price = 99, trial_days = 14, tier_level = 2, self_serve = TRUE, display_name_ar = 'الاحترافية' WHERE plan_key = 'pro';
-- Custom capacity is agreed with each company and assigned by an operator.
UPDATE usage_plans SET monthly_price = NULL, trial_days = 0, tier_level = 3, self_serve = FALSE, display_name_ar = 'المخصصة' WHERE plan_key = 'custom';

-- Billing periods offered for each self-serve plan. amount is the total
-- charged per period. stripe_price_id is filled by
-- scripts/stripe_sync_catalog.py; a retired price stays here so webhooks for
-- older subscriptions still resolve to their plan and period.
CREATE TABLE IF NOT EXISTS billing_plan_prices (
    price_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key) ON DELETE CASCADE,
    period_code VARCHAR(20) NOT NULL CHECK (period_code IN ('monthly', 'three-months', 'six-months', 'yearly')),
    interval_months INT NOT NULL CHECK (interval_months BETWEEN 1 AND 36),
    discount_percent NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_percent >= 0 AND discount_percent < 100),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    currency CHAR(3) NOT NULL,
    stripe_price_id VARCHAR(255) UNIQUE,
    retired_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_plan_prices_current
    ON billing_plan_prices (plan_key, period_code) WHERE retired_at IS NULL;

INSERT INTO billing_plan_prices (plan_key, period_code, interval_months, discount_percent, amount, currency)
SELECT p.plan_key, v.period_code, v.months, v.discount, ROUND(p.monthly_price * v.months * (1 - v.discount / 100.0), 2), p.currency
FROM usage_plans p
CROSS JOIN (VALUES ('monthly', 1, 0), ('three-months', 3, 10), ('six-months', 6, 20)) AS v(period_code, months, discount)
WHERE p.monthly_price IS NOT NULL
ON CONFLICT DO NOTHING;

-- Tenant plan status gains the end states a real subscription can reach.
ALTER TABLE tenant_plan_assignments DROP CONSTRAINT IF EXISTS tenant_plan_assignments_status_check;
ALTER TABLE tenant_plan_assignments ADD CONSTRAINT tenant_plan_assignments_status_check
    CHECK (status IN ('trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused', 'expired', 'cancelled'));
ALTER TABLE tenant_plan_assignments ADD COLUMN IF NOT EXISTS period_code VARCHAR(20) NOT NULL DEFAULT 'monthly';

-- One Stripe customer per company, reused for every checkout.
CREATE TABLE IF NOT EXISTS billing_customers (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    stripe_customer_id VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    stripe_subscription_id VARCHAR(255) NOT NULL UNIQUE,
    stripe_customer_id VARCHAR(255) NOT NULL,
    stripe_price_id VARCHAR(255),
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key),
    period_code VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL
        CHECK (status IN ('trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused', 'expired', 'cancelled')),
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    scheduled_plan_key VARCHAR(50) REFERENCES usage_plans(plan_key),
    scheduled_period_code VARCHAR(20),
    last_event_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- At most one live subscription per company (CEOPRO allowed several).
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_subscriptions_one_current
    ON billing_subscriptions (tenant_id)
    WHERE status IN ('trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused');

-- Every verified Stripe event, inserted once by its event id.
CREATE TABLE IF NOT EXISTS billing_webhook_events (
    stripe_event_id VARCHAR(255) PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    event_created TIMESTAMP WITH TIME ZONE NOT NULL,
    tenant_id UUID,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE,
    error TEXT,
    payload JSONB NOT NULL
);

-- One row per Stripe invoice that charged (or failed to charge) money.
CREATE TABLE IF NOT EXISTS billing_payments (
    payment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    stripe_invoice_id VARCHAR(255) NOT NULL UNIQUE,
    stripe_subscription_id VARCHAR(255),
    amount NUMERIC(12, 2) NOT NULL,
    currency CHAR(3) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('succeeded', 'failed')),
    paid_at TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,
    hosted_invoice_url TEXT,
    invoice_pdf_url TEXT,
    period_start TIMESTAMP WITH TIME ZONE,
    period_end TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_billing_payments_tenant ON billing_payments (tenant_id, created_at DESC);

-- A company gets the free trial once, ever.
CREATE TABLE IF NOT EXISTS billing_trials (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- Companies created before billing existed keep working: they get the
-- trial now, once, like a new sign-up.
INSERT INTO billing_trials (tenant_id, plan_key, started_at, ends_at)
SELECT c.tenant_id, 'pro', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '14 days'
FROM companies c
WHERE NOT EXISTS (SELECT 1 FROM tenant_plan_assignments a WHERE a.tenant_id = c.tenant_id)
ON CONFLICT DO NOTHING;
INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source)
SELECT t.tenant_id, t.plan_key, 'trialing', t.started_at::date, t.ends_at::date, 'trial'
FROM billing_trials t
ON CONFLICT (tenant_id) DO NOTHING;

-- Companies read their own billing rows; only the billing service writes.
ALTER TABLE billing_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_customers FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_payments FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_trials ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_trials FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_webhook_events FORCE ROW LEVEL SECURITY;

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['billing_customers', 'billing_subscriptions', 'billing_payments', 'billing_trials'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = tbl AND policyname = 'isolation_' || tbl) THEN
            EXECUTE format('CREATE POLICY %I ON %I FOR SELECT USING (tenant_id = get_current_tenant())', 'isolation_' || tbl, tbl);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON billing_customers, billing_subscriptions, billing_payments, billing_trials, billing_webhook_events FROM ceopro_app;
        GRANT SELECT ON billing_customers, billing_subscriptions, billing_payments, billing_trials, billing_plan_prices TO ceopro_app;
        REVOKE INSERT, UPDATE, DELETE ON billing_plan_prices FROM ceopro_app;
    END IF;
END $$;
