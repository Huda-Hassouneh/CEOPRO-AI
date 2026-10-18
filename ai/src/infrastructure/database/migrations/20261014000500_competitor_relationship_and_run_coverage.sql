-- How each discovered business relates to the company (market_discovery/
-- relevance.py): DIRECT (same products/specialty), INDIRECT (same industry),
-- RELATED (neighbouring industry), UNVERIFIED (not confirmed). The reasons
-- stay in match_reasons. NULL for rows classified before this existed.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS relationship TEXT;
ALTER TABLE tenant_competitors DROP CONSTRAINT IF EXISTS tenant_competitors_relationship_check;
ALTER TABLE tenant_competitors ADD CONSTRAINT tenant_competitors_relationship_check
    CHECK (relationship IS NULL OR relationship IN ('DIRECT', 'INDIRECT', 'RELATED', 'UNVERIFIED'));
CREATE INDEX IF NOT EXISTS idx_tenant_competitors_relationship ON tenant_competitors (tenant_id, relationship);

-- What each run actually produced at every stage: businesses discovered,
-- relevant by relationship, websites tried / read / failed by reason,
-- pages read, products and prices extracted, prices matched to the
-- company's products, duplicates merged.
ALTER TABLE discovery_runs ADD COLUMN IF NOT EXISTS coverage JSONB;

-- Website reads before this change recorded a failed DNS lookup as
-- 'not_public' (the address guard's error); it meant 'unreachable'.
UPDATE tenant_competitors SET intel_status = 'unreachable' WHERE intel_status = 'not_public';
