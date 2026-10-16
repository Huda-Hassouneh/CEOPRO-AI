-- Competitor relevance: category-aware classification + confidence ranking.
--
-- Before this, "RELEVANT" meant only "in-region and not a manufacturer", so a
-- donut shop was listed as a burger restaurant's competitor. These columns
-- hold the category evidence and the resulting confidence the competitor
-- directory now ranks by (see src/market_scraper/category_taxonomy.py and
-- src/ai/pricing/competitor_confidence.py).

-- Facts about the business itself (tenant-independent).
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS category_path TEXT[];
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS rating NUMERIC(2,1);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS rating_count INTEGER;
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS place_types TEXT[];

-- Facts that depend on this tenant's own business.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS category_similarity DOUBLE PRECISION
    CHECK (category_similarity IS NULL OR (category_similarity >= 0 AND category_similarity <= 1));
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100));
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS confidence_label TEXT
    CHECK (confidence_label IS NULL OR confidence_label IN ('High', 'Medium', 'Low'));
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS confidence_reasons JSONB;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS classification_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_tenant_competitors_confidence
    ON tenant_competitors (tenant_id, confidence_score DESC);
