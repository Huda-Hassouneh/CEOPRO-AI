-- Revoking source approval cancels undelivered collection requests atomically.
-- Historical prices and unrelated sources are untouched. Runtime roles stay restricted.
CREATE FUNCTION public.cancel_unapproved_source_collection()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE saved_tenant TEXT:=current_setting('app.current_tenant_id',true);
BEGIN
 IF NEW.is_active AND NEW.policy_status='ALLOWED' AND NEW.approved_at IS NOT NULL
  AND NEW.approved_by IS NOT NULL AND NEW.approval_reference IS NOT NULL AND NEW.privacy_reviewed_at IS NOT NULL THEN RETURN NEW; END IF;
 PERFORM set_config('app.current_tenant_id',NEW.tenant_id::text,true);
 UPDATE public.market_tracking_outbox o SET status='CANCELLED',last_error_code='NO_LONGER_ELIGIBLE'
  WHERE o.tenant_id=NEW.tenant_id AND o.source_id=NEW.source_id AND o.kind='COLLECTION' AND o.status='PENDING';
 PERFORM set_config('app.current_tenant_id',coalesce(saved_tenant,''),true);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.cancel_unapproved_source_collection() FROM PUBLIC;
CREATE TRIGGER cancel_unapproved_source_collection
 AFTER UPDATE OF is_active,policy_status,approved_at,approved_by,approval_reference,privacy_reviewed_at ON public.data_sources
 FOR EACH ROW EXECUTE FUNCTION public.cancel_unapproved_source_collection();

-- A cancelled request must not suppress a newly approved source review.
CREATE OR REPLACE FUNCTION public.queue_market_tracking(request_tenant UUID, request_kind TEXT, request_source UUID, request_key TEXT)
RETURNS TABLE(event_id UUID,status TEXT) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE saved_tenant TEXT:=current_setting('app.current_tenant_id',true);
 saved_user TEXT:=current_setting('app.current_user_id',true);
 caller TEXT:=COALESCE(NULLIF(current_setting('role',true),'none'),session_user::TEXT);
BEGIN
 IF caller <> current_user::TEXT AND caller <> 'ceopro_market_dispatcher'
   AND public.get_current_tenant() IS DISTINCT FROM request_tenant THEN
  RAISE EXCEPTION 'MARKET_TENANT_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF request_kind NOT IN ('DISCOVERY','COLLECTION') OR request_key IS NULL OR length(request_key)>250 THEN
  RAISE EXCEPTION 'MARKET_INVALID_REQUEST' USING ERRCODE='23514';
 END IF;
 PERFORM set_config('app.current_tenant_id',request_tenant::TEXT,true);
 PERFORM set_config('app.current_user_id',COALESCE(NULLIF(saved_user,''),'market-tracking-trigger'),true);
 IF NOT EXISTS(SELECT 1 FROM public.subscriptions s JOIN public.plan_features pf ON pf.plan_id=s.plan_id
    JOIN public.features f ON f.feature_id=pf.feature_id JOIN public.companies c ON c.tenant_id=s.tenant_id
    WHERE s.tenant_id=request_tenant AND s.status IN ('active','trialing') AND f.feature_code='competitor_management'
      AND s.plan_id=(SELECT latest_subscription.plan_id FROM public.subscriptions AS latest_subscription WHERE latest_subscription.tenant_id=request_tenant AND latest_subscription.status IN ('active','trialing') ORDER BY latest_subscription.updated_at DESC,latest_subscription.created_at DESC LIMIT 1)
      AND c.deleted_at IS NULL AND c.platform_status='active') THEN
  PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
  PERFORM set_config('app.current_user_id',COALESCE(saved_user,''),true);RETURN;
 END IF;
 IF request_kind='DISCOVERY' AND NOT EXISTS(SELECT 1 FROM public.products WHERE tenant_id=request_tenant AND deleted_at IS NULL) THEN
  PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
  PERFORM set_config('app.current_user_id',COALESCE(saved_user,''),true);RETURN;
 END IF;
 IF request_kind='COLLECTION' AND NOT EXISTS(
  SELECT 1 FROM public.data_sources ds JOIN public.competitor_product_mappings m ON m.tenant_id=ds.tenant_id AND m.source_id=ds.source_id
   JOIN public.tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
   JOIN public.products p ON p.tenant_id=m.tenant_id AND p.product_id=m.product_id
  WHERE ds.tenant_id=request_tenant AND ds.source_id=request_source AND ds.source_type IN ('website','WEB_SCRAPE')
   AND ds.is_active AND ds.policy_status='ALLOWED' AND ds.collector_key IS NOT NULL AND ds.collector_key NOT IN ('db_connector','api_connector')
   AND ds.approval_reference IS NOT NULL AND ds.approved_by IS NOT NULL AND ds.approved_at IS NOT NULL AND ds.privacy_reviewed_at IS NOT NULL
   AND m.is_active AND tc.is_tracked AND p.deleted_at IS NULL) THEN
  PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
  PERFORM set_config('app.current_user_id',COALESCE(saved_user,''),true);RETURN;
 END IF;
 IF request_kind='COLLECTION' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('market-source:'||request_source::TEXT,0));
  RETURN QUERY SELECT o.event_id,o.status FROM public.market_tracking_outbox o JOIN public.data_sources ds ON ds.tenant_id=o.tenant_id AND ds.source_id=o.source_id
   WHERE o.tenant_id=request_tenant AND o.source_id=request_source AND o.status<>'CANCELLED' AND (o.status='PENDING' OR o.created_at>now()-make_interval(mins=>COALESCE(ds.sync_frequency_minutes,1440))) ORDER BY o.created_at DESC LIMIT 1;
  IF FOUND THEN
   PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
   PERFORM set_config('app.current_user_id',COALESCE(saved_user,''),true);RETURN;
  END IF;
 END IF;
 RETURN QUERY INSERT INTO public.market_tracking_outbox AS o(tenant_id,kind,source_id,dedupe_key)
 VALUES(request_tenant,request_kind,request_source,request_key)
 ON CONFLICT(tenant_id,dedupe_key) DO UPDATE SET dedupe_key=EXCLUDED.dedupe_key
 RETURNING o.event_id,o.status;
 PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
 PERFORM set_config('app.current_user_id',COALESCE(saved_user,''),true);
END $$;
