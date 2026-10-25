-- Public validation reveals eligibility only, never cross-tenant redemption data.
-- Atomic reservation remains the authoritative concurrency/cap enforcement.
CREATE FUNCTION public.billing_promotion_capacity_reason(p_promotion UUID)
RETURNS TEXT LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_terms JSONB; v_count BIGINT;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant) THEN
   RAISE EXCEPTION 'active customer context required' USING ERRCODE='42501';
 END IF;
 SELECT terms INTO v_terms FROM public.billing_promotions WHERE promotion_id=p_promotion AND status='active';
 IF NOT FOUND THEN RETURN 'not_available'; END IF;
 IF v_terms->>'max_uses' IS NOT NULL THEN
   SELECT count(*) INTO v_count FROM public.billing_promotion_redemptions
     WHERE promotion_id=p_promotion AND state IN ('pending','settled','reconciliation_required');
   IF v_count >= (v_terms->>'max_uses')::bigint THEN RETURN 'promotion_exhausted'; END IF;
 END IF;
 IF v_terms->>'max_uses_per_tenant' IS NOT NULL THEN
   SELECT count(*) INTO v_count FROM public.billing_promotion_redemptions
     WHERE promotion_id=p_promotion AND tenant_id=v_tenant
       AND state IN ('pending','settled','reconciliation_required');
   IF v_count >= (v_terms->>'max_uses_per_tenant')::bigint THEN RETURN 'promotion_tenant_limit'; END IF;
 END IF;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.billing_promotion_capacity_reason(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_promotion_capacity_reason(UUID) TO ceopro_app;
