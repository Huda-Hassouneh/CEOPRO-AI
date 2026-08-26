-- Rewritten 2026-08-27 to match Final_schema.sql's conventions after the
-- schema fork was resolved in its favor: gen_random_uuid() (Final_schema.sql
-- creates no extensions at all, so the old uuid_generate_v4() - which needs
-- uuid-ossp - would fail outright), IF NOT EXISTS, and FORCE ROW LEVEL
-- SECURITY + a get_current_tenant()-keyed policy like every other tenant-
-- scoped table.

CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    product_id UUID,
    campaign_brief TEXT NOT NULL,
    generated_image_key VARCHAR(512),
    status VARCHAR(50) DEFAULT 'Pending',
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_campaigns_product_isolated FOREIGN KEY (tenant_id, product_id) REFERENCES products(tenant_id, product_id) ON DELETE SET NULL,
    CONSTRAINT uq_tenant_campaign_perimeter UNIQUE (tenant_id, campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_campaigns_tenant ON campaigns(tenant_id);

ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'campaigns' AND policyname = 'isolation_campaigns') THEN
        CREATE POLICY isolation_campaigns ON campaigns FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;
