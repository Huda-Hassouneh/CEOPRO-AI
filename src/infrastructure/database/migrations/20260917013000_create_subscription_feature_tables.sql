-- ==========================================
-- UP MIGRATION
-- ==========================================

-- 1. Create ENUMs (Only the ones actually needed for Features)
CREATE TYPE feature_type_enum AS ENUM ('limit', 'boolean');
CREATE TYPE aggregation_type_enum AS ENUM ('sum', 'max');
CREATE TYPE reset_cycle_enum AS ENUM ('billing_period', 'lifetime');

-- 2. Create Features Table
CREATE TABLE features (
    feature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_code VARCHAR(50) UNIQUE NOT NULL CHECK (feature_code ~ '^[a-z0-9_]+$'),
    feature_name VARCHAR(100) NOT NULL,
    feature_name_ar VARCHAR(100) NOT NULL,
    feature_type feature_type_enum NOT NULL,
    description VARCHAR(255),
    description_ar VARCHAR(255),
    
    unit VARCHAR(50),
    unit_ar VARCHAR(50),
    aggregation_type aggregation_type_enum NOT NULL DEFAULT 'sum',
    reset_cycle reset_cycle_enum NOT NULL DEFAULT 'billing_period',
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Create Mapping Table
CREATE TABLE plan_features (
    plan_id UUID REFERENCES plans(id) ON DELETE CASCADE,
    feature_id UUID REFERENCES features(feature_id) ON DELETE CASCADE,
    limit_value INT CHECK (limit_value >= -1),
    
    PRIMARY KEY (plan_id, feature_id)
);

-- 4. Create Usage Tracking (Now points to your existing 'subscriptions' table!)
CREATE TABLE subscription_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Links directly to your robust subscriptions table
    subscription_id UUID NOT NULL
        REFERENCES subscriptions(id) 
        ON DELETE CASCADE,

    feature_id UUID NOT NULL
        REFERENCES features(feature_id)
        ON DELETE CASCADE,

    current_usage INT NOT NULL DEFAULT 0
        CHECK (current_usage >= 0),

    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (period_end > period_start),

    UNIQUE (subscription_id, feature_id, period_start)
);

-- ==========================================
-- DOWN MIGRATION (Rollback)
-- ==========================================

-- DROP TABLE IF EXISTS subscription_usage;
-- DROP TABLE IF EXISTS plan_features;
-- DROP TABLE IF EXISTS features;

-- DROP TYPE IF EXISTS reset_cycle_enum;
-- DROP TYPE IF EXISTS aggregation_type_enum;
-- DROP TYPE IF EXISTS feature_type_enum;