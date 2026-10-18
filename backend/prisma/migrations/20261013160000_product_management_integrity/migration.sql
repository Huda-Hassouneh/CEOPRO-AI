-- Product capacity and price audit apply to application, import and direct writers.
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE public.product_price_history ADD COLUMN IF NOT EXISTS old_currency VARCHAR(3);
-- Archived products remain readable to their tenant for history and restore.
DROP POLICY IF EXISTS select_products_isolated ON public.products;
CREATE POLICY select_products_isolated ON public.products FOR SELECT USING (tenant_id = public.get_current_tenant());

CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_active_sku
ON public.products (tenant_id, lower(btrim(sku)))
WHERE deleted_at IS NULL AND NULLIF(btrim(sku), '') IS NOT NULL;

CREATE OR REPLACE FUNCTION public.product_capacity_for_tenant(request_tenant UUID)
RETURNS TABLE(current_usage BIGINT, limit_value INTEGER, is_unlimited BOOLEAN, included BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  saved_tenant TEXT := current_setting('app.current_tenant_id', true);
  saved_user TEXT := current_setting('app.current_user_id', true);
  caller TEXT := COALESCE(NULLIF(current_setting('role', true), 'none'), session_user::TEXT);
  plan UUID; used BIGINT; cap INTEGER; enabled BOOLEAN := FALSE;
BEGIN
  -- The owner already has administrative access. Other application callers
  -- must supply the same tenant context as the request. The dedicated worker
  -- may inspect only a tenant with a queued/processing ingestion job.
  IF caller <> current_user::TEXT AND caller <> 'ceopro_ingestion_worker'
     AND public.get_current_tenant() IS DISTINCT FROM request_tenant THEN
    RAISE EXCEPTION 'PRODUCT_TENANT_REQUIRED' USING ERRCODE = '23514';
  END IF;
  IF public.get_current_tenant() IS NOT NULL AND public.get_current_tenant() <> request_tenant THEN
    RAISE EXCEPTION 'PRODUCT_TENANT_REQUIRED' USING ERRCODE = '23514';
  END IF;
  -- Temporary context is limited to this tenant inside the definer function.
  -- It is restored before returning; caller table privileges/RLS are unchanged.
  PERFORM set_config('app.current_tenant_id', request_tenant::TEXT, true);
  PERFORM set_config('app.current_user_id', COALESCE(NULLIF(saved_user, ''), 'product-capacity-guard'), true);
  IF caller = 'ceopro_ingestion_worker' AND NOT EXISTS (
    SELECT 1 FROM public.ingestion_jobs WHERE tenant_id = request_tenant AND job_status IN ('QUEUED', 'PROCESSING')
  ) THEN RAISE EXCEPTION 'PRODUCT_WORKER_JOB_REQUIRED' USING ERRCODE = '23514'; END IF;
  SELECT count(*) INTO used FROM public.products WHERE tenant_id = request_tenant AND deleted_at IS NULL;
  SELECT plan_id INTO plan FROM public.subscriptions
    WHERE tenant_id = request_tenant AND status IN ('active', 'trialing')
    ORDER BY updated_at DESC, created_at DESC LIMIT 1 FOR SHARE;
  IF plan IS NOT NULL AND EXISTS (
    SELECT 1 FROM public.plan_features pf JOIN public.features f ON f.feature_id = pf.feature_id
    WHERE pf.plan_id = plan AND f.feature_code = 'product_management' AND f.feature_type = 'boolean'
  ) THEN
    SELECT pf.limit_value INTO cap FROM public.plan_features pf JOIN public.features f ON f.feature_id = pf.feature_id
      WHERE pf.plan_id = plan AND f.feature_code = 'tracked_products' AND f.feature_type = 'limit'
        AND f.aggregation_type = 'max' AND f.reset_cycle = 'lifetime';
    enabled := FOUND;
  END IF;
  PERFORM set_config('app.current_tenant_id', COALESCE(saved_tenant, ''), true);
  PERFORM set_config('app.current_user_id', COALESCE(saved_user, ''), true);
  RETURN QUERY SELECT used, CASE WHEN enabled THEN cap ELSE 0 END, enabled AND cap IS NULL, enabled;
END;
$$;

CREATE OR REPLACE FUNCTION public.enforce_product_capacity()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE capacity RECORD;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'PRODUCT_TENANT_IMMUTABLE' USING ERRCODE = '23514';
  END IF;
  IF NEW.deleted_at IS NOT NULL THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL THEN RETURN NEW; END IF;
  -- A fresh READ COMMITTED snapshot after waiting on the common lock is
  -- required for capacity checks by every writer, including direct imports.
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'PRODUCT_CAPACITY_REQUIRES_READ_COMMITTED' USING ERRCODE = '23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('products-capacity:' || NEW.tenant_id::TEXT, 0));
  SELECT * INTO capacity FROM public.product_capacity_for_tenant(NEW.tenant_id);
  IF NOT capacity.included THEN RAISE EXCEPTION 'PRODUCT_CAPACITY_NOT_CONFIGURED' USING ERRCODE = '23514'; END IF;
  IF capacity.limit_value IS NOT NULL AND capacity.current_usage >= capacity.limit_value THEN
    RAISE EXCEPTION 'PRODUCT_CAPACITY_EXCEEDED' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER products_capacity_guard BEFORE INSERT OR UPDATE OF tenant_id, deleted_at ON public.products
FOR EACH ROW EXECUTE FUNCTION public.enforce_product_capacity();

CREATE OR REPLACE FUNCTION public.advance_product_revision()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.version := OLD.version + 1;
  NEW.updated_at := CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$;
CREATE TRIGGER products_revision BEFORE UPDATE ON public.products
FOR EACH ROW EXECUTE FUNCTION public.advance_product_revision();

CREATE OR REPLACE FUNCTION public.trigger_log_price_change()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE saved_tenant TEXT := current_setting('app.current_tenant_id', true);
        saved_user TEXT := current_setting('app.current_user_id', true);
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.current_price IS NOT DISTINCT FROM OLD.current_price AND NEW.currency IS NOT DISTINCT FROM OLD.currency THEN RETURN NEW; END IF;
  PERFORM set_config('app.current_tenant_id', NEW.tenant_id::TEXT, true);
  PERFORM set_config('app.current_user_id', COALESCE(NULLIF(saved_user, ''), 'product-price-audit'), true);
  IF TG_OP = 'INSERT' THEN
    INSERT INTO public.product_price_history (product_id, tenant_id, old_price, new_price, old_currency, currency, changed_by_user_id)
      VALUES (NEW.product_id, NEW.tenant_id, NULL, NEW.current_price, NULL, NEW.currency, NEW.created_by_user_id);
  ELSE
    INSERT INTO public.product_price_history (product_id, tenant_id, old_price, new_price, old_currency, currency, changed_by_user_id)
      VALUES (NEW.product_id, NEW.tenant_id, OLD.current_price, NEW.current_price, OLD.currency, NEW.currency, NEW.updated_by_user_id);
  END IF;
  PERFORM set_config('app.current_tenant_id', COALESCE(saved_tenant, ''), true);
  PERFORM set_config('app.current_user_id', COALESCE(saved_user, ''), true);
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS log_price_change ON public.products;
CREATE TRIGGER log_price_change AFTER INSERT OR UPDATE OF current_price, currency ON public.products
FOR EACH ROW EXECUTE FUNCTION public.trigger_log_price_change();
REVOKE ALL ON FUNCTION public.enforce_product_capacity() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.advance_product_revision() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.trigger_log_price_change() FROM PUBLIC;
-- This function exposes only a tenant's capacity, and validates caller context.
GRANT EXECUTE ON FUNCTION public.product_capacity_for_tenant(UUID) TO PUBLIC;
