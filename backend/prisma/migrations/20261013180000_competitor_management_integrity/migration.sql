-- Preserve existing competitors and history. New tracking must fit the active plan.
ALTER TABLE public.competitor_product_mappings ADD COLUMN IF NOT EXISTS tracking_paused BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.competitor_product_mappings ADD COLUMN IF NOT EXISTS comparison_confirmed BOOLEAN NOT NULL DEFAULT FALSE;

CREATE OR REPLACE FUNCTION public.competitor_capacity_for_tenant(request_tenant UUID)
RETURNS TABLE(current_usage BIGINT, limit_value INTEGER, is_unlimited BOOLEAN, included BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  saved_tenant TEXT := current_setting('app.current_tenant_id', true);
  saved_user TEXT := current_setting('app.current_user_id', true);
  caller TEXT := COALESCE(NULLIF(current_setting('role', true), 'none'), session_user::TEXT);
  plan UUID; used BIGINT; cap INTEGER; enabled BOOLEAN := FALSE;
BEGIN
  -- Application calls require matching tenant context; trigger calls preserve table RLS.
  IF caller <> current_user::TEXT
     AND public.get_current_tenant() IS DISTINCT FROM request_tenant THEN
    RAISE EXCEPTION 'COMPETITOR_TENANT_REQUIRED' USING ERRCODE = '23514';
  END IF;
  IF public.get_current_tenant() IS NOT NULL AND public.get_current_tenant() <> request_tenant THEN
    RAISE EXCEPTION 'COMPETITOR_TENANT_REQUIRED' USING ERRCODE = '23514';
  END IF;
  -- Temporary context is limited to this tenant inside the definer function.
  -- It is restored before returning; caller table privileges/RLS are unchanged.
  PERFORM set_config('app.current_tenant_id', request_tenant::TEXT, true);
  PERFORM set_config('app.current_user_id', COALESCE(NULLIF(saved_user, ''), 'competitor-capacity-guard'), true);
  SELECT count(*) INTO used FROM public.tenant_competitors WHERE tenant_id = request_tenant AND is_tracked = TRUE;
  SELECT plan_id INTO plan FROM public.subscriptions
    WHERE tenant_id = request_tenant AND status IN ('active', 'trialing')
    ORDER BY updated_at DESC, created_at DESC LIMIT 1 FOR SHARE;
  IF plan IS NOT NULL AND EXISTS (
    SELECT 1 FROM public.plan_features pf JOIN public.features f ON f.feature_id = pf.feature_id
    WHERE pf.plan_id = plan AND f.feature_code = 'competitor_management' AND f.feature_type = 'boolean'
  ) THEN
    SELECT pf.limit_value INTO cap FROM public.plan_features pf JOIN public.features f ON f.feature_id = pf.feature_id
      WHERE pf.plan_id = plan AND f.feature_code = 'tracked_competitors' AND f.feature_type = 'limit'
        AND f.aggregation_type = 'max' AND f.reset_cycle = 'lifetime';
    enabled := FOUND;
  END IF;
  PERFORM set_config('app.current_tenant_id', COALESCE(saved_tenant, ''), true);
  PERFORM set_config('app.current_user_id', COALESCE(saved_user, ''), true);
  RETURN QUERY SELECT used, CASE WHEN enabled THEN cap ELSE 0 END, enabled AND cap IS NULL, enabled;
END;
$$;

CREATE OR REPLACE FUNCTION public.enforce_competitor_capacity()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE capacity RECORD;
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.global_competitor_id IS DISTINCT FROM OLD.global_competitor_id) THEN
    RAISE EXCEPTION 'COMPETITOR_TENANT_IMMUTABLE' USING ERRCODE = '23514';
  END IF;
  IF NOT NEW.is_tracked THEN RETURN NEW; END IF;
  -- ON CONFLICT retries of an already tracked relationship do not consume capacity.
  IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM public.tenant_competitors
      WHERE tenant_id = NEW.tenant_id AND global_competitor_id = NEW.global_competitor_id AND is_tracked = TRUE) THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND OLD.is_tracked = TRUE THEN RETURN NEW; END IF;
  -- A fresh READ COMMITTED snapshot after waiting on the common lock is
  -- required for capacity checks by every writer, including direct imports.
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'COMPETITOR_CAPACITY_REQUIRES_READ_COMMITTED' USING ERRCODE = '23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('competitors-capacity:' || NEW.tenant_id::TEXT, 0));
  SELECT * INTO capacity FROM public.competitor_capacity_for_tenant(NEW.tenant_id);
  IF NOT capacity.included THEN RAISE EXCEPTION 'COMPETITOR_CAPACITY_NOT_CONFIGURED' USING ERRCODE = '23514'; END IF;
  IF capacity.limit_value IS NOT NULL AND capacity.current_usage >= capacity.limit_value THEN
    RAISE EXCEPTION 'COMPETITOR_CAPACITY_EXCEEDED' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER competitors_capacity_guard BEFORE INSERT OR UPDATE OF tenant_id, is_tracked, global_competitor_id ON public.tenant_competitors
