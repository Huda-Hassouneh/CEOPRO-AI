-- Additive identity; existing records and provider observations are unchanged.
ALTER TABLE public.products ADD COLUMN sku varchar(100);
ALTER TABLE public.products ADD COLUMN version integer NOT NULL DEFAULT 1;
ALTER TABLE public.products ADD CONSTRAINT product_sku_format CHECK(sku IS NULL OR sku ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$');
CREATE UNIQUE INDEX products_active_tenant_sku ON public.products(tenant_id,lower(sku)) WHERE deleted_at IS NULL AND sku IS NOT NULL;
CREATE FUNCTION public.keel_product_revision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE old_names jsonb;
BEGIN
 NEW.version := OLD.version+1;
 IF NEW.product_name IS DISTINCT FROM OLD.product_name THEN
  SELECT coalesce(jsonb_agg(DISTINCT lower(trim(value))),'[]'::jsonb) INTO old_names
  FROM jsonb_each_text(CASE WHEN jsonb_typeof(OLD.product_name)='object' THEN OLD.product_name ELSE '{}'::jsonb END) WHERE trim(value)<>'';
  NEW.metadata:=coalesce(NEW.metadata,'{}'::jsonb)||jsonb_build_object('import_name_aliases',coalesce(OLD.metadata->'import_name_aliases','[]'::jsonb)||old_names);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER keel_product_revision BEFORE UPDATE ON public.products FOR EACH ROW EXECUTE FUNCTION public.keel_product_revision();
REVOKE ALL ON FUNCTION public.keel_product_revision() FROM PUBLIC;
