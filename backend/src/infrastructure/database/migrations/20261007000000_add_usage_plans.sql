-- 360 Radar - subscription usage allowances, separate from technical limits.
--
-- Two different things must never be confused:
--   * Technical safety limits (10 MB per upload, 20 MB per assistant
--     document, unpacked-size checks) protect the service and are the same
--     for every company. They stay in code/configuration.
--   * Plan allowances (assistant questions, web searches, image
--     generations, products, competitors, document storage) are a
--     commercial decision per company. They live here, are measured per
--     tenant and enforced per tenant: one company using up its allowance -
--     or a provider rate limit - never affects another company.
--
-- Vocabulary deliberately matches the CEOPRO billing backend (features /
-- plan_features / subscriptions / subscription_usage, on the same
-- companies.tenant_id): the same feature codes, aggregation types, reset
-- cycles and subscription statuses, so this local store can later be
-- replaced by reading that system (src/ai/core/usage.py's entitlement
-- source) without changing callers. Table names differ on purpose
-- (usage_*), so the two never collide in one database.

CREATE TABLE IF NOT EXISTS usage_features (
    feature_code VARCHAR(60) PRIMARY KEY,
    unit VARCHAR(30) NOT NULL,
    aggregation_type VARCHAR(10) NOT NULL CHECK (aggregation_type IN ('sum', 'max')),
    reset_cycle VARCHAR(20) NOT NULL CHECK (reset_cycle IN ('billing_period', 'lifetime'))
);

INSERT INTO usage_features (feature_code, unit, aggregation_type, reset_cycle) VALUES
    ('rag_assistant', 'questions', 'sum', 'billing_period'),
    ('web_searches', 'searches', 'sum', 'billing_period'),
    ('marketing_image_generation', 'images', 'sum', 'billing_period'),
    ('tracked_products', 'products', 'max', 'lifetime'),
    ('tracked_competitors', 'competitors', 'max', 'lifetime'),
    ('document_storage_mb', 'MB', 'max', 'lifetime')
ON CONFLICT (feature_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS usage_plans (
    plan_key VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    -- The CEOPRO billing plan this corresponds to, once linked.
    billing_plan_id UUID
);

-- limit_value NULL = unlimited.
CREATE TABLE IF NOT EXISTS usage_plan_limits (
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key) ON DELETE CASCADE,
    feature_code VARCHAR(60) NOT NULL REFERENCES usage_features(feature_code),
    limit_value BIGINT CHECK (limit_value IS NULL OR limit_value >= 0),
    PRIMARY KEY (plan_key, feature_code)
);

-- Same plans and limits the product's plan catalogue shows customers
-- (frontend/src/shared/catalog/planCatalog.js), plus the AI metrics.
INSERT INTO usage_plans (plan_key, display_name) VALUES
    ('standard', 'Standard'), ('pro', 'Pro'), ('custom', 'Custom')
ON CONFLICT (plan_key) DO NOTHING;

INSERT INTO usage_plan_limits (plan_key, feature_code, limit_value) VALUES
    ('standard', 'rag_assistant', 200), ('standard', 'web_searches', 50), ('standard', 'marketing_image_generation', 30),
    ('standard', 'tracked_products', 100), ('standard', 'tracked_competitors', 5), ('standard', 'document_storage_mb', 5120),
    ('pro', 'rag_assistant', 1500), ('pro', 'web_searches', 300), ('pro', 'marketing_image_generation', 200),
    ('pro', 'tracked_products', 1000), ('pro', 'tracked_competitors', 25), ('pro', 'document_storage_mb', 51200),
    ('custom', 'rag_assistant', NULL), ('custom', 'web_searches', NULL), ('custom', 'marketing_image_generation', NULL),
    ('custom', 'tracked_products', NULL), ('custom', 'tracked_competitors', NULL), ('custom', 'document_storage_mb', NULL)
ON CONFLICT (plan_key, feature_code) DO NOTHING;

-- Which plan each company is on, written by an operator or a billing
-- service - never by the application role. No row = the deployment's
-- DEFAULT_PLAN_KEY. Only 'active' and 'trialing' grant access (as in CEOPRO).
CREATE TABLE IF NOT EXISTS tenant_plan_assignments (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key),
    status VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (status IN ('trialing', 'active', 'past_due', 'pending', 'payment_failed', 'paused')),
    current_period_start DATE,
    current_period_end DATE,
    source VARCHAR(30) NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Metered ('sum') usage per tenant, feature and period (period_start = the
-- first day of the billing period or calendar month). A new period is a new
-- row - nothing is ever reset in place. 'max' features are counted live.
CREATE TABLE IF NOT EXISTS tenant_usage_counters (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    feature_code VARCHAR(60) NOT NULL REFERENCES usage_features(feature_code),
    period_start DATE NOT NULL,
    used BIGINT NOT NULL DEFAULT 0 CHECK (used >= 0),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, feature_code, period_start)
);

ALTER TABLE tenant_plan_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_plan_assignments FORCE ROW LEVEL SECURITY;
ALTER TABLE tenant_usage_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_usage_counters FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'tenant_plan_assignments' AND policyname = 'isolation_tenant_plan_assignments') THEN
        CREATE POLICY isolation_tenant_plan_assignments ON tenant_plan_assignments
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'tenant_usage_counters' AND policyname = 'isolation_tenant_usage_counters') THEN
        CREATE POLICY isolation_tenant_usage_counters ON tenant_usage_counters
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    -- The application reads features, plans and assignments; only an
    -- operator or billing service changes them.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE INSERT, UPDATE, DELETE ON usage_features, usage_plans, usage_plan_limits, tenant_plan_assignments FROM ceopro_app;
        GRANT SELECT ON usage_features, usage_plans, usage_plan_limits, tenant_plan_assignments TO ceopro_app;
        GRANT SELECT, INSERT, UPDATE ON tenant_usage_counters TO ceopro_app;
    END IF;
END $$;
