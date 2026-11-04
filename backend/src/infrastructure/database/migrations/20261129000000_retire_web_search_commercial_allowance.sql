-- Forward-only commercial deprecation. No historical rows/snapshots are rewritten.
-- Existing FORCE RLS policies and authenticated commands remain authoritative.
ALTER FUNCTION public.billing_owner_catalog_command(jsonb)
 RENAME TO billing_owner_catalog_command_before_search_retirement;
REVOKE ALL ON FUNCTION public.billing_owner_catalog_command_before_search_retirement(jsonb) FROM PUBLIC, ceopro_app;
CREATE FUNCTION public.billing_owner_catalog_command(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF p->>'action'='feature' AND p->>'feature_code'='web_searches' THEN
  RAISE EXCEPTION 'web_searches is retired from commercial authoring' USING ERRCODE='22023';
 END IF;
 RETURN public.billing_owner_catalog_command_before_search_retirement(p);
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_catalog_command(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_catalog_command(jsonb) TO ceopro_app;

ALTER FUNCTION public.billing_owner_standard_plan_create(jsonb)
 RENAME TO billing_owner_standard_plan_create_before_search_retirement;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_create_before_search_retirement(jsonb) FROM PUBLIC, ceopro_app;
CREATE FUNCTION public.billing_owner_standard_plan_create(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF nullif(p->>'template_key','') IS NOT NULL AND EXISTS(
  SELECT FROM public.billing_standard_catalog_versions v,
   LATERAL jsonb_array_elements(v.catalog->'features') f(value)
  WHERE v.catalog_version=p->>'template_catalog_version' AND f.value->>'key'='web_searches'
 ) THEN
  RAISE EXCEPTION 'use the current commercial catalog for new plans' USING ERRCODE='22023';
 END IF;
 RETURN public.billing_owner_standard_plan_create_before_search_retirement(p);
END $$;
REVOKE ALL ON FUNCTION public.billing_owner_standard_plan_create(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_owner_standard_plan_create(jsonb) TO ceopro_app;

ALTER FUNCTION public.billing_custom_quote_command(text,jsonb)
 RENAME TO billing_custom_quote_command_before_search_retirement;
REVOKE ALL ON FUNCTION public.billing_custom_quote_command_before_search_retirement(text,jsonb) FROM PUBLIC, ceopro_app;
CREATE FUNCTION public.billing_custom_quote_command(p_action text,p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE previous jsonb;
BEGIN
 IF p_action IN ('create_draft','request','create_revision') AND p->'feature_quantities' ? 'web_searches' THEN
  IF p_action<>'create_revision' THEN
   RAISE EXCEPTION 'web_searches is retired from new Custom selections' USING ERRCODE='22023';
  END IF;
  -- Owner authorization precedes private historical lookup. Lock the same
  -- quote head the delegated command uses so a concurrent revision cannot
  -- substitute a different legacy value between validation and creation.
  PERFORM public.billing_platform_standard_plans_read(1,0);
  SELECT r.feature_quantities INTO previous FROM public.billing_custom_quotes q
   JOIN public.billing_custom_quote_revisions r ON r.revision_id=q.current_revision_id
    AND r.quote_id=q.quote_id AND r.tenant_id=q.tenant_id
   WHERE q.quote_id=(p->>'quote_id')::uuid FOR UPDATE OF q;
  -- An existing operation must retain its original idempotent result even if
  -- a subsequent revision removed web_searches. The delegated command verifies
  -- the original fingerprint; a changed retry payload still raises a conflict.
  IF EXISTS(SELECT FROM public.billing_custom_quote_revisions r
    JOIN public.billing_custom_quotes q ON q.quote_id=r.quote_id AND q.tenant_id=r.tenant_id
    WHERE q.quote_id=(p->>'quote_id')::uuid AND r.request_key=p->>'idempotency_key') THEN
   RETURN public.billing_custom_quote_command_before_search_retirement(p_action,p);
  END IF;
  IF previous->'web_searches' IS NULL OR previous->'web_searches' IS DISTINCT FROM p->'feature_quantities'->'web_searches' THEN
   RAISE EXCEPTION 'legacy web_searches may only be carried forward unchanged' USING ERRCODE='22023';
  END IF;
 END IF;
 RETURN public.billing_custom_quote_command_before_search_retirement(p_action,p);
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_command(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_custom_quote_command(text,jsonb) TO ceopro_app;
