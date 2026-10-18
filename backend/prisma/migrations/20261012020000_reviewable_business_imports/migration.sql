ALTER TABLE products ADD COLUMN sku VARCHAR(100);
ALTER TABLE products ADD CONSTRAINT products_sku_format
  CHECK (sku IS NULL OR sku ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$');

-- Existing rows have no SKU, so the index can be introduced without a backfill.
CREATE UNIQUE INDEX uq_products_active_tenant_sku
  ON products (tenant_id, lower(btrim(sku)))
  WHERE deleted_at IS NULL AND sku IS NOT NULL AND btrim(sku) <> '';

CREATE TABLE business_import_drafts (
  draft_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('invoices', 'inventory')),
  file_name VARCHAR(255) NOT NULL,
  file_bytes BYTEA,
  sha256 CHAR(64) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'PREVIEW' CHECK (status IN ('PREVIEW', 'COMPLETED')),
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT business_import_draft_bytes CHECK (
    (status = 'PREVIEW' AND file_bytes IS NOT NULL) OR
    (status = 'COMPLETED' AND file_bytes IS NULL AND result IS NOT NULL)
  )
);

CREATE INDEX business_import_drafts_owner_expiry
  ON business_import_drafts(tenant_id, user_id, expires_at);

ALTER TABLE business_import_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_import_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY business_import_drafts_owner ON business_import_drafts FOR ALL
  USING (tenant_id = get_current_tenant() AND
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
  WITH CHECK (tenant_id = get_current_tenant() AND
    user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
