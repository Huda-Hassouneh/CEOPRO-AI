-- How a tracked competitor competes with this business:
--   MARKET  - competes with the business as a whole (same market/category,
--             e.g. another grocery store), whether or not prices for
--             specific products have been recorded yet;
--   PRODUCT - competes on specific products only (e.g. a coffee roaster
--             against a grocer's Arabic coffee), linked through
--             competitor_product_mappings.
-- NULL means "not stated"; the API then derives it from discovery method and
-- product overlap (competitor_landscape.py).
ALTER TABLE tenant_competitors
    ADD COLUMN IF NOT EXISTS competition_level TEXT
    CHECK (competition_level IS NULL OR competition_level IN ('MARKET', 'PRODUCT'));
