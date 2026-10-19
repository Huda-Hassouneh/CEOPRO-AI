-- Owner decisions on the price comparison ladder (migration 20261024000000).
-- The ladder's rows are REPLACED whenever a competitor's items are re-read, so a correction made on a row would be
-- lost. This table keeps the decision keyed by what it is about - (product, competitor, normalized item name) - and
-- the engine re-applies it on every recompute:
--   ADDITION        the competitor's item is the base and ours adds something (forces ADDED_VALUE)
--   VARIANT         only a different variant of comparable standing (forces SIMILAR, like for like)
--   NOT_COMPARABLE  never compare this item with this product
-- Additive: one new table, nothing else touched.
CREATE TABLE IF NOT EXISTS product_price_comparison_overrides (
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    name_key TEXT NOT NULL,
    item_name TEXT,
    verdict VARCHAR(16) NOT NULL CHECK (verdict IN ('ADDITION', 'VARIANT', 'NOT_COMPARABLE')),
    decided_by UUID,
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, product_id, global_competitor_id, name_key),
    CONSTRAINT fk_comparison_override_product FOREIGN KEY (tenant_id, product_id)
        REFERENCES products (tenant_id, product_id) ON DELETE CASCADE,
    CONSTRAINT fk_comparison_override_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE
);

ALTER TABLE product_price_comparison_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_price_comparison_overrides FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'product_price_comparison_overrides' AND policyname = 'isolation_product_price_comparison_overrides') THEN
        CREATE POLICY isolation_product_price_comparison_overrides ON product_price_comparison_overrides
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON product_price_comparison_overrides TO ceopro_app;
    END IF;
END $$;
