-- ENT-009: shared generations for tenant entitlement inputs and the plan catalog.
-- This records state changes only; it does not modify plans, assignments, trials,
-- overrides, customer terms, usage, or credit balances.

CREATE TABLE IF NOT EXISTS public.entitlement_version_state (
    tenant_id UUID PRIMARY KEY REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0)
);

INSERT INTO public.entitlement_version_state (tenant_id, version)
SELECT tenant_id, 1 FROM public.companies
ON CONFLICT (tenant_id) DO NOTHING;

ALTER TABLE public.entitlement_version_state ENABLE ROW LEVEL SECURITY;
-- The owning SECURITY DEFINER trigger functions maintain this internal table;
-- RLS remains enabled for ceopro_app, which receives SELECT only.
ALTER TABLE public.entitlement_version_state NO FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS isolation_entitlement_version_state ON public.entitlement_version_state;
CREATE POLICY isolation_entitlement_version_state
    ON public.entitlement_version_state
    FOR SELECT USING (tenant_id = public.get_current_tenant());

REVOKE ALL ON public.entitlement_version_state FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON public.entitlement_version_state FROM ceopro_app;
        GRANT SELECT ON public.entitlement_version_state TO ceopro_app;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.entitlement_catalog_version (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0)
);
INSERT INTO public.entitlement_catalog_version (singleton, version)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

ALTER TABLE public.entitlement_catalog_version ENABLE ROW LEVEL SECURITY;
-- The owning SECURITY DEFINER trigger function updates this singleton; the
-- application role is restricted to the singleton SELECT policy below.
ALTER TABLE public.entitlement_catalog_version NO FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS read_entitlement_catalog_version ON public.entitlement_catalog_version;
CREATE POLICY read_entitlement_catalog_version
    ON public.entitlement_catalog_version
    FOR SELECT USING (singleton IS TRUE);

REVOKE ALL ON public.entitlement_catalog_version FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON public.entitlement_catalog_version FROM ceopro_app;
        GRANT SELECT ON public.entitlement_catalog_version TO ceopro_app;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.keel_bump_entitlement_tenant_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_tenant_id UUID;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        v_tenant_id := OLD.tenant_id;
        -- Do not recreate the version row while a company is being deleted.
        UPDATE public.entitlement_version_state
           SET version = version + 1
         WHERE tenant_id = v_tenant_id;
        RETURN OLD;
    END IF;

    v_tenant_id := NEW.tenant_id;
    INSERT INTO public.entitlement_version_state (tenant_id, version)
    VALUES (v_tenant_id, 1)
    ON CONFLICT (tenant_id) DO UPDATE
       SET version = public.entitlement_version_state.version + 1;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.keel_bump_entitlement_tenant_version() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.keel_bump_entitlement_catalog_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE public.entitlement_catalog_version
       SET version = version + 1
     WHERE singleton IS TRUE;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.keel_bump_entitlement_catalog_version() FROM PUBLIC;

DROP TRIGGER IF EXISTS entitlement_version_assignment ON public.tenant_plan_assignments;
CREATE TRIGGER entitlement_version_assignment
    AFTER INSERT OR UPDATE OR DELETE ON public.tenant_plan_assignments
    FOR EACH ROW EXECUTE FUNCTION public.keel_bump_entitlement_tenant_version();

DROP TRIGGER IF EXISTS entitlement_version_trial ON public.billing_trials;
CREATE TRIGGER entitlement_version_trial
    AFTER INSERT OR UPDATE OR DELETE ON public.billing_trials
    FOR EACH ROW EXECUTE FUNCTION public.keel_bump_entitlement_tenant_version();

DROP TRIGGER IF EXISTS entitlement_version_override ON public.tenant_entitlement_overrides;
CREATE TRIGGER entitlement_version_override
    AFTER INSERT OR UPDATE OR DELETE ON public.tenant_entitlement_overrides
    FOR EACH ROW EXECUTE FUNCTION public.keel_bump_entitlement_tenant_version();

DROP TRIGGER IF EXISTS entitlement_catalog_version_plans ON public.usage_plans;
CREATE TRIGGER entitlement_catalog_version_plans
    AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.usage_plans
    FOR EACH STATEMENT EXECUTE FUNCTION public.keel_bump_entitlement_catalog_version();

DROP TRIGGER IF EXISTS entitlement_catalog_version_limits ON public.usage_plan_limits;
CREATE TRIGGER entitlement_catalog_version_limits
    AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.usage_plan_limits
    FOR EACH STATEMENT EXECUTE FUNCTION public.keel_bump_entitlement_catalog_version();

DROP TRIGGER IF EXISTS entitlement_catalog_version_features ON public.usage_features;
CREATE TRIGGER entitlement_catalog_version_features
    AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.usage_features
    FOR EACH STATEMENT EXECUTE FUNCTION public.keel_bump_entitlement_catalog_version();

DROP TRIGGER IF EXISTS entitlement_catalog_version_entitlements ON public.usage_plan_entitlements;
CREATE TRIGGER entitlement_catalog_version_entitlements
    AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.usage_plan_entitlements
    FOR EACH STATEMENT EXECUTE FUNCTION public.keel_bump_entitlement_catalog_version();
