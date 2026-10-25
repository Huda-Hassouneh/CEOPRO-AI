-- Enable immutable Custom Plan infrastructure cost rates and bindings.
-- No rates or commercial values are seeded by this migration.
ALTER TABLE public.billing_custom_cost_rates
  DROP CONSTRAINT IF EXISTS billing_custom_cost_rates_budget_kind_check;
ALTER TABLE public.billing_custom_cost_rates
  ADD CONSTRAINT billing_custom_cost_rates_budget_kind_check
  CHECK (budget_kind IN ('data','ai','infrastructure'));
ALTER TABLE public.billing_custom_cost_rates
  DROP CONSTRAINT IF EXISTS billing_custom_cost_rates_unit_check;
ALTER TABLE public.billing_custom_cost_rates
  ALTER COLUMN unit TYPE VARCHAR(60);
ALTER TABLE public.billing_custom_cost_rates
  ADD CONSTRAINT billing_custom_cost_rates_unit_check
  CHECK (unit ~ '^[A-Za-z][A-Za-z0-9_./-]{0,59}$');

ALTER TABLE public.billing_custom_cost_bindings
  DROP CONSTRAINT IF EXISTS billing_custom_cost_bindings_budget_kind_check;
ALTER TABLE public.billing_custom_cost_bindings
  ADD CONSTRAINT billing_custom_cost_bindings_budget_kind_check
  CHECK (budget_kind IN ('data','ai','infrastructure'));
ALTER TABLE public.billing_custom_cost_bindings
  DROP CONSTRAINT IF EXISTS billing_custom_cost_bindings_usage_basis_check;
ALTER TABLE public.billing_custom_cost_bindings
  ADD CONSTRAINT billing_custom_cost_bindings_usage_basis_check
  CHECK (usage_basis IN ('enabled_feature','limit_value','estimated_usage'));
ALTER TABLE public.billing_custom_cost_bindings
  ALTER COLUMN unit TYPE VARCHAR(60);

-- Canonical feature codes and usage semantics remain fixed in Python. Owner
-- metadata edits change only the catalog labels shown to customers/operators.
ALTER TABLE public.usage_features
  ADD COLUMN IF NOT EXISTS display_name VARCHAR(100),
  ADD COLUMN IF NOT EXISTS display_name_ar VARCHAR(100),
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS description_ar TEXT;

CREATE OR REPLACE FUNCTION public.billing_platform_feature_catalog_command(p_action TEXT, p JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
  v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
  v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
  v_code TEXT:=p->>'feature_code';
  v_old JSONB;
  v_new JSONB;
  v_result JSONB;
BEGIN
  IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
    OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
      WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
    OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
    RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
  END IF;
  IF p_action='list' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.feature_code),'[]'::jsonb) INTO v_result
      FROM public.usage_features f;
    RETURN jsonb_build_object('features',v_result);
  ELSIF p_action='update_metadata' THEN
    SELECT to_jsonb(f) INTO v_old FROM public.usage_features f WHERE f.feature_code=v_code FOR UPDATE;
    IF v_old IS NULL THEN RAISE EXCEPTION 'feature not found' USING ERRCODE='P0002'; END IF;
    IF length(btrim(coalesce(p->>'display_name','')))=0 OR length(btrim(coalesce(p->>'display_name_ar','')))=0 THEN
      RAISE EXCEPTION 'localized feature names are required' USING ERRCODE='22023';
    END IF;
    UPDATE public.usage_features SET display_name=btrim(p->>'display_name'),display_name_ar=btrim(p->>'display_name_ar'),
      description=nullif(btrim(p->>'description'),''),description_ar=nullif(btrim(p->>'description_ar'),'')
      WHERE feature_code=v_code RETURNING to_jsonb(usage_features) INTO v_new;
    INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
      VALUES(v_actor,'owner','feature_catalog_metadata_update',v_code,
        v_old-ARRAY['display_name','display_name_ar','description','description_ar'],
        v_new-ARRAY['display_name','display_name_ar','description','description_ar'],
        nullif(btrim(p->>'reason'),''),'succeeded');
    RETURN v_new;
  END IF;
  RAISE EXCEPTION 'unsupported feature catalog command' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.billing_platform_feature_catalog_command(TEXT,JSONB) FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
    GRANT EXECUTE ON FUNCTION public.billing_platform_feature_catalog_command(TEXT,JSONB) TO ceopro_app;
  END IF;
END $$;
