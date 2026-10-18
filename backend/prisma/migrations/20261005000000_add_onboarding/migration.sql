-- Per-tenant onboarding wizard state (see src/modules/onboarding).
CREATE TABLE onboarding (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    current_step SMALLINT NOT NULL DEFAULT 1 CHECK (current_step BETWEEN 1 AND 6),
    highest_completed_step SMALLINT NOT NULL DEFAULT 0 CHECK (highest_completed_step BETWEEN 0 AND 6),
    industry VARCHAR(50),
    business_size VARCHAR(20),
    annual_revenue VARCHAR(20),
    city VARCHAR(100),
    objectives TEXT[] NOT NULL DEFAULT '{}',
    selected_plan VARCHAR(50),
    checkout_mode VARCHAR(10) NOT NULL DEFAULT 'trial',
    billing_period VARCHAR(20) NOT NULL DEFAULT 'monthly',
    custom_plan JSONB NOT NULL DEFAULT '{}',
    source_statuses JSONB NOT NULL DEFAULT '{}',
    website_url VARCHAR(2048),
    database_provider VARCHAR(50),
    downloaded_templates TEXT[] NOT NULL DEFAULT '{}',
    is_complete BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE onboarding ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_onboarding ON onboarding
    USING (tenant_id = get_current_tenant())
    WITH CHECK (tenant_id = get_current_tenant());

CREATE POLICY insert_onboarding ON onboarding FOR INSERT
    WITH CHECK (get_current_tenant() IS NULL OR tenant_id = get_current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding TO ceopro_app;
