-- The latest AI summary of market trends per company (built only from
-- stored news and competitor facts, each point citing them). Additive only.
CREATE TABLE IF NOT EXISTS market_summaries (
    tenant_id UUID PRIMARY KEY REFERENCES companies(tenant_id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE market_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_summaries FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'market_summaries' AND policyname = 'isolation_market_summaries') THEN
        CREATE POLICY isolation_market_summaries ON market_summaries FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON market_summaries TO ceopro_app;
    END IF;
END $$;
