-- Owner-created Standard Plans remain drafts until an owner explicitly
-- activates them. Prices are created from an owner-entered monthly amount and
-- explicitly selected billing-period discounts; Stripe reconciliation stays
-- in scripts/stripe_sync_catalog.py.
ALTER TABLE public.usage_plans
    ADD COLUMN IF NOT EXISTS description text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description_ar text NOT NULL DEFAULT '';

CREATE OR REPLACE FUNCTION public.billing_owner_standard_plan_create(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_plan_key text:=lower(btrim(coalesce(p->>'plan_key','')));
 name_en text:=nullif(btrim(p->>'display_name'),'');
 name_ar text:=nullif(btrim(p->>'display_name_ar'),'');
 description_en text:=coalesce(p->>'description','');
 description_ar text:=coalesce(p->>'description_ar','');
 currency text:=upper(coalesce(p->>'currency',''));
 monthly numeric(10,2):=nullif(p->>'monthly_price','')::numeric;
 tier integer:=nullif(p->>'tier_level','')::integer;
 trial_days integer:=nullif(p->>'trial_days','')::integer;
 period jsonb; months integer; discount numeric(5,2); amount numeric(12,2);
 catalog_version text; new_plan jsonb; new_prices jsonb:='[]'::jsonb;
 reason text:=nullif(btrim(p->>'reason'),'');
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
  OR NOT EXISTS(SELECT FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
    WHERE m.user_id=actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT FROM public.users u WHERE u.user_id=actor AND u.platform_disabled_at IS NOT NULL) THEN
  RAISE EXCEPTION 'active Platform Owner required' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.keel_platform_members WHERE user_id=actor FOR UPDATE;
 IF v_plan_key !~ '^[a-z][a-z0-9_]{0,49}$' OR v_plan_key='custom' THEN
  RAISE EXCEPTION 'plan key must be a new stable lowercase identifier' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT FROM public.usage_plans u WHERE u.plan_key=v_plan_key) THEN
  RAISE EXCEPTION 'plan key already exists; historical identities cannot be reused' USING ERRCODE='23505'; END IF;
 IF name_en IS NULL OR length(name_en)>100 OR name_ar IS NULL OR length(name_ar)>100 THEN
  RAISE EXCEPTION 'unique English and Arabic plan names are required' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT FROM public.usage_plans u
   WHERE lower(u.display_name)=lower(name_en) OR lower(coalesce(u.display_name_ar,''))=lower(name_ar)) THEN
  RAISE EXCEPTION 'display name is already in use' USING ERRCODE='23505'; END IF;
 IF length(description_en)>2000 OR length(description_ar)>2000 OR currency<>'USD'
  OR tier IS NULL OR tier<1 OR trial_days IS NULL OR trial_days<0 OR trial_days>365
  OR monthly IS NULL OR monthly<0 THEN
  RAISE EXCEPTION 'invalid Standard Plan terms; current Standard checkout requires USD' USING ERRCODE='22023'; END IF;
 IF reason IS NULL THEN RAISE EXCEPTION 'audit reason required' USING ERRCODE='22023'; END IF;
 IF jsonb_typeof(p->'billing_periods') IS DISTINCT FROM 'array'
  OR jsonb_array_length(p->'billing_periods')>3
  OR (SELECT count(*) FROM jsonb_array_elements(p->'billing_periods') AS entries(value) WHERE value->>'period_code'='monthly')>0
  THEN
  RAISE EXCEPTION 'invalid optional billing periods' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p->'billing_periods') AS entries(value)
   GROUP BY value->>'period_code' HAVING count(*)>1) THEN
  RAISE EXCEPTION 'duplicate billing period' USING ERRCODE='22023'; END IF;
 SELECT 'owner-v'||version::text INTO catalog_version FROM public.entitlement_catalog_version WHERE singleton IS TRUE;
 INSERT INTO public.usage_plans(plan_key,display_name,display_name_ar,description,description_ar,
   monthly_price,currency,trial_days,tier_level,self_serve,is_active,catalog_version)
 VALUES(v_plan_key,name_en,name_ar,description_en,description_ar,monthly,currency,trial_days,tier,TRUE,FALSE,catalog_version);
 INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
 VALUES(v_plan_key,'monthly',1,0,monthly,currency)
 RETURNING to_jsonb(billing_plan_prices) INTO period;
 new_prices:=new_prices||jsonb_build_array(period);
 FOR period IN SELECT value FROM jsonb_array_elements(p->'billing_periods') AS entries(value) LOOP
  CASE period->>'period_code'
   WHEN 'three-months' THEN months:=3;
   WHEN 'six-months' THEN months:=6;
   WHEN 'yearly' THEN months:=12;
   ELSE RAISE EXCEPTION 'unsupported billing period' USING ERRCODE='22023';
  END CASE;
  discount:=coalesce(nullif(period->>'discount_percent','')::numeric,0);
  IF discount<0 OR discount>=100 THEN RAISE EXCEPTION 'discount must be between 0 and 100 percent' USING ERRCODE='22023'; END IF;
  amount:=round(monthly*months*(1-discount/100),2);
  INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
  VALUES(v_plan_key,period->>'period_code',months,discount,amount,currency)
  RETURNING to_jsonb(billing_plan_prices) INTO period;
  new_prices:=new_prices||jsonb_build_array(period);
 END LOOP;
 SELECT to_jsonb(u) INTO new_plan FROM public.usage_plans u WHERE u.plan_key=v_plan_key;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
 VALUES(actor,'owner','standard_plan_create','plan:'||v_plan_key,NULL,
   jsonb_build_object('plan',new_plan,'prices',new_prices),'Created inactive Standard Plan: '||reason,'succeeded');
 RETURN jsonb_build_object('plan',new_plan,'prices',new_prices,'is_active',false,
   'stripe_setup_required',true,'existing_assignments_preserved',true);
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_create(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_standard_plan_create(jsonb) TO ceopro_app;

-- Activation is an explicit future-offer action. Require a configured
-- monthly price and at least one canonical allowance/entitlement first.
CREATE OR REPLACE FUNCTION public.billing_owner_catalog_command(p jsonb)
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
  IF (p->>'active')::boolean AND (SELECT self_serve FROM public.usage_plans WHERE plan_key=plan) AND (
    NOT EXISTS(SELECT FROM public.billing_plan_prices WHERE plan_key=plan AND period_code='monthly' AND retired_at IS NULL)
    OR NOT EXISTS(SELECT FROM public.usage_plan_limits WHERE plan_key=plan)
       AND NOT EXISTS(SELECT FROM public.usage_plan_entitlements WHERE plan_key=plan)) THEN
    RAISE EXCEPTION 'plan needs a monthly price and at least one canonical allowance before activation' USING ERRCODE='22023';
  END IF;
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

CREATE OR REPLACE FUNCTION public.billing_platform_standard_plans_read(p_limit integer DEFAULT 100,p_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 base jsonb; plans jsonb;
BEGIN
 IF p_limit<1 OR p_limit>200 OR p_offset<0 THEN RAISE EXCEPTION 'invalid page bounds' USING ERRCODE='22023'; END IF;
 IF actor IS NULL OR tenant IS NULL OR NOT public.keel_active_principal(actor,tenant)
  OR NOT EXISTS(SELECT FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=tenant
    WHERE m.user_id=actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT FROM public.users u WHERE u.user_id=actor AND u.platform_disabled_at IS NOT NULL) THEN
  RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501'; END IF;
 base:=public.billing_platform_owner_read('plans',p_limit,p_offset);
 SELECT coalesce(jsonb_agg(x.value||jsonb_build_object(
   'description',u.description,'description_ar',u.description_ar,'catalog_version',u.catalog_version,
   'feature_configured',EXISTS(SELECT FROM public.usage_plan_limits l WHERE l.plan_key=u.plan_key)
      OR EXISTS(SELECT FROM public.usage_plan_entitlements e WHERE e.plan_key=u.plan_key),
   'pricing_configured',EXISTS(SELECT FROM public.billing_plan_prices b WHERE b.plan_key=u.plan_key
      AND b.period_code='monthly' AND b.retired_at IS NULL),
   'stripe_setup_required',EXISTS(SELECT FROM public.billing_plan_prices b WHERE b.plan_key=u.plan_key
      AND b.retired_at IS NULL AND b.stripe_price_id IS NULL),
   'configuration_status',CASE
     WHEN NOT EXISTS(SELECT FROM public.billing_plan_prices b WHERE b.plan_key=u.plan_key AND b.period_code='monthly' AND b.retired_at IS NULL) THEN 'MISSING_PRICE'
     WHEN NOT (EXISTS(SELECT FROM public.usage_plan_limits l WHERE l.plan_key=u.plan_key)
       OR EXISTS(SELECT FROM public.usage_plan_entitlements e WHERE e.plan_key=u.plan_key)) THEN 'MISSING_FEATURES'
     WHEN u.is_active AND EXISTS(SELECT FROM public.billing_plan_prices b WHERE b.plan_key=u.plan_key AND b.retired_at IS NULL AND b.stripe_price_id IS NULL) THEN 'STRIPE_SETUP_REQUIRED'
     WHEN NOT u.is_active THEN 'READY_TO_ACTIVATE'
     ELSE 'READY' END
   ) ORDER BY x.value->>'plan_key'),'[]'::jsonb) INTO plans
 FROM jsonb_array_elements(base->'plans') x(value)
 JOIN public.usage_plans u ON u.plan_key=x.value->>'plan_key';
 RETURN jsonb_build_object('plans',plans,'limit',p_limit,'offset',p_offset);
END $$;
REVOKE ALL ON FUNCTION public.billing_platform_standard_plans_read(integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_platform_standard_plans_read(integer,integer) TO ceopro_app;
