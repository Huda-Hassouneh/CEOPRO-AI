-- What competitors publish about themselves (read from their own
-- websites) and AI analysis of it, plus industry and competitor news, each
-- with the page it came from and when it was read. Additive only; rows
-- belong to one company (RLS) and go with it.
CREATE TABLE IF NOT EXISTS competitor_intel (
    intel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    global_competitor_id UUID NOT NULL,
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('product', 'promotion', 'message', 'social', 'analysis')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_url TEXT,
    confidence NUMERIC(4, 3),
    retrieved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_competitor_intel_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_competitor_intel_competitor ON competitor_intel (tenant_id, global_competitor_id, kind);

-- When each competitor's website was last read, and how it went.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS intel_checked_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS intel_status VARCHAR(20);

CREATE TABLE IF NOT EXISTS market_news (
    news_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    source_domain VARCHAR(255),
    language VARCHAR(40),
    published_at TIMESTAMP WITH TIME ZONE,
    topic VARCHAR(20) NOT NULL DEFAULT 'industry' CHECK (topic IN ('industry', 'competitor')),
    global_competitor_id UUID,
    retrieved_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_market_news UNIQUE (tenant_id, url)
);
CREATE INDEX IF NOT EXISTS idx_market_news_tenant ON market_news (tenant_id, published_at DESC);

-- How many separate sources a discovery run actually queried or read.
ALTER TABLE discovery_runs ADD COLUMN IF NOT EXISTS sources_checked INT NOT NULL DEFAULT 0;
ALTER TABLE discovery_runs ADD COLUMN IF NOT EXISTS sources_answered INT NOT NULL DEFAULT 0;

ALTER TABLE competitor_intel ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_intel FORCE ROW LEVEL SECURITY;
ALTER TABLE market_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_news FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'competitor_intel' AND policyname = 'isolation_competitor_intel') THEN
        CREATE POLICY isolation_competitor_intel ON competitor_intel FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'market_news' AND policyname = 'isolation_market_news') THEN
        CREATE POLICY isolation_market_news ON market_news FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON competitor_intel, market_news TO ceopro_app;
    END IF;
END $$;
