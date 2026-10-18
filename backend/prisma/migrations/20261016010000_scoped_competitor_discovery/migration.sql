-- Delivery and discovery execution are separate lifecycles. No existing data is deleted.
ALTER TABLE public.market_tracking_outbox
 ADD COLUMN competitor_id UUID,
 ADD COLUMN worker_status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(worker_status IN ('QUEUED','RUNNING','COMPLETED','NO_MATCHES','PARTIAL','TIMED_OUT','FAILED','CANCELLED')),
 ADD COLUMN worker_started_at TIMESTAMPTZ,
 ADD COLUMN worker_heartbeat_at TIMESTAMPTZ,
 ADD COLUMN worker_finished_at TIMESTAMPTZ,
 ADD COLUMN worker_run_token UUID,
 ADD COLUMN worker_result JSONB,
 ADD COLUMN worker_error_code TEXT,
 ADD CONSTRAINT market_tracking_competitor_tenant_fk FOREIGN KEY(tenant_id,competitor_id)
 REFERENCES public.tenant_competitors(tenant_id,global_competitor_id),
 ADD CONSTRAINT market_tracking_competitor_discovery CHECK(competitor_id IS NULL OR kind='DISCOVERY');
CREATE INDEX market_tracking_competitor_jobs ON public.market_tracking_outbox(tenant_id,competitor_id,created_at DESC);
-- Obsolete tenant-wide requests must not resume after the new scoped worker starts.
UPDATE public.market_tracking_outbox SET status='CANCELLED',worker_status='CANCELLED',
 worker_finished_at=now(),worker_error_code='LEGACY_DISCOVERY_REPLACED'
 WHERE kind='DISCOVERY' AND status IN ('PENDING','PUBLISHED');

-- The app can report execution only; it cannot retarget jobs, create queue rows,
-- change delivery state or grant itself a subscription through these grants.
REVOKE INSERT,UPDATE,DELETE ON public.market_tracking_outbox FROM ceopro_app;
GRANT UPDATE(worker_status,worker_started_at,worker_heartbeat_at,worker_finished_at,
 worker_run_token,worker_result,worker_error_code) ON public.market_tracking_outbox TO ceopro_app;

CREATE FUNCTION public.queue_competitor_discovery(request_tenant UUID, request_competitor UUID, request_key TEXT)
RETURNS TABLE(event_id UUID,status TEXT) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE queued_id UUID; queued_status TEXT;
BEGIN
 IF public.get_current_tenant() IS DISTINCT FROM request_tenant OR NOT EXISTS(
  SELECT 1 FROM public.tenant_users tu JOIN public.system_roles r ON r.role_key=tu.role_key
  WHERE tu.tenant_id=request_tenant AND tu.user_id=NULLIF(current_setting('app.current_user_id',true),'')::uuid
   AND tu.removed_at IS NULL AND tu.platform_status='active'
   AND (r.permissions->>'all'='true' OR r.permissions->>'competitors.write'='true')
 ) THEN RAISE EXCEPTION 'MARKET_TENANT_REQUIRED' USING ERRCODE='23514'; END IF;
 -- Serialize with untrack so a concurrently inserted job cannot miss cancellation.
 PERFORM pg_advisory_xact_lock(hashtextextended('competitors-capacity:'||request_tenant::TEXT,0));
 IF NOT EXISTS(SELECT 1 FROM public.tenant_competitors tc WHERE tc.tenant_id=request_tenant
  AND tc.global_competitor_id=request_competitor AND tc.is_tracked) THEN RETURN; END IF;
 SELECT q.event_id,q.status INTO queued_id,queued_status FROM public.queue_market_tracking(
  request_tenant,'DISCOVERY',NULL,'competitor:'||request_competitor::TEXT||':'||request_key) q;
 IF queued_id IS NULL THEN RETURN; END IF;
 UPDATE public.market_tracking_outbox o SET competitor_id=request_competitor WHERE o.event_id=queued_id AND o.tenant_id=request_tenant;
 RETURN QUERY SELECT queued_id,queued_status;
END $$;
REVOKE ALL ON FUNCTION public.queue_competitor_discovery(UUID,UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.queue_competitor_discovery(UUID,UUID,TEXT) TO ceopro_app;

CREATE FUNCTION public.cancel_untracked_competitor_work()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE saved_tenant TEXT:=current_setting('app.current_tenant_id',true);
BEGIN
 IF NEW.is_tracked OR NOT OLD.is_tracked THEN RETURN NEW; END IF;
 PERFORM set_config('app.current_tenant_id',NEW.tenant_id::TEXT,true);
 UPDATE public.market_tracking_outbox o SET
  worker_status='CANCELLED',worker_finished_at=now(),worker_error_code='UNTRACKED',
  status=CASE WHEN o.status='PENDING' THEN 'CANCELLED' ELSE o.status END
 WHERE o.tenant_id=NEW.tenant_id AND o.kind='DISCOVERY' AND o.competitor_id=NEW.global_competitor_id
  AND o.worker_status IN ('QUEUED','RUNNING');
 -- Shared sources remain eligible while another tracked competitor uses them.
 UPDATE public.market_tracking_outbox o SET status='CANCELLED',last_error_code='NO_LONGER_ELIGIBLE'
 WHERE o.tenant_id=NEW.tenant_id AND o.kind='COLLECTION' AND o.status='PENDING'
  AND EXISTS(SELECT 1 FROM public.competitor_product_mappings m WHERE m.tenant_id=NEW.tenant_id
   AND m.global_competitor_id=NEW.global_competitor_id AND m.source_id=o.source_id)
  AND NOT EXISTS(SELECT 1 FROM public.competitor_product_mappings m JOIN public.tenant_competitors tc
   ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
   WHERE m.tenant_id=NEW.tenant_id AND m.source_id=o.source_id AND m.is_active AND tc.is_tracked);
 PERFORM set_config('app.current_tenant_id',COALESCE(saved_tenant,''),true);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.cancel_untracked_competitor_work() FROM PUBLIC;
CREATE TRIGGER cancel_untracked_competitor_work AFTER UPDATE OF is_tracked ON public.tenant_competitors
 FOR EACH ROW EXECUTE FUNCTION public.cancel_untracked_competitor_work();
-- Existing FORCE RLS tenant/dispatcher policies and function ownership remain in force.
