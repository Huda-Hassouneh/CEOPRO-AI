-- The original function parameter is named p. Use a distinct table alias in
-- policy_list so PostgreSQL does not resolve p as both the JSON argument and
-- the pricing-policy row variable.
CREATE OR REPLACE FUNCTION public.billing_custom_pricing_admin_command(p_action TEXT,p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_policy UUID; v_rate UUID; v_binding UUID; v_row RECORD; v_count INTEGER; v_result JSONB;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
    OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
                  WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
    OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
   RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
 END IF;
 IF p_action='policy_list' THEN
   SELECT coalesce(jsonb_agg(to_jsonb(pricing_policy) ORDER BY pricing_policy.version_number DESC),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_pricing_policies pricing_policy;
   RETURN jsonb_build_object('policies',v_result);
 ELSIF p_action='rate_list' THEN
   SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.provider,r.operation,r.unit,r.effective_from),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_cost_rates r;
   RETURN jsonb_build_object('cost_rates',v_result);
 ELSIF p_action='binding_list' THEN
   v_policy:=(p->>'policy_version_id')::uuid;
   SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.feature_code,b.cost_category,b.effective_from),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_cost_bindings b WHERE b.policy_version_id=v_policy;
   RETURN jsonb_build_object('bindings',v_result);
 ELSIF p_action='policy_create' THEN
   INSERT INTO public.billing_custom_pricing_policies(quote_currency,target_gross_margin,enforce_vendor_cost_ratio_floor,
     max_vendor_cost_revenue_ratio,fixed_platform_fee_usd,upward_rounding_increment_usd,
     monthly_shared_infrastructure_cost_usd,active_paying_tenant_count,approved_by,approval_evidence)
   VALUES('USD',nullif(p->>'target_gross_margin','')::numeric,nullif(p->>'enforce_vendor_cost_ratio_floor','')::boolean,
     nullif(p->>'max_vendor_cost_revenue_ratio','')::numeric,nullif(p->>'fixed_platform_fee_usd','')::numeric,
     nullif(p->>'upward_rounding_increment_usd','')::numeric,nullif(p->>'monthly_shared_infrastructure_cost_usd','')::numeric,
     nullif(p->>'active_paying_tenant_count','')::bigint,v_actor::text,nullif(btrim(p->>'approval_evidence'),''))
   RETURNING policy_version_id INTO v_policy;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_policy_draft_created','pricing_policy',jsonb_build_object('policy_version_id',v_policy),v_actor::text,
      coalesce(nullif(p->>'approval_evidence',''),'Draft policy setup'));
   RETURN jsonb_build_object('policy_version_id',v_policy,'status','draft');
 ELSIF p_action='rate_create' THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('custom_cost_rate:'||(p->>'budget_kind')||':'||lower(btrim(p->>'provider'))||':'||lower(btrim(p->>'operation'))||':'||(p->>'unit'),0));
   INSERT INTO public.billing_custom_cost_rates(budget_kind,provider,operation,unit,unit_cost_usd,source,verified_at,
      effective_from,effective_to,verified_by,verification_evidence)
   VALUES(p->>'budget_kind',lower(btrim(p->>'provider')),lower(btrim(p->>'operation')),p->>'unit',
      (p->>'unit_cost_usd')::numeric,nullif(btrim(p->>'source'),''),(p->>'verified_at')::date,
      (p->>'effective_from')::timestamptz,nullif(p->>'effective_to','')::timestamptz,v_actor::text,
      nullif(btrim(p->>'verification_evidence'),'')) RETURNING cost_rate_id INTO v_rate;
   IF EXISTS(SELECT 1 FROM public.billing_custom_cost_rates r WHERE r.cost_rate_id<>v_rate
      AND (r.budget_kind,r.provider,r.operation,r.unit)=(p->>'budget_kind',lower(btrim(p->>'provider')),
       lower(btrim(p->>'operation')),p->>'unit')
      AND tstzrange(r.effective_from,r.effective_to,'[)') && tstzrange((p->>'effective_from')::timestamptz,
       nullif(p->>'effective_to','')::timestamptz,'[)')) THEN
     RAISE EXCEPTION 'overlapping provider rate effective dates' USING ERRCODE='23P01';
   END IF;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_rate_created','pricing_cost_rate',jsonb_build_object('cost_rate_id',v_rate,
      'provider',p->>'provider','operation',p->>'operation','unit',p->>'unit'),v_actor::text,p->>'verification_evidence');
   RETURN jsonb_build_object('cost_rate_id',v_rate,'status','verified');
 ELSIF p_action='rate_close' THEN
   v_rate:=(p->>'cost_rate_id')::uuid;
   UPDATE public.billing_custom_cost_rates SET effective_to=(p->>'effective_to')::timestamptz
    WHERE cost_rate_id=v_rate AND effective_to IS NULL
      AND (p->>'effective_to')::timestamptz>effective_from
      AND (p->>'effective_to')::timestamptz IS NOT NULL;
   IF NOT FOUND THEN RAISE EXCEPTION 'current rate or valid close date required' USING ERRCODE='55000'; END IF;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_rate_closed','pricing_cost_rate',jsonb_build_object('cost_rate_id',v_rate,
      'effective_to',p->>'effective_to'),v_actor::text,coalesce(nullif(p->>'reason',''),'Rate version closed'));
   RETURN jsonb_build_object('cost_rate_id',v_rate,'status','closed');
 ELSIF p_action='binding_create' THEN
   v_policy:=(p->>'policy_version_id')::uuid; v_rate:=(p->>'cost_rate_id')::uuid;
   IF NOT EXISTS(SELECT 1 FROM public.billing_custom_pricing_policies WHERE policy_version_id=v_policy AND status='draft') THEN
      RAISE EXCEPTION 'bindings require a draft pricing policy' USING ERRCODE='55000'; END IF;
   IF NOT EXISTS(SELECT 1 FROM public.billing_custom_cost_rates WHERE cost_rate_id=v_rate
      AND effective_from <= clock_timestamp() AND (effective_to IS NULL OR effective_to>clock_timestamp())) THEN
      RAISE EXCEPTION 'effective verified cost rate required' USING ERRCODE='22023'; END IF;
   SELECT * INTO v_row FROM public.billing_custom_cost_rates WHERE cost_rate_id=v_rate;
   INSERT INTO public.billing_custom_cost_bindings(policy_version_id,feature_code,cost_category,budget_kind,provider,
     operation,unit,usage_basis,units_per_feature_unit,operational_multiplier,variability_reserve,required_for_price,
     usage_assumption,effective_from,effective_to,source,created_by,cost_rate_id)
   VALUES(v_policy,p->>'feature_code',p->>'cost_category',v_row.budget_kind,v_row.provider,v_row.operation,v_row.unit,
     p->>'usage_basis',(p->>'units_per_feature_unit')::numeric,nullif(p->>'operational_multiplier','')::numeric,
     nullif(p->>'variability_reserve','')::numeric,coalesce((p->>'required_for_price')::boolean,true),
     coalesce(p->'usage_assumption','{}'::jsonb),greatest((p->>'effective_from')::timestamptz,v_row.effective_from),
     CASE WHEN p->>'effective_to' IS NULL OR p->>'effective_to'='' THEN v_row.effective_to ELSE (p->>'effective_to')::timestamptz END,
     nullif(btrim(p->>'source'),''),v_actor::text,v_rate) RETURNING binding_id INTO v_binding;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_binding_created','pricing_binding',jsonb_build_object('binding_id',v_binding,
      'policy_version_id',v_policy,'cost_rate_id',v_rate,'feature_code',p->>'feature_code'),v_actor::text,p->>'source');
   RETURN jsonb_build_object('binding_id',v_binding,'status','draft');
 ELSIF p_action='policy_activate' THEN
   v_policy:=(p->>'policy_version_id')::uuid;
   SELECT * INTO v_row FROM public.billing_custom_pricing_policies WHERE policy_version_id=v_policy FOR UPDATE;
   IF NOT FOUND OR v_row.status<>'draft' THEN RAISE EXCEPTION 'draft policy required' USING ERRCODE='55000'; END IF;
   SELECT count(*) INTO v_count FROM public.billing_custom_cost_bindings b LEFT JOIN public.billing_custom_cost_rates r ON r.cost_rate_id=b.cost_rate_id
    WHERE b.policy_version_id=v_policy AND b.required_for_price AND (r.cost_rate_id IS NULL OR r.verified_at>CURRENT_DATE
      OR r.effective_from>clock_timestamp() OR (r.effective_to IS NOT NULL AND r.effective_to<=clock_timestamp()));
   IF v_count>0 THEN RAISE EXCEPTION 'all required bindings need effective verified rates' USING ERRCODE='22023'; END IF;
   IF EXISTS(SELECT 1 FROM public.billing_custom_cost_bindings b WHERE b.policy_version_id=v_policy AND b.required_for_price
      GROUP BY b.feature_code,b.cost_category HAVING count(*)=0) THEN RAISE EXCEPTION 'invalid policy bindings' USING ERRCODE='22023'; END IF;
   UPDATE public.billing_custom_pricing_policies SET status='retired',effective_to=clock_timestamp()
    WHERE status='active' AND effective_to IS NULL;
   UPDATE public.billing_custom_pricing_policies SET status='active',effective_from=coalesce(effective_from,clock_timestamp()),
     approved_by=v_actor::text,approval_evidence=nullif(btrim(p->>'approval_evidence'), '') WHERE policy_version_id=v_policy;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_policy_activated','pricing_policy',jsonb_build_object('policy_version_id',v_policy,
      'version',v_row.version_number),v_actor::text,p->>'approval_evidence');
   RETURN jsonb_build_object('policy_version_id',v_policy,'status','active');
 END IF;
 RAISE EXCEPTION 'unsupported pricing administration command' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_pricing_admin_command(TEXT,JSONB) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_pricing_admin_command(TEXT,JSONB) TO ceopro_app; END IF; END $$;
