-- Market discovery: competitors found from public sources (OpenStreetMap,
-- Google Places, web search, Apify), merged into one record per business,
-- with every source kept for provenance and a relevance/confidence score per
-- company. Industry-agnostic: what to look for comes from the company's own
-- industry, products and location.

-- The company's industry (a key of the discovery taxonomy) and a short
-- description of what it sells, both used to decide what counts as a
-- competitor. business_type stays as the free-text label.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS industry_key VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS business_description TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS website_url TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP WITH TIME ZONE;
-- Demonstration workspaces (owners on the reserved ".example" domain, RFC
-- 2606, which no real customer can use) are labelled as sample data.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE companies c SET is_demo = TRUE
WHERE NOT c.is_demo AND EXISTS (
    SELECT 1 FROM tenant_users tu JOIN users u ON u.user_id = tu.user_id
    WHERE tu.tenant_id = c.tenant_id AND tu.role_key = 'owner' AND LOWER(u.email) LIKE '%.example');
-- Companies that existed before guided setup are treated as set up.
UPDATE companies SET onboarding_completed_at = COALESCE(onboarding_completed_at, created_at, CURRENT_TIMESTAMP)
WHERE onboarding_completed_at IS NULL;

-- Public business details, filled from whichever sources reported them.
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS categories TEXT[];
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS rating NUMERIC(3, 2) CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5));
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS review_count INT CHECK (review_count IS NULL OR review_count >= 0);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS price_level SMALLINT CHECK (price_level IS NULL OR price_level BETWEEN 0 AND 4);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS name_ar VARCHAR(255);

-- How each company relates to each discovered business.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS relevance_score NUMERIC(5, 4) CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1);
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS confidence NUMERIC(5, 4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1);
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS source_count INT NOT NULL DEFAULT 0;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS match_reasons JSONB NOT NULL DEFAULT '[]'::jsonb;
-- Branches of the same brand found in the area (one competitor, many places).
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS branch_count INT NOT NULL DEFAULT 0;
ALTER TABLE tenant_competitors DROP CONSTRAINT IF EXISTS tenant_competitors_discovery_method_check;
ALTER TABLE tenant_competitors ADD CONSTRAINT tenant_competitors_discovery_method_check
    CHECK (discovery_method IS NULL OR discovery_method IN (
        'PRODUCT_SEARCH', 'PLACES_NEARBY', 'INDUSTRY_KEYWORD_SEARCH', 'MAP_LISTING', 'WEB_SEARCH', 'DIRECTORY'));
CREATE INDEX IF NOT EXISTS idx_tenant_competitors_relevance ON tenant_competitors (tenant_id, relevance_score DESC NULLS LAST);

-- One row per (company, source, record at that source): where a competitor
-- was seen, when, and what the source said.
CREATE TABLE IF NOT EXISTS competitor_sources (
    source_row_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    global_competitor_id UUID NOT NULL,
    source VARCHAR(40) NOT NULL CHECK (source IN (
        'openstreetmap', 'google_places', 'google_search', 'apify_google_maps', 'searxng', 'manual', 'website', 'demo')),
    source_ref TEXT NOT NULL,
    source_url TEXT,
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT fk_competitor_source_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE,
    CONSTRAINT uq_competitor_source UNIQUE (tenant_id, source, source_ref)
);
CREATE INDEX IF NOT EXISTS idx_competitor_sources_competitor ON competitor_sources (tenant_id, global_competitor_id);

-- Each discovery run: what was searched, which sources answered, results.
CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'partial', 'failed')),
    requested_by UUID,
    industry_key VARCHAR(50),
    center_latitude DOUBLE PRECISION,
    center_longitude DOUBLE PRECISION,
    radius_km DOUBLE PRECISION,
    query JSONB NOT NULL DEFAULT '{}'::jsonb,
    providers JSONB NOT NULL DEFAULT '{}'::jsonb,
    found_count INT NOT NULL DEFAULT 0,
    new_count INT NOT NULL DEFAULT 0,
    updated_count INT NOT NULL DEFAULT 0,
    tracked_count INT NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_discovery_runs_tenant ON discovery_runs (tenant_id, created_at DESC);
-- One active run per company at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_discovery_runs_active ON discovery_runs (tenant_id) WHERE status IN ('queued', 'running');

ALTER TABLE competitor_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE discovery_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovery_runs FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'competitor_sources' AND policyname = 'isolation_competitor_sources') THEN
        CREATE POLICY isolation_competitor_sources ON competitor_sources FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'discovery_runs' AND policyname = 'isolation_discovery_runs') THEN
        CREATE POLICY isolation_discovery_runs ON discovery_runs FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON competitor_sources, discovery_runs TO ceopro_app;
    END IF;
END $$;
