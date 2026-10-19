-- Competitor data completeness: a per-competitor, per-facet ledger recording
-- what we managed to collect and, when we did not, WHY (so the owner can
-- retry or fix the cause instead of staring at a blank field).
--
-- Additive only: two nullable columns on global_competitors plus one new
-- table. Existing rows and queries are unaffected.

-- Google's stable identity for a business. Lets a business with no website
-- (many local shops live only on Maps/Instagram) be registered and
-- deduplicated, and lets profile enrichment skip the name-matching guess.
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS google_place_id TEXT;
-- The business's own official social profile URLs, e.g. {"instagram": "https://..."}.
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS social_profiles JSONB;

CREATE INDEX IF NOT EXISTS idx_global_competitors_google_place_id
    ON global_competitors (google_place_id) WHERE google_place_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS competitor_enrichment (
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    facet VARCHAR(32) NOT NULL
        CHECK (facet IN ('PROFILE', 'SOCIAL_LINKS', 'PRICES', 'REVIEWS', 'SOCIAL_CONTENT')),
    status VARCHAR(16) NOT NULL
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'BLOCKED', 'NOT_APPLICABLE')),
    -- Machine-readable cause (NO_CREDENTIALS, PROVIDER_ERROR, NO_MATCH, ...);
    -- reason_detail is the human-readable specifics and never holds a secret.
    reason_code VARCHAR(40),
    reason_detail TEXT,
    provider VARCHAR(40),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    items_found INTEGER NOT NULL DEFAULT 0 CHECK (items_found >= 0),
    -- How sure we are the data belongs to THIS business (1.0 = exact place_id).
    data_confidence DOUBLE PRECISION CHECK (data_confidence IS NULL OR (data_confidence >= 0 AND data_confidence <= 1)),
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, global_competitor_id, facet),
    CONSTRAINT fk_competitor_enrichment_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors(tenant_id, global_competitor_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_competitor_enrichment_retry
    ON competitor_enrichment (tenant_id, status, next_retry_at);

ALTER TABLE competitor_enrichment ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_enrichment FORCE ROW LEVEL SECURITY;

CREATE POLICY isolation_competitor_enrichment ON competitor_enrichment
    FOR ALL USING (tenant_id = get_current_tenant());
