-- Durable bridge to the existing Python Redis Streams workers. No observations are fabricated.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_market_dispatcher') THEN
  CREATE ROLE ceopro_market_dispatcher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE public.market_tracking_outbox (
 event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('DISCOVERY','COLLECTION')),
 source_id UUID,
 dedupe_key TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PUBLISHED','FAILED','CANCELLED')),
 attempts INT NOT NULL DEFAULT 0,
 next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 published_at TIMESTAMPTZ,
 stream_message_id TEXT,
 last_error_code TEXT,
 UNIQUE(tenant_id,dedupe_key),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.data_sources(tenant_id,source_id) ON DELETE CASCADE,
 CHECK((kind='DISCOVERY' AND source_id IS NULL) OR (kind='COLLECTION' AND source_id IS NOT NULL))
);
CREATE INDEX market_tracking_pending ON public.market_tracking_outbox(next_attempt_at,created_at) WHERE status='PENDING';
ALTER TABLE public.market_tracking_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_tracking_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY market_tracking_tenant ON public.market_tracking_outbox FOR ALL USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
DO $$ BEGIN
 EXECUTE format('CREATE POLICY market_queue_owner ON public.market_tracking_outbox TO %I USING (tenant_id = NULLIF(current_setting(''app.current_tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting(''app.current_tenant_id'',true),'''')::uuid)',current_user);
END $$;
CREATE POLICY market_tracking_dispatch ON public.market_tracking_outbox TO ceopro_market_dispatcher USING(true) WITH CHECK(true);

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
      AND s.plan_id=(SELECT plan_id FROM public.subscriptions WHERE tenant_id=request_tenant AND status IN ('active','trialing') ORDER BY updated_at DESC,created_at DESC LIMIT 1)
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
   WHERE o.tenant_id=request_tenant AND o.source_id=request_source AND (o.status='PENDING' OR o.created_at>now()-make_interval(mins=>COALESCE(ds.sync_frequency_minutes,1440))) ORDER BY o.created_at DESC LIMIT 1;
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
GRANT EXECUTE ON FUNCTION public.queue_market_tracking(UUID,TEXT,UUID,TEXT) TO PUBLIC;
-- API reads only its tenant's queue. Application roles need no queue write privilege.
GRANT SELECT ON public.market_tracking_outbox TO PUBLIC;

-- The trigger uses NEW values only. The dispatcher validates the original
-- document job and committed sales under its restricted read policies before delivery.
CREATE OR REPLACE FUNCTION public.queue_discovery_after_sales_import()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE saved_tenant TEXT:=current_setting('app.current_tenant_id',true);
BEGIN
 IF NEW.job_status <> 'COMPLETED' OR (OLD.job_status='COMPLETED' AND NEW.rows_processed IS NOT DISTINCT FROM OLD.rows_processed)
    OR COALESCE(NEW.rows_processed,0)=0 THEN RETURN NEW; END IF;
 PERFORM set_config('app.current_tenant_id',NEW.tenant_id::TEXT,true);
 INSERT INTO public.market_tracking_outbox(tenant_id,kind,dedupe_key)
 VALUES(NEW.tenant_id,'DISCOVERY','sales-import:'||NEW.job_id::TEXT||':'||NEW.rows_processed::TEXT)
 ON CONFLICT(tenant_id,dedupe_key) DO NOTHING;
 PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);RETURN NEW;
END $$;
CREATE TRIGGER sales_import_market_discovery AFTER UPDATE OF job_status,rows_processed ON public.ingestion_jobs
FOR EACH ROW EXECUTE FUNCTION public.queue_discovery_after_sales_import();
REVOKE ALL ON FUNCTION public.queue_discovery_after_sales_import() FROM PUBLIC;

-- Dispatcher may read only scheduling inputs and update source cadence, never credentials or prices.
GRANT USAGE ON SCHEMA public TO ceopro_market_dispatcher;
GRANT SELECT,INSERT,UPDATE ON public.market_tracking_outbox TO ceopro_market_dispatcher;
GRANT SELECT(tenant_id,deleted_at,platform_status) ON public.companies TO ceopro_market_dispatcher;
GRANT SELECT(tenant_id,plan_id,status,updated_at,created_at) ON public.subscriptions TO ceopro_market_dispatcher;
GRANT SELECT ON public.features,public.plan_features TO ceopro_market_dispatcher;
GRANT SELECT(source_id,tenant_id,source_type,is_active,policy_status,collector_key,approval_reference,approved_by,approved_at,privacy_reviewed_at,last_synced_at,sync_frequency_minutes) ON public.data_sources TO ceopro_market_dispatcher;
GRANT UPDATE(sync_frequency_minutes) ON public.data_sources TO ceopro_market_dispatcher;
GRANT SELECT(tenant_id,source_id,is_active,product_id,global_competitor_id) ON public.competitor_product_mappings TO ceopro_market_dispatcher;
GRANT SELECT(tenant_id,global_competitor_id,is_tracked) ON public.tenant_competitors TO ceopro_market_dispatcher;
GRANT SELECT(tenant_id,product_id,deleted_at) ON public.products TO ceopro_market_dispatcher;
GRANT SELECT(job_id,tenant_id,source_id,job_status,created_at,heartbeat_at) ON public.ingestion_jobs TO ceopro_market_dispatcher;
CREATE POLICY market_dispatch_companies ON public.companies FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_subscriptions ON public.subscriptions FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_sources ON public.data_sources FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_source_cadence ON public.data_sources FOR UPDATE TO ceopro_market_dispatcher USING(is_active AND policy_status='ALLOWED' AND source_type IN ('website','WEB_SCRAPE')) WITH CHECK(is_active AND policy_status='ALLOWED' AND source_type IN ('website','WEB_SCRAPE'));
CREATE POLICY market_dispatch_mappings ON public.competitor_product_mappings FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_competitors ON public.tenant_competitors FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_products ON public.products FOR SELECT TO ceopro_market_dispatcher USING(true);
CREATE POLICY market_dispatch_jobs ON public.ingestion_jobs FOR SELECT TO ceopro_market_dispatcher USING(true);

GRANT SELECT(tenant_id,job_id,committed_table,validation_status) ON public.import_staging_rows TO ceopro_market_dispatcher;
CREATE POLICY market_dispatch_sales_markers ON public.import_staging_rows FOR SELECT TO ceopro_market_dispatcher USING(true);
