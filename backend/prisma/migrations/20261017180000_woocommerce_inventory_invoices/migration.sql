-- Forward-only extension. Existing canonical data and source identities survive.
ALTER TABLE public.store_connections ADD COLUMN mapping_version SMALLINT NOT NULL DEFAULT 1 CHECK(mapping_version IN (1,2));
-- Unknown business safety stock must not become an invented zero. Existing
-- defaults and values remain intact for manual inventory workflows.
ALTER TABLE public.inventory ALTER COLUMN safety_stock DROP NOT NULL;
-- Keep original totals exact when a discounted unit rate repeats at scale four.
ALTER TABLE public.invoice_items ADD COLUMN rounding_adjustment NUMERIC(12,4) NOT NULL DEFAULT 0;
ALTER TABLE public.invoice_items DROP CONSTRAINT chk_total_price_consistent;
ALTER TABLE public.invoice_items ADD CONSTRAINT chk_total_price_consistent
 CHECK(total_price=quantity*unit_price+rounding_adjustment AND abs(rounding_adjustment)<=quantity*0.00005);
ALTER TABLE public.invoice_items ADD CONSTRAINT uq_tenant_invoice_item_perimeter UNIQUE(tenant_id,invoice_id,invoice_item_id);
CREATE TABLE public.store_inventory_links (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,external_id TEXT NOT NULL,
 inventory_id UUID,stock_state TEXT NOT NULL CHECK(stock_state IN ('managed','unmanaged','shared')),
 stock_status TEXT CHECK(stock_status IN ('instock','outofstock','onbackorder')),
 low_stock_threshold INT CHECK(low_stock_threshold>=0),stock_owner_external_id TEXT,
 observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,source_id,external_id),UNIQUE(tenant_id,inventory_id),
 FOREIGN KEY(tenant_id,source_id,external_id) REFERENCES public.store_product_links(tenant_id,source_id,external_id),
 FOREIGN KEY(tenant_id,inventory_id) REFERENCES public.inventory(tenant_id,inventory_id)
);
CREATE TABLE public.store_order_links (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,order_id TEXT NOT NULL,invoice_id UUID NOT NULL,
 order_status TEXT NOT NULL,source_modified_at TIMESTAMPTZ NOT NULL,paid_at TIMESTAMPTZ,
 accounting JSONB NOT NULL CHECK(jsonb_typeof(accounting)='object'),
 PRIMARY KEY(tenant_id,source_id,order_id),UNIQUE(tenant_id,invoice_id),UNIQUE(tenant_id,source_id,order_id,invoice_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES public.invoices(tenant_id,invoice_id)
);
CREATE TABLE public.store_order_item_links (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,order_id TEXT NOT NULL,line_id TEXT NOT NULL,
 invoice_id UUID NOT NULL,invoice_item_id UUID NOT NULL,
 PRIMARY KEY(tenant_id,source_id,order_id,line_id),UNIQUE(tenant_id,invoice_item_id),
 FOREIGN KEY(tenant_id,source_id,order_id,invoice_id) REFERENCES public.store_order_links(tenant_id,source_id,order_id,invoice_id),
 FOREIGN KEY(tenant_id,invoice_id,invoice_item_id) REFERENCES public.invoice_items(tenant_id,invoice_id,invoice_item_id)
);
DO $$ DECLARE relation TEXT; BEGIN
 FOREACH relation IN ARRAY ARRAY['store_inventory_links','store_order_links','store_order_item_links'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation);
  EXECUTE format('CREATE POLICY store_tenant ON public.%I TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',relation);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',relation);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO ceopro_app',relation);
 END LOOP;
END $$;
-- The restricted dispatcher still sees due metadata only, never accounting.
