-- Owner-only read models for the integrated billing administration UI.
-- No mutations or commercial defaults are introduced here.
CREATE OR REPLACE FUNCTION public.billing_platform_owner_read(p_action TEXT, p_limit INTEGER DEFAULT 100, p_offset INTEGER DEFAULT 0)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_actor UUID := nullif(current_setting('app.current_user_id', true), '')::uuid;
  v_tenant UUID := nullif(current_setting('app.current_tenant_id', true), '')::uuid;
  v_result JSONB;
BEGIN
  IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
     OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
                   WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
     OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
    RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
  END IF;
  IF p_limit < 1 OR p_limit > 200 OR p_offset < 0 THEN
    RAISE EXCEPTION 'invalid page bounds' USING ERRCODE='22023';
  END IF;

  IF p_action='quotes' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.updated_at DESC),'[]'::jsonb) INTO v_result
    FROM (
      SELECT q.quote_id,q.tenant_id,c.business_name,q.customer_user_id,u.email AS customer_email,
        u.full_name AS customer_name,q.state,q.current_revision_id,q.row_version,q.created_at,q.updated_at,
        r.revision_number,r.state AS revision_state,r.configuration,r.feature_quantities,r.commercial_terms,
        r.valid_until,r.approved_at,r.accepted_at
      FROM public.billing_custom_quotes q
      JOIN public.companies c ON c.tenant_id=q.tenant_id
      LEFT JOIN public.users u ON u.user_id=q.customer_user_id
      LEFT JOIN public.billing_custom_quote_revisions r
        ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id AND r.revision_id=q.current_revision_id
      ORDER BY q.updated_at DESC,q.quote_id
      LIMIT p_limit OFFSET p_offset
    ) x;
    RETURN jsonb_build_object('quotes',v_result,'limit',p_limit,'offset',p_offset);
  ELSIF p_action='plans' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.plan_key),'[]'::jsonb) INTO v_result
    FROM (
      SELECT p.plan_key,p.display_name,p.display_name_ar,p.monthly_price,p.currency,p.trial_days,p.tier_level,
             p.self_serve,p.is_active,
        coalesce((SELECT jsonb_agg(jsonb_build_object('feature_code',f.feature_code,'unit',f.unit,
          'aggregation_type',f.aggregation_type,'reset_cycle',f.reset_cycle,'limit_value',l.limit_value,
          'trial_limit_value',l.trial_limit_value) ORDER BY f.feature_code)
          FROM public.usage_plan_limits l JOIN public.usage_features f USING(feature_code)
          WHERE l.plan_key=p.plan_key),'[]'::jsonb) AS feature_limits,
        coalesce((SELECT jsonb_agg(to_jsonb(bp) ORDER BY bp.interval_months)
          FROM public.billing_plan_prices bp WHERE bp.plan_key=p.plan_key AND bp.retired_at IS NULL),'[]'::jsonb) AS prices,
        coalesce((SELECT jsonb_agg(e.feature_code ORDER BY e.feature_code)
          FROM public.usage_plan_entitlements e WHERE e.plan_key=p.plan_key),'[]'::jsonb) AS entitlements
      FROM public.usage_plans p
    ) x;
    RETURN jsonb_build_object('plans',v_result);
  ELSIF p_action='subscriptions' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.updated_at DESC NULLS LAST),'[]'::jsonb) INTO v_result
    FROM (
      SELECT s.subscription_id,s.tenant_id,c.business_name,s.plan_key,p.display_name AS plan_name,
        s.period_code,s.status,s.current_period_start,s.current_period_end,s.trial_end,s.cancel_at_period_end,
        s.cancelled_at,s.scheduled_plan_key,s.scheduled_period_code,s.stripe_subscription_id,
        s.stripe_customer_id,s.stripe_price_id,s.last_event_at,s.created_at,s.updated_at,
        a.source AS assignment_source,t.ends_at AS trial_ends_at,cc.contract_ref
      FROM public.billing_subscriptions s
      JOIN public.companies c ON c.tenant_id=s.tenant_id
      LEFT JOIN public.usage_plans p ON p.plan_key=s.plan_key
      LEFT JOIN public.tenant_plan_assignments a ON a.tenant_id=s.tenant_id
      LEFT JOIN public.billing_trials t ON t.tenant_id=s.tenant_id
      LEFT JOIN public.tenant_custom_contracts cc ON cc.tenant_id=s.tenant_id
      ORDER BY s.updated_at DESC NULLS LAST,s.subscription_id
      LIMIT p_limit OFFSET p_offset
    ) x;
    RETURN jsonb_build_object('subscriptions',v_result,'limit',p_limit,'offset',p_offset);
  ELSIF p_action='contracts' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.updated_at DESC NULLS LAST),'[]'::jsonb) INTO v_result
    FROM (
      SELECT cc.tenant_id,c.business_name,cc.contract_ref,cc.monthly_price,cc.currency,cc.trial_days,
        cc.data_sources,cc.included_features,cc.refresh_frequency,cc.support_level,cc.approved_by,cc.reason,
        cc.approved_at,cc.created_at,a.status AS assignment_status,a.current_period_start,
        a.current_period_end,a.period_code,
        coalesce((SELECT jsonb_agg(jsonb_build_object('feature_code',o.feature_code,'limit_value',o.limit_value)
          ORDER BY o.feature_code) FROM public.tenant_entitlement_overrides o
          WHERE o.tenant_id=cc.tenant_id),'[]'::jsonb) AS overrides
      FROM public.tenant_custom_contracts cc
      JOIN public.companies c ON c.tenant_id=cc.tenant_id
      LEFT JOIN public.tenant_plan_assignments a ON a.tenant_id=cc.tenant_id
      ORDER BY cc.approved_at DESC NULLS LAST,cc.tenant_id
      LIMIT p_limit OFFSET p_offset
    ) x;
    RETURN jsonb_build_object('contracts',v_result,'limit',p_limit,'offset',p_offset);
  ELSIF p_action='audit' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC),'[]'::jsonb) INTO v_result
    FROM (
      SELECT audit_id,tenant_id,action,subject,old_value,new_value,contract_ref,approved_by,reason,created_at
      FROM public.entitlement_audit_log
      ORDER BY created_at DESC,audit_id DESC
      LIMIT p_limit OFFSET p_offset
    ) x;
    RETURN jsonb_build_object('audit',v_result,'limit',p_limit,'offset',p_offset);
  END IF;
  RAISE EXCEPTION 'unsupported platform billing read' USING ERRCODE='22023';
END
$$;
REVOKE ALL ON FUNCTION public.billing_platform_owner_read(TEXT,INTEGER,INTEGER) FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
    GRANT EXECUTE ON FUNCTION public.billing_platform_owner_read(TEXT,INTEGER,INTEGER) TO ceopro_app;
  END IF;
END $$;
