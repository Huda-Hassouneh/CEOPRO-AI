-- SUBSCRIPTION PLANS
-- Stores the subscription plans offered by CEOPRO.
CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(50) NOT NULL UNIQUE
        CHECK (name IN ('starter', 'growth', 'enterprise')),

    description TEXT,

    price NUMERIC(10, 2) NOT NULL
        CHECK (price >= 0),

    currency VARCHAR(3) NOT NULL DEFAULT 'JOD'
        CHECK (currency ~ '^[A-Z]{3}$'),

    billing_interval_value INTEGER NOT NULL
        CHECK (billing_interval_value > 0),

    billing_interval_unit VARCHAR(10) NOT NULL
        CHECK (billing_interval_unit IN ('day', 'week', 'month', 'year')),

    trial_period_value INTEGER NOT NULL DEFAULT 0
        CHECK (trial_period_value >= 0),

    trial_period_unit VARCHAR(10)
        CHECK (trial_period_unit IN ('day', 'week', 'month', 'year')),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Either both trial fields are provided or neither
    CONSTRAINT trial_period_consistency CHECK (
        (trial_period_value = 0 AND trial_period_unit IS NULL)
        OR
        (trial_period_value > 0 AND trial_period_unit IS NOT NULL)
    )
);



-- PROMO CODES
-- Stores discount codes that can be applied during checkout.
CREATE TABLE IF NOT EXISTS promo_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    code VARCHAR(50) NOT NULL UNIQUE,

    discount_type VARCHAR(20) NOT NULL
        CHECK (discount_type IN ('percentage', 'fixed_amount')),

   
    discount_value NUMERIC(10, 2) NOT NULL
        CHECK (discount_value > 0),

    max_uses INTEGER NOT NULL
        CHECK (max_uses > 0),

    used_count INTEGER NOT NULL DEFAULT 0
        CHECK (used_count >= 0 AND used_count <= max_uses),

    max_uses_per_user INTEGER NOT NULL DEFAULT 1
        CHECK (max_uses_per_user > 0),

    starts_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_promo_code_dates
        CHECK (expires_at > starts_at)
);



-- PROMO CODE / PLAN JUNCTION
-- Represents the many-to-many relationship between promo codes
-- and subscription plans.
CREATE TABLE IF NOT EXISTS promo_codes_plans (
    promo_code_id UUID NOT NULL,
    plan_id UUID NOT NULL,

    PRIMARY KEY (promo_code_id, plan_id),

    CONSTRAINT fk_promo_codes_plans_promo_code
        FOREIGN KEY (promo_code_id)
        REFERENCES promo_codes(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_promo_codes_plans_plan
        FOREIGN KEY (plan_id)
        REFERENCES plans(id)
        ON DELETE CASCADE
);


-- SUBSCRIPTIONS
-- Stores the tenant's current and historical subscriptions.
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID NOT NULL,

    plan_id UUID NOT NULL,

    stripe_customer_id VARCHAR(255) UNIQUE,

    stripe_subscription_id VARCHAR(255) UNIQUE,

    status VARCHAR(30) NOT NULL
        CHECK (
            status IN (
                'pending',
                'active',
                'past_due',
                'payment_failed',
                'cancelled',
                'expired'
            )
        ),

    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,

   
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,

    cancelled_at TIMESTAMPTZ NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_subscriptions_tenant
        FOREIGN KEY (tenant_id)
        REFERENCES companies(tenant_id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_subscriptions_plan
        FOREIGN KEY (plan_id)
        REFERENCES plans(id)
        ON DELETE RESTRICT,

    CONSTRAINT chk_subscription_period
        CHECK (current_period_end > current_period_start)
);


-- Ensures a tenant can have at most one current subscription.
-- Historical cancelled/expired subscriptions are still allowed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_one_current_per_tenant
ON subscriptions (tenant_id)
WHERE status IN (
    'pending',
    'active',
    'past_due',
    'payment_failed'
);

-- PAYMENT TRANSACTIONS
-- Stores the payment history for subscription billing attempts.
CREATE TABLE IF NOT EXISTS payment_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    subscription_id UUID NOT NULL,

    stripe_payment_intent_id VARCHAR(255) UNIQUE,

   
    stripe_invoice_id VARCHAR(255),

    amount NUMERIC(12, 2) NOT NULL
        CHECK (amount >= 0),

    currency VARCHAR(3) NOT NULL
        CHECK (currency ~ '^[A-Z]{3}$'),

    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'succeeded',
                'failed'
            )
        ),

    paid_at TIMESTAMPTZ NULL,

  
    failure_reason TEXT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_payment_transactions_subscription
        FOREIGN KEY (subscription_id)
        REFERENCES subscriptions(id)
        ON DELETE RESTRICT
);


-- PROMO CODE REDEMPTIONS
-- Stores an audit trail of successfully redeemed promo codes.
-- Validation alone does not create a redemption record.
CREATE TABLE IF NOT EXISTS promo_code_redemptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    promo_code_id UUID NOT NULL,

    subscription_id UUID NOT NULL,

    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_promo_code_redemptions_promo_code
        FOREIGN KEY (promo_code_id)
        REFERENCES promo_codes(id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_promo_code_redemptions_subscription
        FOREIGN KEY (subscription_id)
        REFERENCES subscriptions(id)
        ON DELETE RESTRICT,

    -- Prevents the same promo code from being redeemed more
    -- than once for the same subscription.
    CONSTRAINT uq_promo_code_redemption
        UNIQUE (promo_code_id, subscription_id)
);


-- STRIPE WEBHOOK EVENTS
-- Stores received Stripe webhook events for auditing and
-- idempotent event processing.
CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    
    stripe_event_id VARCHAR(255) NOT NULL UNIQUE,

    event_type VARCHAR(100) NOT NULL,

    processed BOOLEAN NOT NULL DEFAULT FALSE,

    processed_at TIMESTAMPTZ NULL,

    payload JSONB NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);