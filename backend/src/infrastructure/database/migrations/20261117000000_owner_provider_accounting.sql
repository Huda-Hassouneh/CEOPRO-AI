-- Shared persistence for billing.admin.set_price (operator and owner HTTP).
-- No table privileges or elevated connection credentials are granted to runtime roles.
CREATE FUNCTION public.billing_provider_accounting(p_action TEXT, p JSONB DEFAULT '{}'::jsonb)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor UUID := nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant UUID := nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 trusted BOOLEAN;
 old_row public.provider_cost_schedules%ROWTYPE;
 new_row public.provider_cost_schedules%ROWTYPE;
 result JSONB;
BEGIN
 -- Preserve trusted installation/operator calls. SET ROLE ceopro_app in tests
 -- must exercise the same owner boundary as a real restricted password login.
 trusted := current_setting('role') = 'none' AND pg_has_role(session_user,
   (SELECT relowner FROM pg_class WHERE oid='public.provider_cost_schedules'::regclass),'USAGE');
 IF NOT trusted THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
   IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
      OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m
          JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
          WHERE m.user_id=actor AND m.role_key='owner' AND m.status='active')
      OR EXISTS(SELECT 1 FROM public.users WHERE user_id=actor AND platform_disabled_at IS NOT NULL) THEN
     RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
   END IF;
   IF p_action='set_price' AND p->>'approved_by' IS DISTINCT FROM actor::text THEN
     RAISE EXCEPTION 'approver must be authenticated owner' USING ERRCODE='42501';
   END IF;
 END IF;
 IF p_action='list' THEN
   SELECT coalesce(jsonb_agg(to_jsonb(s) || jsonb_build_object('reason',a.reason,
      'unit_cost_usd',s.unit_cost_usd::text,'safety_margin',s.safety_margin::text)
      ORDER BY s.budget_kind,s.provider,s.operation,s.unit),'[]'::jsonb) INTO result
   FROM public.provider_cost_schedules s
   LEFT JOIN LATERAL (SELECT reason FROM public.entitlement_audit_log
     WHERE action='set_price' AND subject=concat_ws(':',s.budget_kind,s.provider,s.operation,s.unit)
     ORDER BY created_at DESC LIMIT 1) a ON true;
   RETURN result;
 ELSIF p_action <> 'set_price' THEN
   RAISE EXCEPTION 'unsupported provider accounting action' USING ERRCODE='22023';
 END IF;
 -- Constraints match the existing schedule schema; provenance is mandatory.
 IF p->>'budget_kind' NOT IN ('data','ai') OR nullif(btrim(p->>'provider'),'') IS NULL
    OR nullif(btrim(p->>'operation'),'') IS NULL
    OR nullif(btrim(p->>'source'),'') IS NULL OR nullif(btrim(p->>'reason'),'') IS NULL
    OR nullif(btrim(p->>'approved_by'),'') IS NULL OR p->>'verified_on' IS NULL
    OR p->>'unit_cost_usd' IS NULL THEN
   RAISE EXCEPTION 'incomplete approved price' USING ERRCODE='22023';
 END IF;
 IF NOT ((p->>'unit_cost_usd')::numeric >= 0 AND (p->>'unit_cost_usd')::numeric < 100000000)
    OR (p->>'safety_margin' IS NOT NULL AND NOT ((p->>'safety_margin')::numeric BETWEEN 0 AND 2)) THEN
   RAISE EXCEPTION 'invalid finite price or margin' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('provider_price:'||concat_ws(':',
   p->>'budget_kind',p->>'provider',p->>'operation',p->>'unit'),0));
 SELECT * INTO old_row FROM public.provider_cost_schedules
 WHERE budget_kind=p->>'budget_kind' AND provider=p->>'provider'
   AND operation=p->>'operation' AND unit=p->>'unit' FOR UPDATE;
 IF coalesce((p->>'if_missing')::boolean,false) AND old_row.unit_cost_usd IS NOT NULL THEN
   RETURN jsonb_build_object('written',false);
 END IF;
 INSERT INTO public.provider_cost_schedules(budget_kind,provider,operation,unit,unit_cost_usd,
   safety_margin,charged_on_failure,cost_is_final,source,verified_at,configured_by)
 VALUES(p->>'budget_kind',p->>'provider',p->>'operation',p->>'unit',(p->>'unit_cost_usd')::numeric,
   (p->>'safety_margin')::numeric,(p->>'charged_on_failure')::boolean,(p->>'cost_is_final')::boolean,
   p->>'source',(p->>'verified_on')::date,p->>'approved_by')
 ON CONFLICT(budget_kind,provider,operation,unit) DO UPDATE SET
   unit_cost_usd=EXCLUDED.unit_cost_usd,safety_margin=EXCLUDED.safety_margin,
   charged_on_failure=EXCLUDED.charged_on_failure,cost_is_final=EXCLUDED.cost_is_final,
   source=EXCLUDED.source,verified_at=EXCLUDED.verified_at,configured_by=EXCLUDED.configured_by,updated_at=NOW()
 RETURNING * INTO new_row;
 INSERT INTO public.entitlement_audit_log(action,subject,old_value,new_value,approved_by,reason)
 VALUES('set_price',concat_ws(':',new_row.budget_kind,new_row.provider,new_row.operation,new_row.unit),
   CASE WHEN old_row.schedule_id IS NULL THEN NULL ELSE to_jsonb(old_row) END,
   to_jsonb(new_row)||jsonb_build_object('verified_on',new_row.verified_at),p->>'approved_by',p->>'reason');
 RETURN jsonb_build_object('written',true);
END $$;
REVOKE ALL ON FUNCTION public.billing_provider_accounting(TEXT,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_provider_accounting(TEXT,JSONB) TO ceopro_app;
