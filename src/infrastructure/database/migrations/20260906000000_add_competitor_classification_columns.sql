-- CEOPRO AI - Real-competitor classification columns.
-- Discovery today registers any seller of a matched product as a
-- "competitor" with no manufacturer or product-overlap gate at all.
-- global_competitors.is_manufacturer lets discovery persist its existing
-- looks_like_manufacturer_or_wholesale() heuristic instead of discarding
-- it, and tenant_competitors.product_match_rate/is_confirmed_competitor
-- record the computed product-overlap ratio (this tenant's products the
-- seller also carries) and whether it cleared the configurable
-- "real competitor" threshold (default 50%, see
-- pricing/competitor_classification.py). country_code already exists
-- (20260827020000_add_competitor_country_code.sql) for the region check.

ALTER TABLE global_competitors
    ADD COLUMN IF NOT EXISTS is_manufacturer BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tenant_competitors
    ADD COLUMN IF NOT EXISTS product_match_rate NUMERIC(5, 4) CHECK (product_match_rate >= 0 AND product_match_rate <= 1),
    ADD COLUMN IF NOT EXISTS is_confirmed_competitor BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS classified_at TIMESTAMP WITH TIME ZONE;
