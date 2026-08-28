-- Restored 2026-08-27 - a commit on main ("Update 20260807230553_add_market_intelligence_tables.sql")
-- had replaced this file's real SQL with unrelated Python source code (see
-- PENDING_ACTIONS.md #27/#29). Restored from the file's original creation
-- commit (f71bf2c) and upgraded to Final_schema.sql's conventions while
-- adopting it as canonical: gen_random_uuid() (no extensions are created
-- anywhere in Final_schema.sql), IF NOT EXISTS, and FORCE ROW LEVEL SECURITY
-- + a get_current_tenant()-keyed policy - the original version had none of
-- the three, which was consistent with the old schema's own conventions at
-- the time but not with the new baseline.

CREATE TABLE IF NOT EXISTS news_record (
    news_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    source_url VARCHAR(1024) NOT NULL,
    headline VARCHAR(512) NOT NULL,
    body_text TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS social_mention (
    mention_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    author_handle VARCHAR(255),
    mention_text TEXT NOT NULL,
    posted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extracted_entity (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    source_table VARCHAR(50) NOT NULL,
    source_record_id UUID NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_value VARCHAR(512) NOT NULL,
    confidence_score NUMERIC(4, 3),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_record_tenant ON news_record(tenant_id);
CREATE INDEX IF NOT EXISTS idx_social_mention_tenant ON social_mention(tenant_id);
CREATE INDEX IF NOT EXISTS idx_extracted_entity_tenant ON extracted_entity(tenant_id);
CREATE INDEX IF NOT EXISTS idx_extracted_entity_source ON extracted_entity(source_table, source_record_id);

ALTER TABLE news_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_mention ENABLE ROW LEVEL SECURITY;
ALTER TABLE extracted_entity ENABLE ROW LEVEL SECURITY;

ALTER TABLE news_record FORCE ROW LEVEL SECURITY;
ALTER TABLE social_mention FORCE ROW LEVEL SECURITY;
ALTER TABLE extracted_entity FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'news_record' AND policyname = 'isolation_news_record') THEN
        CREATE POLICY isolation_news_record ON news_record FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'social_mention' AND policyname = 'isolation_social_mention') THEN
        CREATE POLICY isolation_social_mention ON social_mention FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'extracted_entity' AND policyname = 'isolation_extracted_entity') THEN
        CREATE POLICY isolation_extracted_entity ON extracted_entity FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;
