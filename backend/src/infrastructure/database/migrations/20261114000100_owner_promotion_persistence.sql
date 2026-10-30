-- Owner-only promotion repository. No table privileges granted to runtime roles.
-- Activation/disable finalization is callable only by the trusted setup identity,
-- after Python has verified the provider. This grants no payment/credit authority.
CREATE FUNCTION public.billing_owner_promotion_command(p_action text,p jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 id uuid:=nullif(p->>'promotion_id','')::uuid; r public.billing_promotions%ROWTYPE;
 old_value jsonb; result jsonb; plans jsonb; keys text[]; event_name text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
  OR NOT EXISTS(SELECT FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
    WHERE m.user_id=actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT FROM public.users u WHERE u.user_id=actor AND u.platform_disabled_at IS NOT NULL) THEN
  RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.keel_platform_members WHERE user_id=actor FOR UPDATE;
 IF p_action='list' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY x.created_at DESC,x.promotion_id),'[]'::jsonb) INTO result FROM
   (SELECT b.*,coalesce((SELECT jsonb_agg(pp.plan_key ORDER BY pp.plan_key) FROM public.billing_promotion_plans pp WHERE pp.promotion_id=b.promotion_id),'[]'::jsonb) AS plan_keys FROM public.billing_promotions b) x;
  RETURN jsonb_build_object('items',result);
 END IF;
 IF id IS NOT NULL THEN
  SELECT * INTO r FROM public.billing_promotions WHERE promotion_id=id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'promotion not found' USING ERRCODE='P0002'; END IF;
  old_value:=to_jsonb(r);
 END IF;
 IF p_action='get' THEN
  SELECT coalesce(jsonb_agg(plan_key ORDER BY plan_key),'[]'::jsonb) INTO plans FROM public.billing_promotion_plans WHERE promotion_id=id;
  RETURN to_jsonb(r)||jsonb_build_object('plan_keys',plans);
 ELSIF p_action='save_draft' THEN
  IF id IS NOT NULL AND r.status<>'draft' THEN RAISE EXCEPTION 'only drafts can be edited' USING ERRCODE='55000'; END IF;
  IF coalesce(p->>'code','') !~ '^[A-Z0-9][A-Z0-9_-]{0,99}$' OR jsonb_typeof(p->'terms')<>'object' OR nullif(btrim(p->>'reason'),'') IS NULL THEN
   RAISE EXCEPTION 'invalid promotion draft' USING ERRCODE='22023'; END IF;
  SELECT coalesce(array_agg(v ORDER BY v),ARRAY[]::text[]) INTO keys FROM jsonb_array_elements_text(coalesce(p->'plan_keys','[]'::jsonb)) AS q(v);
  IF EXISTS(SELECT FROM unnest(keys) k WHERE NOT EXISTS(SELECT FROM public.usage_plans u WHERE u.plan_key=k AND u.is_active)) THEN
   RAISE EXCEPTION 'existing active plans required' USING ERRCODE='22023'; END IF;
  IF id IS NULL THEN
   INSERT INTO public.billing_promotions(code,name,description,status,terms,stripe_coupon_id,stripe_promotion_code_id,created_by,updated_by)
   VALUES(p->>'code',p->>'name',p->>'description','draft',p->'terms',p#>>'{terms,stripe_coupon_id}',p#>>'{terms,stripe_promotion_code_id}',actor,actor)
   RETURNING * INTO r;id:=r.promotion_id;event_name:='promotion_draft_create';
  ELSE
   UPDATE public.billing_promotions SET code=p->>'code',name=p->>'name',description=p->>'description',terms=p->'terms',
    stripe_coupon_id=p#>>'{terms,stripe_coupon_id}',stripe_promotion_code_id=p#>>'{terms,stripe_promotion_code_id}',updated_by=actor,updated_at=now()
    WHERE promotion_id=id RETURNING * INTO r;event_name:='promotion_draft_update';
  END IF;
  DELETE FROM public.billing_promotion_plans WHERE promotion_id=id;
  INSERT INTO public.billing_promotion_plans(promotion_id,plan_key) SELECT id,k FROM unnest(keys) k;
 ELSIF p_action IN ('activate','disable') THEN
  IF session_user<>'ceopro_billing_setup' AND coalesce(current_setting('role',true),'')<>'ceopro_billing_setup' THEN
   RAISE EXCEPTION 'trusted provider configuration identity required' USING ERRCODE='42501'; END IF;
  IF id IS NULL OR nullif(btrim(p->>'reason'),'') IS NULL THEN RAISE EXCEPTION 'identity and audit reason required' USING ERRCODE='22023'; END IF;
  IF p_action='activate' THEN
   IF r.status NOT IN ('draft','disabled') OR p->>'expected_status' IS DISTINCT FROM r.status THEN
    RAISE EXCEPTION 'promotion state changed' USING ERRCODE='55000'; END IF;
   IF p#>>'{terms,stripe_coupon_id}' IS NULL OR coalesce(p#>>'{terms,stripe_promotion_code_id}','') !~ '^promo_[A-Za-z0-9]+$'
    OR nullif(btrim(p->>'approval_reference'),'') IS NULL OR p->'expected_terms' IS DISTINCT FROM r.terms THEN
    RAISE EXCEPTION 'verified provider mapping and unchanged terms required' USING ERRCODE='22023'; END IF;
   UPDATE public.billing_promotions SET status='active',terms=p->'terms',stripe_coupon_id=p#>>'{terms,stripe_coupon_id}',
    stripe_promotion_code_id=p#>>'{terms,stripe_promotion_code_id}',approval_reference=p->>'approval_reference',approved_by=actor,approved_at=now(),updated_by=actor,updated_at=now()
    WHERE promotion_id=id RETURNING * INTO r;event_name:='promotion_activate';
  ELSE
   UPDATE public.billing_promotions SET status='disabled',updated_by=actor,updated_at=now() WHERE promotion_id=id RETURNING * INTO r;event_name:='promotion_disable';
  END IF;
 ELSE RAISE EXCEPTION 'unsupported promotion command' USING ERRCODE='22023'; END IF;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
 VALUES(actor,'owner',event_name,id::text,old_value,to_jsonb(r),p->>'reason','succeeded');
 SELECT coalesce(jsonb_agg(plan_key ORDER BY plan_key),'[]'::jsonb) INTO plans FROM public.billing_promotion_plans WHERE promotion_id=id;
 RETURN to_jsonb(r)||jsonb_build_object('plan_keys',plans);
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_promotion_command(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_promotion_command(text,jsonb) TO ceopro_app,ceopro_billing_setup;

-- Preserve the existing plan mutation semantics and immutable-assignment triggers.
CREATE FUNCTION public.billing_owner_catalog_command(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 plan text:=p->>'plan_key'; feature text:=p->>'feature_code'; reason text:=nullif(btrim(p->>'reason'),'');
 old_value jsonb; new_value jsonb; included boolean; value bigint; found_plan text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
  OR NOT EXISTS(SELECT FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
   WHERE m.user_id=actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT FROM public.users u WHERE u.user_id=actor AND u.platform_disabled_at IS NOT NULL) THEN
  RAISE EXCEPTION 'active Platform Owner required' USING ERRCODE='42501'; END IF;
 IF reason IS NULL THEN RAISE EXCEPTION 'audit reason required' USING ERRCODE='22023'; END IF;
 SELECT plan_key INTO found_plan FROM public.usage_plans WHERE plan_key=plan FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'plan not found' USING ERRCODE='P0002'; END IF;
 IF p->>'action'='status' THEN
  IF jsonb_typeof(p->'active')<>'boolean' THEN RAISE EXCEPTION 'boolean active required' USING ERRCODE='22023'; END IF;
  SELECT jsonb_build_object('is_active',is_active) INTO old_value FROM public.usage_plans WHERE plan_key=plan;
  new_value:=jsonb_build_object('is_active',(p->>'active')::boolean);
  UPDATE public.usage_plans SET is_active=(p->>'active')::boolean WHERE plan_key=plan;
 ELSE
  IF p->>'action'<>'feature' OR jsonb_typeof(p->'included')<>'boolean'
    OR NOT EXISTS(SELECT FROM public.usage_features WHERE feature_code=feature) THEN RAISE EXCEPTION 'invalid feature mutation' USING ERRCODE='22023'; END IF;
  included:=(p->>'included')::boolean;value:=nullif(p->>'limit_value','')::bigint;
  IF value<0 THEN RAISE EXCEPTION 'nonnegative limit required' USING ERRCODE='22023'; END IF;
  IF feature IN ('market_intelligence','demand_prediction','competitor_management') THEN
   IF value IS NOT NULL THEN RAISE EXCEPTION 'module cannot have numeric limit' USING ERRCODE='22023'; END IF;
   old_value:=jsonb_build_object('included',EXISTS(SELECT FROM public.usage_plan_entitlements WHERE plan_key=plan AND feature_code=feature),'limit_value',NULL);
   IF included THEN INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(plan,feature) ON CONFLICT DO NOTHING;
   ELSE DELETE FROM public.usage_plan_entitlements WHERE plan_key=plan AND feature_code=feature; END IF;
  ELSE
   SELECT jsonb_build_object('included',true,'limit_value',limit_value) INTO old_value FROM public.usage_plan_limits WHERE plan_key=plan AND feature_code=feature;
   old_value:=coalesce(old_value,jsonb_build_object('included',false,'limit_value',NULL));
   IF included THEN INSERT INTO public.usage_plan_limits(plan_key,feature_code,limit_value) VALUES(plan,feature,value)
    ON CONFLICT(plan_key,feature_code) DO UPDATE SET limit_value=EXCLUDED.limit_value;
   ELSE DELETE FROM public.usage_plan_limits WHERE plan_key=plan AND feature_code=feature; END IF;
  END IF;
  new_value:=jsonb_build_object('included',included,'limit_value',CASE WHEN included THEN value ELSE NULL END);
 END IF;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
 VALUES(actor,'owner',CASE WHEN p->>'action'='status' THEN 'plan_status_update' ELSE 'plan_feature_update' END,
  'plan:'||plan||CASE WHEN feature IS NOT NULL THEN ':'||feature ELSE '' END,old_value,new_value,reason,'succeeded');
 RETURN jsonb_build_object('plan_key',plan,'feature_code',feature,'catalog_versioned',p->>'action'='feature','existing_assignments_preserved',true)||new_value;
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_catalog_command(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_catalog_command(jsonb) TO ceopro_app;
