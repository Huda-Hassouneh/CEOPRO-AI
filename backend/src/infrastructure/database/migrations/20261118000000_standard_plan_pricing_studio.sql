-- Analysis evidence only. No customer price, assignment, schedule or ledger writes.
CREATE TABLE public.billing_plan_analysis_policies (
 policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), version BIGSERIAL UNIQUE NOT NULL,
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 effective_from TIMESTAMPTZ NOT NULL, assumptions JSONB NOT NULL CHECK(jsonb_typeof(assumptions)='object'),
 created_by TEXT NOT NULL, reason TEXT NOT NULL CHECK(length(btrim(reason))>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
CREATE TABLE public.billing_plan_analyses (
 analysis_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 plan_key TEXT NOT NULL REFERENCES public.usage_plans(plan_key), mode TEXT NOT NULL CHECK(mode IN('analyze','simulate')),
 policy_id UUID REFERENCES public.billing_plan_analysis_policies(policy_id),
 snapshot JSONB NOT NULL CHECK(jsonb_typeof(snapshot)='object'), source_hash TEXT NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
ALTER TABLE public.billing_plan_analysis_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_plan_analysis_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE public.billing_plan_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_plan_analyses FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_plan_analysis_policies,public.billing_plan_analyses FROM PUBLIC,ceopro_app;
CREATE FUNCTION public.billing_plan_studio_immutable() RETURNS TRIGGER LANGUAGE plpgsql
 SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_OP='DELETE' AND pg_trigger_depth()>1 THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'pricing analysis and policy evidence is append only' USING ERRCODE='42501'; END $$;
CREATE TRIGGER billing_plan_policy_immutable BEFORE UPDATE OR DELETE ON public.billing_plan_analysis_policies
 FOR EACH ROW EXECUTE FUNCTION public.billing_plan_studio_immutable();
CREATE TRIGGER billing_plan_analysis_immutable BEFORE UPDATE OR DELETE ON public.billing_plan_analyses
 FOR EACH ROW EXECUTE FUNCTION public.billing_plan_studio_immutable();
REVOKE ALL ON FUNCTION public.billing_plan_studio_immutable() FROM PUBLIC;

CREATE FUNCTION public.billing_plan_studio(p_action TEXT,p JSONB DEFAULT '{}') RETURNS JSONB
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 selected public.billing_plan_analysis_policies%ROWTYPE;
 pol JSONB; plans JSONB; features JSONB; observations JSONB; bindings JSONB:='[]'; result JSONB;
 ident UUID; as_of TIMESTAMPTZ:=clock_timestamp(); window_start TIMESTAMPTZ:=clock_timestamp()-interval '30 days';
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
 OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
   WHERE m.user_id=actor AND m.role_key='owner' AND m.status='active')
 OR EXISTS(SELECT 1 FROM public.users WHERE user_id=actor AND platform_disabled_at IS NOT NULL) THEN
 RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501'; END IF;
 IF p_action='create_policy' THEN
  IF jsonb_typeof(p->'assumptions') IS DISTINCT FROM 'object' OR nullif(btrim(p->>'reason'),'') IS NULL THEN
   RAISE EXCEPTION 'explicit assumptions and reason required' USING ERRCODE='22023'; END IF;
  IF p#>>'{assumptions,cost_binding_policy_id}' IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM public.billing_custom_pricing_policies WHERE policy_version_id=(p#>>'{assumptions,cost_binding_policy_id}')::uuid
    AND status IN('active','retired')) THEN
   RAISE EXCEPTION 'approved economic cost binding policy required' USING ERRCODE='22023'; END IF;
  INSERT INTO public.billing_plan_analysis_policies(tenant_id,effective_from,assumptions,created_by,reason)
   VALUES(tenant,(p->>'effective_from')::timestamptz,p->'assumptions',actor::text,p->>'reason') RETURNING policy_id INTO ident;
  INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
   VALUES(tenant,'plan_analysis_policy_created','plan_analysis_policy',jsonb_build_object('policy_id',ident),actor::text,p->>'reason');
  RETURN jsonb_build_object('policy_id',ident);
 ELSIF p_action='save_analysis' THEN
  IF NOT EXISTS(SELECT 1 FROM public.usage_plans WHERE plan_key=p->>'plan_key' AND self_serve) THEN
   RAISE EXCEPTION 'standard plan required' USING ERRCODE='22023'; END IF;
  INSERT INTO public.billing_plan_analyses(tenant_id,plan_key,mode,policy_id,snapshot,source_hash,created_by)
   VALUES(tenant,p->>'plan_key',p->>'mode',nullif(p->>'policy_id','')::uuid,p->'snapshot',p->>'source_hash',actor::text)
   RETURNING analysis_id INTO ident;
  RETURN jsonb_build_object('analysis_id',ident);
 ELSIF p_action='history' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC),'[]') INTO result FROM (
   SELECT analysis_id,plan_key,mode,policy_id,source_hash,created_at,snapshot FROM public.billing_plan_analyses
    WHERE tenant_id=tenant AND (p->>'plan_key' IS NULL OR plan_key=p->>'plan_key') ORDER BY created_at DESC LIMIT 25) x;
  RETURN jsonb_build_object('analyses',result);
 ELSIF p_action<>'inputs' THEN RAISE EXCEPTION 'unsupported studio operation' USING ERRCODE='22023'; END IF;
 SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.version DESC),'[]') INTO pol
  FROM public.billing_plan_analysis_policies x WHERE tenant_id=tenant;
 SELECT * INTO selected FROM public.billing_plan_analysis_policies WHERE tenant_id=tenant AND effective_from<=as_of
  AND (p->>'policy_id' IS NULL OR policy_id=(p->>'policy_id')::uuid) ORDER BY effective_from DESC,version DESC LIMIT 1;
 IF p->>'policy_id' IS NOT NULL AND selected.policy_id IS NULL THEN
  RAISE EXCEPTION 'effective policy not found' USING ERRCODE='22023'; END IF;
 SELECT coalesce(jsonb_agg(x ORDER BY (x->>'tier_level')::int),'[]') INTO plans
  FROM jsonb_array_elements(public.billing_platform_owner_read('plans',100,0)->'plans') x
  WHERE (x->>'self_serve')::boolean;
 SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.feature_code),'[]') INTO features FROM public.usage_features f;
 IF selected.assumptions->>'cost_binding_policy_id' IS NOT NULL THEN
  -- Reuse approved quantity/unit mappings, not Custom quotation prices.
  -- Standard economics consumes the actual Provider Accounting authority.
  SELECT coalesce(jsonb_agg(to_jsonb(b)||jsonb_build_object('rate_id',s.schedule_id,
    'unit_cost_usd',s.unit_cost_usd,'cost_is_final',s.cost_is_final,'rate_source',s.source,
    'verified_at',s.verified_at,'updated_at',s.updated_at,'price_authority','provider_cost_schedules')),'[]') INTO bindings
   FROM public.billing_custom_pricing_rate_evidence(
    (selected.assumptions->>'cost_binding_policy_id')::uuid,
    ARRAY(SELECT feature_code FROM public.usage_features),as_of) b
   LEFT JOIN public.provider_cost_schedules s ON (s.budget_kind,s.provider,s.operation,s.unit)=(b.budget_kind,b.provider,b.operation,b.unit)
     AND s.updated_at<=as_of;
 END IF;
 -- Stored ledger plan_key preserves attribution; never join historical costs
 -- to a tenant's current plan. Pending estimates remain separately labeled.
 SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO observations FROM (
  SELECT plan_key,budget_kind,count(*) AS entries,count(DISTINCT tenant_id) AS tenants,
   sum(actual_cost_usd) FILTER(WHERE status IN('consumed','failed_charged','reconciled')) AS settled_cost_usd,
   sum(estimated_cost_usd) FILTER(WHERE status='pending_reconciliation') AS pending_estimate_usd
  FROM public.usage_ledger WHERE created_at>=window_start AND created_at<=as_of
  GROUP BY plan_key,budget_kind) x;
 RETURN jsonb_build_object('as_of',as_of,'observation_window',jsonb_build_object('from',window_start,'to',as_of),
  'plans',plans,'features',features,'entitlement_catalog',(SELECT coalesce(jsonb_agg(DISTINCT e.feature_code),'[]') FROM public.usage_plan_entitlements e
    JOIN public.usage_plans p ON p.plan_key=e.plan_key WHERE p.self_serve),
  'policies',pol,'selected_policy',CASE WHEN selected.policy_id IS NULL THEN NULL ELSE to_jsonb(selected) END,
  'bindings',bindings,'credit_policy',(SELECT jsonb_build_object('credit_usd_value',credit_usd_value::text,
    'default_safety_margin',default_safety_margin::text,'evidence',to_jsonb(cp)) FROM public.billing_cost_policy cp WHERE policy_id),
  'provider_rates',public.billing_provider_accounting('list'),'observations',observations,
  'binding_policies',(SELECT coalesce(jsonb_agg(jsonb_build_object('policy_version_id',policy_version_id,'version_number',version_number,'status',status)),'[]')
    FROM public.billing_custom_pricing_policies WHERE status IN('active','retired')));
END $$;
REVOKE ALL ON FUNCTION public.billing_plan_studio(TEXT,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_plan_studio(TEXT,JSONB) TO ceopro_app;
