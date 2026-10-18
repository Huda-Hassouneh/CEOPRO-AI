-- CEOPRO AI - Restore spec S13 Collection Policy Engine columns on
-- competitor_prices, entirely absent from Final_schema.sql's version
-- (competitor_price_id, tenant_id, mapping_id, scraped_price, currency,
-- is_available, observed_at only) - no way to mark a scraped price
-- RESTRICTED/BLOCKED, and no way to distinguish an exact captured price from
-- an estimate.

ALTER TABLE competitor_prices ADD COLUMN IF NOT EXISTS source_status VARCHAR(20) NOT NULL DEFAULT 'ALLOWED';
ALTER TABLE competitor_prices ADD COLUMN IF NOT EXISTS is_exact_data BOOLEAN NOT NULL DEFAULT TRUE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_competitor_price_source_status') THEN
        ALTER TABLE competitor_prices ADD CONSTRAINT chk_competitor_price_source_status
            CHECK (source_status IN ('ALLOWED', 'RESTRICTED', 'BLOCKED'));
    END IF;
END $$;
