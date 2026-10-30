-- Freeze the plan terms a tenant accepted when assigned. The current shared catalog
-- remains the source for future assignments; owner quota changes cannot silently
-- rewrite existing subscription or trial rights.
ALTER TABLE public.tenant_plan_assignments
    ADD COLUMN IF NOT EXISTS catalog_snapshot jsonb;

CREATE OR REPLACE FUNCTION public.keel_capture_plan_catalog_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.plan_key = OLD.plan_key THEN
        IF OLD.catalog_snapshot IS NOT NULL THEN
            NEW.catalog_snapshot := OLD.catalog_snapshot;
            RETURN NEW;
        END IF;
    END IF;

    SELECT jsonb_build_object(
        'catalog_version', (SELECT version FROM public.entitlement_catalog_version WHERE singleton IS TRUE),
        'plan_key', p.plan_key,
        'display_name', p.display_name,
        'features', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'feature_code', f.feature_code, 'unit', f.unit,
                'aggregation_type', f.aggregation_type, 'reset_cycle', f.reset_cycle,
                'limit_value', l.limit_value, 'trial_limit_value', l.trial_limit_value
            ) ORDER BY f.feature_code)
            FROM public.usage_plan_limits l
            JOIN public.usage_features f ON f.feature_code = l.feature_code
            WHERE l.plan_key = p.plan_key
        ), '[]'::jsonb),
        'entitlements', COALESCE((
            SELECT jsonb_agg(e.feature_code ORDER BY e.feature_code)
            FROM public.usage_plan_entitlements e WHERE e.plan_key = p.plan_key
        ), '[]'::jsonb)
    ) INTO NEW.catalog_snapshot
    FROM public.usage_plans p WHERE p.plan_key = NEW.plan_key;

    IF NEW.catalog_snapshot IS NULL THEN
        RAISE EXCEPTION 'plan catalog snapshot unavailable for plan %', NEW.plan_key;
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.keel_capture_plan_catalog_snapshot() FROM PUBLIC;
DROP TRIGGER IF EXISTS tenant_plan_catalog_snapshot ON public.tenant_plan_assignments;
CREATE TRIGGER tenant_plan_catalog_snapshot
    BEFORE INSERT OR UPDATE OF plan_key, catalog_snapshot ON public.tenant_plan_assignments
    FOR EACH ROW EXECUTE FUNCTION public.keel_capture_plan_catalog_snapshot();

-- Backfill currently assigned tenants with the terms already in force at migration time.
UPDATE public.tenant_plan_assignments SET catalog_snapshot = NULL
WHERE catalog_snapshot IS NULL;
