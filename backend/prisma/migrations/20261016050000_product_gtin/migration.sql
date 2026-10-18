-- Optional user-supplied GTIN, separate from a merchant's internal SKU.
-- No backfill, global uniqueness, identity merge, or AI behavior change.
ALTER TABLE public.products ADD COLUMN gtin VARCHAR(14);
ALTER TABLE public.products ADD CONSTRAINT chk_products_gtin CHECK (
  gtin IS NULL OR CASE WHEN gtin ~ '^([0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})$' AND gtin !~ '^0+$' THEN
    (substring(lpad(gtin,14,'0'),1,1)::int * 3 + substring(lpad(gtin,14,'0'),2,1)::int * 1 + substring(lpad(gtin,14,'0'),3,1)::int * 3 + substring(lpad(gtin,14,'0'),4,1)::int * 1 + substring(lpad(gtin,14,'0'),5,1)::int * 3 + substring(lpad(gtin,14,'0'),6,1)::int * 1 + substring(lpad(gtin,14,'0'),7,1)::int * 3 + substring(lpad(gtin,14,'0'),8,1)::int * 1 + substring(lpad(gtin,14,'0'),9,1)::int * 3 + substring(lpad(gtin,14,'0'),10,1)::int * 1 + substring(lpad(gtin,14,'0'),11,1)::int * 3 + substring(lpad(gtin,14,'0'),12,1)::int * 1 + substring(lpad(gtin,14,'0'),13,1)::int * 3 + substring(lpad(gtin,14,'0'),14,1)::int * 1) % 10 = 0
  ELSE FALSE END
);
CREATE INDEX idx_products_tenant_gtin ON public.products(tenant_id, (lpad(gtin,14,'0')))
 WHERE deleted_at IS NULL AND gtin IS NOT NULL;