FOR EACH ROW EXECUTE FUNCTION public.enforce_competitor_capacity();


REVOKE ALL ON FUNCTION public.enforce_competitor_capacity() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.competitor_capacity_for_tenant(UUID) TO PUBLIC;

-- A mapping changed by discovery must be reviewed again before comparing packs/units.
CREATE OR REPLACE FUNCTION public.reset_competitor_mapping_confirmation()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF NEW.product_id IS DISTINCT FROM OLD.product_id OR NEW.global_competitor_id IS DISTINCT FROM OLD.global_competitor_id
     OR NEW.competitor_product_url IS DISTINCT FROM OLD.competitor_product_url
     OR NEW.competitor_product_sku IS DISTINCT FROM OLD.competitor_product_sku THEN
    NEW.comparison_confirmed := FALSE;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER competitor_mapping_confirmation_guard BEFORE UPDATE ON public.competitor_product_mappings
FOR EACH ROW EXECUTE FUNCTION public.reset_competitor_mapping_confirmation();
REVOKE ALL ON FUNCTION public.reset_competitor_mapping_confirmation() FROM PUBLIC;

-- Pause only active mappings; restore only mappings paused by untracking.
CREATE OR REPLACE FUNCTION public.sync_competitor_tracking_mappings()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF OLD.is_tracked IS NOT DISTINCT FROM NEW.is_tracked THEN RETURN NEW; END IF;
  IF NEW.is_tracked THEN
    UPDATE public.competitor_product_mappings SET is_active = TRUE, tracking_paused = FALSE
      WHERE tenant_id = NEW.tenant_id AND global_competitor_id = NEW.global_competitor_id AND tracking_paused = TRUE;
  ELSE
    UPDATE public.competitor_product_mappings SET is_active = FALSE, tracking_paused = TRUE
      WHERE tenant_id = NEW.tenant_id AND global_competitor_id = NEW.global_competitor_id AND is_active = TRUE;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER competitor_tracking_mappings AFTER UPDATE OF is_tracked ON public.tenant_competitors
FOR EACH ROW EXECUTE FUNCTION public.sync_competitor_tracking_mappings();

CREATE OR REPLACE FUNCTION public.guard_untracked_competitor_mapping()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF NEW.is_active AND EXISTS (SELECT 1 FROM public.tenant_competitors
      WHERE tenant_id = NEW.tenant_id AND global_competitor_id = NEW.global_competitor_id AND NOT is_tracked) THEN
    NEW.is_active := FALSE; NEW.tracking_paused := TRUE;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER competitor_mapping_tracking_guard BEFORE INSERT OR UPDATE ON public.competitor_product_mappings
FOR EACH ROW EXECUTE FUNCTION public.guard_untracked_competitor_mapping();
REVOKE ALL ON FUNCTION public.sync_competitor_tracking_mappings() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_untracked_competitor_mapping() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.reset_catalog_competitor_confirmations()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF NEW.product_name IS DISTINCT FROM OLD.product_name OR NEW.sku IS DISTINCT FROM OLD.sku THEN
    UPDATE public.competitor_product_mappings SET comparison_confirmed = FALSE
      WHERE tenant_id = NEW.tenant_id AND product_id = NEW.product_id AND comparison_confirmed = TRUE;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER catalog_competitor_confirmation_guard AFTER UPDATE OF product_name, sku ON public.products
FOR EACH ROW EXECUTE FUNCTION public.reset_catalog_competitor_confirmations();
REVOKE ALL ON FUNCTION public.reset_catalog_competitor_confirmations() FROM PUBLIC;
