-- Price comparison tiers: how each of a company's products relates to the items
-- its competitors sell, when no competitor sells exactly the same thing.
--   EXACT        same product, same size
--   EQUIVALENT   same product, another quantity that scales cleanly (1 hour = 2 x 30 min)
--   SIMILAR      same kind of product, not like for like (another variant, size or nearby quantity)
--   ADDED_VALUE  ours is the competitor's item plus something extra, so a premium can be justified
-- Deliberately NOT written to competitor_prices: those rows are exact prices that feed
-- pricing recommendations and analytics. A comparable price is weaker evidence and is
-- labelled as such (same reasoning as market_price_observations).
--
-- One row per product + competitor + tier (the closest item of that tier). A competitor's
-- rows are replaced as a whole when its items are re-read, so a removed menu item disappears.
CREATE TABLE IF NOT EXISTS product_price_comparisons (
    comparison_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    tier VARCHAR(12) NOT NULL CHECK (tier IN ('EXACT', 'EQUIVALENT', 'SIMILAR', 'ADDED_VALUE')),
    direction VARCHAR(12) NOT NULL DEFAULT 'same' CHECK (direction IN ('own_richer', 'own_leaner', 'same')),
    match_score NUMERIC(4, 3) NOT NULL CHECK (match_score >= 0 AND match_score <= 1),
    -- competitor_price x scale_factor = comparable_price (2 for "1 hour vs 30 min"; 1 when no scaling applies).
    scale_factor NUMERIC(10, 4) NOT NULL DEFAULT 1 CHECK (scale_factor > 0),
    competitor_item_name TEXT NOT NULL,
    competitor_price NUMERIC(12, 4) NOT NULL CHECK (competitor_price >= 0),
    comparable_price NUMERIC(12, 4) NOT NULL CHECK (comparable_price >= 0),
    currency VARCHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    -- Our price against the comparable price, in percent; positive = we are dearer.
    price_delta_pct NUMERIC(8, 1),
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- ADDED_VALUE only: {premium_pct, status: underpriced|within_range|above_range, band_pct}.
    premium JSONB,
    method VARCHAR(12) NOT NULL DEFAULT 'RULES' CHECK (method IN ('RULES', 'AI_ASSISTED', 'OWNER')),
    source_url TEXT,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    computed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_price_comparison_product FOREIGN KEY (tenant_id, product_id)
        REFERENCES products (tenant_id, product_id) ON DELETE CASCADE,
    CONSTRAINT fk_price_comparison_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE,
    CONSTRAINT uq_price_comparison_tier UNIQUE (tenant_id, product_id, global_competitor_id, tier)
);

CREATE INDEX IF NOT EXISTS idx_price_comparisons_product ON product_price_comparisons (tenant_id, product_id, tier);
CREATE INDEX IF NOT EXISTS idx_price_comparisons_competitor ON product_price_comparisons (tenant_id, global_competitor_id);

ALTER TABLE product_price_comparisons ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_price_comparisons FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'product_price_comparisons' AND policyname = 'isolation_product_price_comparisons') THEN
        CREATE POLICY isolation_product_price_comparisons ON product_price_comparisons
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON product_price_comparisons TO ceopro_app;
    END IF;
END $$;
