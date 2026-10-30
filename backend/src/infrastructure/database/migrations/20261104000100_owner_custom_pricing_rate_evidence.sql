-- Narrow owner-only read command. Do not grant tenant requests direct access
-- to the private accounting provider_cost_schedules table.
CREATE FUNCTION public.billing_custom_pricing_rate_evidence(
 p_policy UUID, p_features TEXT[], p_as_of TIMESTAMPTZ)
RETURNS TABLE (
 binding_id UUID, feature_code TEXT, cost_category TEXT, budget_kind TEXT,
 provider TEXT, operation TEXT, unit TEXT, usage_basis TEXT,
 units_per_feature_unit NUMERIC, operational_multiplier NUMERIC,
 variability_reserve NUMERIC, required_for_price BOOLEAN,
 effective_from TIMESTAMPTZ, effective_to TIMESTAMPTZ, binding_source TEXT,
 usage_assumption JSONB, rate_id UUID, unit_cost_usd NUMERIC,
 safety_margin NUMERIC, cost_is_final BOOLEAN, rate_source TEXT,
 verified_at DATE, updated_at TIMESTAMPTZ)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL
    OR NOT public.keel_active_principal(v_actor,v_tenant)
    OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m
      JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
      WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
    OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor
      AND u.platform_disabled_at IS NOT NULL) THEN
   RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
 END IF;
 RETURN QUERY
 SELECT b.binding_id,b.feature_code,b.cost_category,b.budget_kind::text,
        b.provider::text,b.operation::text,b.unit::text,b.usage_basis,
        b.units_per_feature_unit,b.operational_multiplier,b.variability_reserve,
        b.required_for_price,b.effective_from,b.effective_to,b.source,
        b.usage_assumption,coalesce(cr.cost_rate_id,p.schedule_id),
        coalesce(cr.unit_cost_usd,p.unit_cost_usd),p.safety_margin,
        coalesce(cr.cost_rate_id IS NOT NULL,p.cost_is_final),
        coalesce(cr.source,p.source),coalesce(cr.verified_at,p.verified_at),
        coalesce(cr.created_at,p.updated_at)
 FROM public.billing_custom_cost_bindings b
 LEFT JOIN public.billing_custom_cost_rates cr ON cr.cost_rate_id=b.cost_rate_id
   AND cr.effective_from<=p_as_of AND (cr.effective_to IS NULL OR cr.effective_to>p_as_of)
 LEFT JOIN public.provider_cost_schedules p ON b.cost_rate_id IS NULL
   AND p.budget_kind=b.budget_kind AND p.provider=b.provider
   AND p.operation=b.operation AND p.unit=b.unit AND p.updated_at<=p_as_of
 WHERE b.policy_version_id=p_policy AND b.feature_code=ANY(p_features)
   AND b.effective_from<=p_as_of AND (b.effective_to IS NULL OR b.effective_to>p_as_of)
 ORDER BY b.feature_code,b.cost_category,b.binding_id;
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_pricing_rate_evidence(UUID,TEXT[],TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_custom_pricing_rate_evidence(UUID,TEXT[],TIMESTAMPTZ) TO ceopro_app;
