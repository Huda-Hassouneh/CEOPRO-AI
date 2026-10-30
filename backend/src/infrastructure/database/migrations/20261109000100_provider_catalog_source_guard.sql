-- Lock verified source identity for owner-confirmed catalog posting without
-- granting the restricted runtime UPDATE on private provider source tables.
CREATE FUNCTION public.keel_provider_catalog_source_guard(p_source uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid uuid:=public.get_current_tenant(); actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF NOT public.keel_active_principal(actor,tid) OR NOT EXISTS(SELECT 1 FROM public.tenant_users u
 WHERE u.tenant_id=tid AND u.user_id=actor AND u.role_key IN ('owner','admin') AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL) THEN
  RAISE EXCEPTION 'active tenant owner or admin required' USING ERRCODE='42501';
 END IF;
 PERFORM 1 FROM public.data_sources ds JOIN public.keel_provider_sources ps ON ps.tenant_id=ds.tenant_id AND ps.source_id=ds.source_id
 WHERE ds.tenant_id=tid AND ds.source_id=p_source AND ds.is_active AND ds.policy_status='ALLOWED'
 AND ps.connection_state='verified' FOR SHARE OF ds,ps;
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_catalog_source_guard(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_catalog_source_guard(uuid) TO ceopro_app;
