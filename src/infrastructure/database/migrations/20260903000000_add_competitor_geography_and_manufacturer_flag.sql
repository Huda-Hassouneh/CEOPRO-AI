-- CEOPRO AI - Geographic relevance and manufacturer-exclusion safeguards
-- for competitor mapping.
--
-- global_competitors.country_code already existed but nothing anywhere in
-- src/ai/pricing/ or src/market_scraper/ enforced it when a competitor got
-- mapped to a tenant's product - confirmed by grep before writing this: no
-- code path checks country relevance at mapping-creation time (the only
-- existing "cross-country" awareness is pricing/data_access.py's currency-
-- based split, which decides how to USE an already-mapped competitor's
-- price, not whether that competitor should have been mapped at all). And
-- there was no way to mark a business as "this is the product's own
-- manufacturer, not a retail competitor" anywhere in the schema.
--
-- This migration adds the column the new safeguard function
-- (src/ai/pricing/matching.py::create_competitor_mapping()) requires;
-- enforcement itself is application-level (a human/tenant, or any future
-- automated mapping pipeline, must go through that function), not a DB
-- trigger - country relevance depends on companies.operating_countries
-- (an array, not directly expressible as a single-table CHECK).

ALTER TABLE global_competitors
    ADD COLUMN IF NOT EXISTS is_manufacturer BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN global_competitors.is_manufacturer IS
    'TRUE means this business is the product''s own manufacturer/brand owner, not a retail competitor - create_competitor_mapping() refuses to map a product to a manufacturer-flagged competitor.';

COMMENT ON COLUMN global_competitors.country_code IS
    'ISO 3166-1 alpha-2. create_competitor_mapping() refuses to create a mapping unless this is set and is one of the mapping tenant''s companies.country_code / companies.operating_countries.';
