-- Owner-set added-value premium bands, per category (price comparison ladder).
-- Without a row the band is observed from the company's own comparisons, or the global default
-- (PRICE_COMPARISON_PREMIUM_BAND_PCT). A row here wins over both. category_key is the lower-cased product category;
-- '__none__' stands for products without a category. Additive: one new table.
CREATE TABLE IF NOT EXISTS price_premium_band_overrides (
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    category_key TEXT NOT NULL,
    band_pct NUMERIC(6,1) NOT NULL CHECK (band_pct >= 5 AND band_pct <= 300),
    set_by UUID,
    set_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, category_key)
);

ALTER TABLE price_premium_band_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_premium_band_overrides FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'price_premium_band_overrides' AND policyname = 'isolation_price_premium_band_overrides') THEN
        CREATE POLICY isolation_price_premium_band_overrides ON price_premium_band_overrides
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON price_premium_band_overrides TO ceopro_app;
    END IF;
END $$;
