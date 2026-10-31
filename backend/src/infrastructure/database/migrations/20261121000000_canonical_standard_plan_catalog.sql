-- Installed by setup from the validated JSON, never from an HTTP payload.
-- Applied migrations remain historical evidence; future seed definitions live
-- only in backend/config/billing/standard_plan_catalog.json.
CREATE TABLE public.billing_standard_catalog_versions (
 catalog_version varchar(30) PRIMARY KEY,
 digest text NOT NULL UNIQUE,
 catalog jsonb NOT NULL CHECK (catalog->>'schema_version'='1'),
 installed_at timestamptz NOT NULL DEFAULT now(),
 installed_by text NOT NULL DEFAULT session_user
);
ALTER TABLE public.billing_standard_catalog_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_standard_catalog_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY standard_catalog_read ON public.billing_standard_catalog_versions FOR SELECT USING (true);
GRANT SELECT ON public.billing_standard_catalog_versions TO ceopro_app;

CREATE FUNCTION public.billing_standard_catalog_install(c jsonb, d text, fresh boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 p jsonb; f jsonb; a jsonb; period jsonb; old_digest text; key text;
 created_keys jsonb:='[]'; months integer; monthly numeric; version text:=c->>'catalog_version';
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 SELECT digest INTO old_digest FROM public.billing_standard_catalog_versions WHERE catalog_version=version;
 IF old_digest IS NOT NULL AND old_digest<>d THEN
  RAISE EXCEPTION 'catalog version is immutable; increment catalog_version' USING ERRCODE='22023';
 END IF;
 IF fresh AND (EXISTS(SELECT FROM public.tenant_plan_assignments)
   OR EXISTS(SELECT FROM public.billing_subscriptions) OR EXISTS(SELECT FROM public.billing_trials)
   OR EXISTS(SELECT FROM public.keel_platform_audit WHERE action LIKE 'plan_%' OR action LIKE 'standard_plan_%')
   OR EXISTS(SELECT FROM public.billing_plan_prices WHERE stripe_price_id IS NOT NULL)) THEN
  RAISE EXCEPTION 'fresh bootstrap cannot rewrite an initialized commercial catalog' USING ERRCODE='22023';
 END IF;
 INSERT INTO public.billing_standard_catalog_versions(catalog_version,digest,catalog)
 VALUES(version,d,c) ON CONFLICT(catalog_version) DO NOTHING;
 IF old_digest IS NULL THEN
  INSERT INTO public.keel_platform_audit(actor_role,action,subject,new_value,reason,outcome)
   VALUES('installer','standard_catalog_install','standard_catalog:'||version,
    jsonb_build_object('digest',d,'installed_by',session_user,'provenance','catalog/bootstrap'),
    'Validated canonical bootstrap/template version; no existing plan synchronization','succeeded');
 END IF;
 -- Metadata is initialization only. Existing NULLs may themselves be owner edits.
 IF fresh THEN
  FOR f IN SELECT value FROM jsonb_array_elements(c->'features') LOOP
   UPDATE public.usage_features SET display_name=f->>'label_en',display_name_ar=f->>'label_ar',
    description=f->>'description_en',description_ar=f->>'description_ar'
   WHERE feature_code=f->>'usage_feature';
  END LOOP;
 END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(c->'plans') LOOP
  key:=p->>'plan_key';
  IF NOT fresh AND (EXISTS(SELECT FROM public.usage_plans WHERE plan_key=key)
    OR EXISTS(SELECT FROM public.keel_platform_audit WHERE subject='plan:'||key)) THEN CONTINUE; END IF;
  monthly:=(p->'bootstrap_commercial_defaults'->>'monthly_price')::numeric;
  INSERT INTO public.usage_plans(plan_key,display_name,display_name_ar,monthly_price,currency,
    trial_days,tier_level,self_serve,is_active,catalog_version)
  VALUES(key,p->>'display_name',p->>'display_name_ar',monthly,'USD',
    (p->>'trial_days')::int,(p->>'tier_level')::int,true,(p->>'bootstrap_active')::boolean
      AND NOT EXISTS(SELECT FROM jsonb_array_elements(p->'allowances') a(value) WHERE a.value->>'state'='owner_required'),version)
  ON CONFLICT(plan_key) DO UPDATE SET display_name=excluded.display_name,display_name_ar=excluded.display_name_ar,
   monthly_price=excluded.monthly_price,currency=excluded.currency,trial_days=excluded.trial_days,
   tier_level=excluded.tier_level,is_active=excluded.is_active,catalog_version=excluded.catalog_version;
  IF fresh THEN
   DELETE FROM public.usage_plan_limits WHERE plan_key=key;
   DELETE FROM public.usage_plan_entitlements WHERE plan_key=key;
  END IF;
  FOR f IN SELECT value FROM jsonb_array_elements(c->'features') LOOP
   IF f->>'entitlement_type'='boolean' THEN
    INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(key,f->>'key');
   END IF;
  END LOOP;
  FOR a IN SELECT value FROM jsonb_array_elements(p->'allowances') LOOP
   IF a->>'state'<>'owner_required' THEN
    INSERT INTO public.usage_plan_limits(plan_key,feature_code,limit_value,trial_limit_value)
     VALUES(key,a->>'feature_key',(a->>'value')::bigint,(a->>'trial_value')::bigint);
   END IF;
  END LOOP;
  INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
   VALUES(key,'monthly',1,0,monthly,'USD')
   ON CONFLICT(plan_key,period_code) WHERE retired_at IS NULL DO UPDATE SET amount=excluded.amount;
  FOR period IN SELECT value FROM jsonb_array_elements(p->'bootstrap_commercial_defaults'->'billing_periods') LOOP
   months:=CASE period->>'period_code' WHEN 'three-months' THEN 3 WHEN 'six-months' THEN 6 WHEN 'yearly' THEN 12 END;
   INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
    VALUES(key,period->>'period_code',months,(period->>'discount_percent')::numeric,
     round(monthly*months*(1-(period->>'discount_percent')::numeric/100),2),'USD')
    ON CONFLICT(plan_key,period_code) WHERE retired_at IS NULL DO UPDATE SET amount=excluded.amount,discount_percent=excluded.discount_percent;
  END LOOP;
  INSERT INTO public.keel_platform_audit(actor_role,action,subject,new_value,reason,outcome)
   VALUES('installer','standard_plan_bootstrap','plan:'||key,p||jsonb_build_object('catalog_version',version,'digest',d,'installed_by',session_user),
     'Canonical initial catalog only; existing owner plans are not reconciled','succeeded');
  created_keys:=created_keys||jsonb_build_array(key);
 END LOOP;
 RETURN jsonb_build_object('catalog_version',version,'initialized_plans',created_keys);
END $$;
REVOKE ALL ON FUNCTION public.billing_standard_catalog_install(jsonb,text,boolean) FROM PUBLIC;

-- Reuse the existing owner creation authority, transaction, explicit price,
-- immutable identity and inactive-first lifecycle. No new Stripe path.
ALTER FUNCTION public.billing_owner_standard_plan_create(jsonb) RENAME TO billing_owner_standard_plan_create_terms;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_create_terms(jsonb) FROM ceopro_app;
CREATE FUNCTION public.billing_owner_standard_plan_create(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 result jsonb; c jsonb; template jsonb; f jsonb; a jsonb; digest text;
 key text:=p->>'plan_key'; template_key text:=nullif(p->>'template_key','');
BEGIN
 result:=public.billing_owner_standard_plan_create_terms(p);
 IF template_key IS NULL THEN RETURN result; END IF;
 SELECT v.catalog,v.digest INTO c,digest FROM public.billing_standard_catalog_versions v
  WHERE v.catalog_version=p->>'template_catalog_version';
 SELECT value INTO template FROM jsonb_array_elements(c->'plans') WHERE value->>'plan_key'=template_key;
 IF template IS NULL THEN RAISE EXCEPTION 'installed catalog template/version required' USING ERRCODE='22023'; END IF;
 FOR f IN SELECT value FROM jsonb_array_elements(c->'features') LOOP
  IF f->>'entitlement_type'='boolean' THEN
   INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(key,f->>'key');
  END IF;
 END LOOP;
 FOR a IN SELECT value FROM jsonb_array_elements(template->'allowances') LOOP
  IF a->>'state'<>'owner_required' THEN
   INSERT INTO public.usage_plan_limits(plan_key,feature_code,limit_value,trial_limit_value)
    VALUES(key,a->>'feature_key',(a->>'value')::bigint,(a->>'trial_value')::bigint);
  END IF;
 END LOOP;
 UPDATE public.usage_plans SET catalog_version=c->>'catalog_version' WHERE plan_key=key;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,new_value,reason,outcome)
  VALUES(nullif(current_setting('app.current_user_id',true),'')::uuid,'owner','standard_plan_template_apply','plan:'||key,
   jsonb_build_object('template',template,'catalog_version',c->>'catalog_version','digest',digest),p->>'reason','succeeded');
 RETURN jsonb_set(result,'{plan,catalog_version}',to_jsonb(c->>'catalog_version'))
  ||jsonb_build_object('template_key',template_key,'template_catalog_version',c->>'catalog_version');
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_create(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_standard_plan_create(jsonb) TO ceopro_app;

-- The three baseline entitlements already exist in assignment snapshots. Let
-- owners configure those same Boolean entries without inventing usage IDs.
ALTER FUNCTION public.billing_owner_catalog_command(jsonb) RENAME TO billing_owner_catalog_command_usage;
REVOKE ALL ON FUNCTION public.billing_owner_catalog_command_usage(jsonb) FROM ceopro_app;
CREATE FUNCTION public.billing_owner_catalog_command(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE feature text:=p->>'feature_code'; key text:=p->>'plan_key'; old_value jsonb; included boolean;
BEGIN
 IF p->>'action'='status' AND p->>'active'='true' THEN
  PERFORM public.billing_platform_standard_plans_read(1,0);
  IF EXISTS(SELECT FROM public.keel_platform_audit audit
    CROSS JOIN LATERAL jsonb_array_elements(audit.new_value->'template'->'allowances') a(value)
    WHERE audit.action='standard_plan_template_apply' AND audit.subject='plan:'||key
    AND a.value->>'state'='owner_required'
    AND NOT EXISTS(SELECT FROM public.usage_plan_limits l WHERE l.plan_key=key AND l.feature_code=a.value->>'feature_key')) THEN
   RAISE EXCEPTION 'template allowances require owner configuration before activation' USING ERRCODE='22023';
  END IF;
 END IF;
 IF p->>'action'<>'feature' OR feature NOT IN ('dashboard_analytics','product_management','data_integration') THEN
  RETURN public.billing_owner_catalog_command_usage(p);
 END IF;
 -- This read verifies the same active Platform Owner/principal/workspace.
 PERFORM public.billing_platform_standard_plans_read(1,0);
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF jsonb_typeof(p->'included') IS DISTINCT FROM 'boolean' OR nullif(btrim(p->>'reason'),'') IS NULL
  OR p->>'limit_value' IS NOT NULL THEN RAISE EXCEPTION 'Boolean entitlement and reason required' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM public.usage_plans WHERE plan_key=key FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'plan not found' USING ERRCODE='P0002'; END IF;
 included:=(p->>'included')::boolean;
 old_value:=jsonb_build_object('included',EXISTS(SELECT FROM public.usage_plan_entitlements WHERE plan_key=key AND feature_code=feature));
 IF included THEN INSERT INTO public.usage_plan_entitlements(plan_key,feature_code) VALUES(key,feature) ON CONFLICT DO NOTHING;
 ELSE DELETE FROM public.usage_plan_entitlements WHERE plan_key=key AND feature_code=feature; END IF;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
  VALUES(nullif(current_setting('app.current_user_id',true),'')::uuid,'owner','plan_feature_update','plan:'||key||':'||feature,
   old_value,jsonb_build_object('included',included),p->>'reason','succeeded');
 RETURN jsonb_build_object('plan_key',key,'feature_code',feature,'included',included,'limit_value',NULL,
   'catalog_versioned',true,'existing_assignments_preserved',true);
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_catalog_command(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_catalog_command(jsonb) TO ceopro_app;

-- Draft authoring is limited to template-created plans before first activation.
-- Commercially used/mapped identities stay under the existing publication guard.
CREATE FUNCTION public.billing_standard_plan_draft_editable(k text) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT EXISTS(SELECT FROM public.usage_plans WHERE plan_key=k AND self_serve AND NOT is_active)
  AND EXISTS(SELECT FROM public.keel_platform_audit WHERE subject='plan:'||k AND action='standard_plan_template_apply')
  AND NOT EXISTS(SELECT FROM public.keel_platform_audit WHERE subject='plan:'||k AND action='plan_status_update' AND new_value->>'is_active'='true')
  AND NOT EXISTS(SELECT FROM public.billing_plan_prices WHERE plan_key=k AND stripe_price_id IS NOT NULL)
  AND NOT EXISTS(SELECT FROM public.billing_subscriptions WHERE plan_key=k OR scheduled_plan_key=k)
  AND NOT EXISTS(SELECT FROM public.tenant_plan_assignments WHERE plan_key=k)
  AND NOT EXISTS(SELECT FROM public.billing_trials WHERE plan_key=k)
  AND NOT EXISTS(SELECT FROM public.billing_promotion_redemptions WHERE plan_key=k)
$$;
REVOKE ALL ON FUNCTION public.billing_standard_plan_draft_editable(text) FROM PUBLIC;

ALTER FUNCTION public.billing_platform_standard_plans_read(integer,integer) RENAME TO billing_platform_standard_plans_read_base;
REVOKE ALL ON FUNCTION public.billing_platform_standard_plans_read_base(integer,integer) FROM ceopro_app;
CREATE FUNCTION public.billing_platform_standard_plans_read(p_limit integer DEFAULT 100,p_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE result jsonb; plans jsonb;
BEGIN
 result:=public.billing_platform_standard_plans_read_base(p_limit,p_offset);
 SELECT coalesce(jsonb_agg(x.value||jsonb_build_object(
  'editable_draft_terms',public.billing_standard_plan_draft_editable(x.value->>'plan_key'),
  'template_missing_allowances',m.missing)||CASE WHEN jsonb_array_length(m.missing)>0
    THEN jsonb_build_object('configuration_status','MISSING_FEATURES') ELSE '{}'::jsonb END ORDER BY x.ordinal),'[]') INTO plans
 FROM jsonb_array_elements(result->'plans') WITH ORDINALITY x(value,ordinal)
 CROSS JOIN LATERAL (
  SELECT coalesce(jsonb_agg(a.value->>'feature_key'),'[]') AS missing
  FROM public.keel_platform_audit audit
  CROSS JOIN LATERAL jsonb_array_elements(audit.new_value->'template'->'allowances') a(value)
  WHERE audit.action='standard_plan_template_apply' AND audit.subject='plan:'||(x.value->>'plan_key')
   AND a.value->>'state'='owner_required'
   AND NOT EXISTS(SELECT FROM public.usage_plan_limits l WHERE l.plan_key=x.value->>'plan_key' AND l.feature_code=a.value->>'feature_key')
 ) m;
 RETURN result||jsonb_build_object('plans',plans);
END $$;
REVOKE ALL ON FUNCTION public.billing_platform_standard_plans_read(integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_platform_standard_plans_read(integer,integer) TO ceopro_app;

CREATE FUNCTION public.billing_owner_standard_plan_update_draft(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 k text:=p->>'plan_key'; en text:=nullif(btrim(p->>'display_name'),''); ar text:=nullif(btrim(p->>'display_name_ar'),'');
 monthly numeric(10,2):=nullif(p->>'monthly_price','')::numeric;
 period jsonb; months integer; discount numeric(5,2); old_value jsonb; new_value jsonb;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 PERFORM public.billing_platform_standard_plans_read(1,0);
 IF NOT public.billing_standard_plan_draft_editable(k) THEN
  RAISE EXCEPTION 'only inactive unused template drafts before first activation can change terms' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM public.usage_plans WHERE plan_key=k FOR UPDATE;
 IF en IS NULL OR ar IS NULL OR length(en)>100 OR length(ar)>100
  OR upper(coalesce(p->>'currency',''))<>'USD' OR monthly IS NULL OR monthly<0
  OR coalesce((p->>'tier_level')::integer,0)<1 OR (p->>'trial_days') IS NULL
  OR (p->>'trial_days')::integer NOT BETWEEN 0 AND 365
  OR length(coalesce(p->>'description',''))>2000 OR length(coalesce(p->>'description_ar',''))>2000
  OR nullif(btrim(p->>'reason'),'') IS NULL THEN
  RAISE EXCEPTION 'invalid explicit draft terms or audit reason' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT FROM public.usage_plans WHERE plan_key<>k AND (lower(display_name)=lower(en) OR lower(display_name_ar)=lower(ar))) THEN
  RAISE EXCEPTION 'plan name already exists' USING ERRCODE='23505'; END IF;
 IF jsonb_typeof(p->'billing_periods') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'billing_periods')>3
  OR EXISTS(SELECT FROM jsonb_array_elements(p->'billing_periods') x(value) GROUP BY value->>'period_code' HAVING count(*)>1) THEN
  RAISE EXCEPTION 'invalid optional billing periods' USING ERRCODE='22023'; END IF;
 SELECT jsonb_build_object('plan',to_jsonb(u),'prices',(SELECT jsonb_agg(to_jsonb(b)) FROM public.billing_plan_prices b WHERE b.plan_key=k))
  INTO old_value FROM public.usage_plans u WHERE u.plan_key=k;
 UPDATE public.usage_plans SET display_name=en,display_name_ar=ar,description=coalesce(p->>'description',''),
  description_ar=coalesce(p->>'description_ar',''),monthly_price=monthly,trial_days=(p->>'trial_days')::int,
  tier_level=(p->>'tier_level')::int,catalog_version='owner-v'||(SELECT version FROM public.entitlement_catalog_version WHERE singleton)
 WHERE plan_key=k;
 -- Retain every earlier commercial row. No Stripe objects, assignments or
 -- entitlements are changed by this explicit unpublished-draft edit.
 UPDATE public.billing_plan_prices SET retired_at=now() WHERE plan_key=k AND retired_at IS NULL;
 INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
  VALUES(k,'monthly',1,0,monthly,'USD');
 FOR period IN SELECT value FROM jsonb_array_elements(p->'billing_periods') LOOP
  months:=CASE period->>'period_code' WHEN 'three-months' THEN 3 WHEN 'six-months' THEN 6 WHEN 'yearly' THEN 12 END;
  discount:=nullif(period->>'discount_percent','')::numeric;
  IF months IS NULL OR discount IS NULL OR discount<0 OR discount>=100 THEN
   RAISE EXCEPTION 'invalid explicit billing period discount' USING ERRCODE='22023'; END IF;
  INSERT INTO public.billing_plan_prices(plan_key,period_code,interval_months,discount_percent,amount,currency)
   VALUES(k,period->>'period_code',months,discount,round(monthly*months*(1-discount/100),2),'USD');
 END LOOP;
 SELECT jsonb_build_object('plan',to_jsonb(u),'prices',(SELECT jsonb_agg(to_jsonb(b)) FROM public.billing_plan_prices b WHERE b.plan_key=k AND retired_at IS NULL))
  INTO new_value FROM public.usage_plans u WHERE u.plan_key=k;
 INSERT INTO public.keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
  VALUES(nullif(current_setting('app.current_user_id',true),'')::uuid,'owner','standard_plan_draft_update','plan:'||k,
   old_value,new_value,p->>'reason','succeeded');
 RETURN new_value;
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_update_draft(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_standard_plan_update_draft(jsonb) TO ceopro_app;
