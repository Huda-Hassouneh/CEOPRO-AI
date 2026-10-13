-- CEOPRO AI - Spec S13 Collection Policy Engine and exact scraper allocation.
-- External collection is disabled by default until a source has an explicit
-- method, justification, and ALLOWED decision.

ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS collection_method VARCHAR(32);
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS policy_status VARCHAR(20) NOT NULL DEFAULT 'RESTRICTED';
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS collection_justification TEXT;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS technical_restrictions JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS rate_limit_per_minute INT NOT NULL DEFAULT 30;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS policy_checked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_data_source_policy_status') THEN
        ALTER TABLE data_sources ADD CONSTRAINT chk_data_source_policy_status
            CHECK (policy_status IN ('ALLOWED', 'RESTRICTED', 'BLOCKED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_data_source_collection_method') THEN
        ALTER TABLE data_sources ADD CONSTRAINT chk_data_source_collection_method
            CHECK (collection_method IS NULL OR collection_method IN
                ('OFFICIAL_API', 'RSS', 'STRUCTURED_DATA', 'WEB_SCRAPE'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_data_source_rate_limit') THEN
        ALTER TABLE data_sources ADD CONSTRAINT chk_data_source_rate_limit
            CHECK (rate_limit_per_minute BETWEEN 1 AND 600);
    END IF;
END $$;

ALTER TABLE competitor_product_mappings ADD COLUMN IF NOT EXISTS source_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_mapping_source_isolated') THEN
        ALTER TABLE competitor_product_mappings ADD CONSTRAINT fk_mapping_source_isolated
            FOREIGN KEY (tenant_id, source_id)
            REFERENCES data_sources(tenant_id, source_id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_data_sources_collection_policy
    ON data_sources(tenant_id, policy_status, is_active);
CREATE INDEX IF NOT EXISTS idx_mappings_collection_source
    ON competitor_product_mappings(tenant_id, source_id, is_active);
