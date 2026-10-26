-- Serialize a reviewed source snapshot against its existing worker identity writes.
CREATE FUNCTION public.keel_provider_catalog_revision_guard(p_source uuid,p_revision uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NOT public.keel_provider_catalog_source_guard(p_source) THEN RETURN FALSE; END IF;
 PERFORM 1 FROM public.keel_provider_business_revisions b JOIN public.keel_provider_record_identities i
 ON i.tenant_id=b.tenant_id AND i.provider_record_identity_id=b.provider_record_identity_id
 WHERE b.tenant_id=public.get_current_tenant() AND b.source_id=p_source AND b.business_revision_id=p_revision
 FOR UPDATE OF i FOR SHARE OF b;
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_catalog_revision_guard(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_catalog_revision_guard(uuid,uuid) TO ceopro_app;
