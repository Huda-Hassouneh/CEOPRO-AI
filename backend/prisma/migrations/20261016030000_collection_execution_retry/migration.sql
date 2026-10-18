-- Delivery and execution have distinct lifecycles; retain every old request/job.
ALTER TABLE public.market_tracking_outbox
 ADD COLUMN worker_attempts INT NOT NULL DEFAULT 0 CHECK(worker_attempts>=0),
 ADD COLUMN retry_of_event_id UUID,
 ADD CONSTRAINT market_tracking_tenant_event_unique UNIQUE(tenant_id,event_id),
 ADD CONSTRAINT market_collection_retry_parent FOREIGN KEY(tenant_id,retry_of_event_id)
 REFERENCES public.market_tracking_outbox(tenant_id,event_id),
 ADD CONSTRAINT market_collection_retry_kind CHECK(retry_of_event_id IS NULL OR kind='COLLECTION');
CREATE UNIQUE INDEX market_collection_one_retry ON public.market_tracking_outbox(tenant_id,retry_of_event_id) WHERE retry_of_event_id IS NOT NULL;
ALTER TABLE public.ingestion_jobs ADD COLUMN market_event_id UUID,
 ADD CONSTRAINT ingestion_market_event_fk FOREIGN KEY(tenant_id,market_event_id)
 REFERENCES public.market_tracking_outbox(tenant_id,event_id);
CREATE INDEX ingestion_market_event ON public.ingestion_jobs(tenant_id,market_event_id,created_at DESC);
GRANT UPDATE(worker_attempts) ON public.market_tracking_outbox TO ceopro_app;

CREATE FUNCTION public.retry_market_collection(request_tenant UUID,request_competitor UUID,request_source UUID,failed_event UUID)
RETURNS TABLE(event_id UUID,created BOOLEAN,reason TEXT) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE cadence INT; new_id UUID; parent public.market_tracking_outbox%ROWTYPE;
BEGIN
 IF public.get_current_tenant() IS DISTINCT FROM request_tenant OR NOT EXISTS(
  SELECT 1 FROM public.tenant_users tu JOIN public.system_roles r ON r.role_key=tu.role_key
  WHERE tu.tenant_id=request_tenant AND tu.user_id=NULLIF(current_setting('app.current_user_id',true),'')::uuid
   AND tu.removed_at IS NULL AND tu.platform_status='active' AND (r.permissions->>'all'='true' OR r.permissions->>'competitors.write'='true')
 ) THEN RAISE EXCEPTION 'COLLECTION_RETRY_FORBIDDEN' USING ERRCODE='23514'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('competitors-capacity:'||request_tenant::TEXT,0));
 PERFORM 1 FROM public.data_sources ds WHERE ds.tenant_id=request_tenant AND ds.source_id=request_source FOR UPDATE;
 PERFORM pg_advisory_xact_lock(hashtextextended('market-source:'||request_source::TEXT,0));
 IF NOT EXISTS(SELECT 1 FROM public.data_sources ds JOIN public.competitor_product_mappings m ON m.tenant_id=ds.tenant_id AND m.source_id=ds.source_id
  JOIN public.tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
  JOIN public.products p ON p.tenant_id=m.tenant_id AND p.product_id=m.product_id
  WHERE ds.tenant_id=request_tenant AND ds.source_id=request_source AND tc.global_competitor_id=request_competitor AND tc.is_tracked AND m.is_active AND p.deleted_at IS NULL
   AND ds.is_active AND ds.policy_status='ALLOWED' AND ds.source_type IN ('website','WEB_SCRAPE') AND ds.collector_key IS NOT NULL AND ds.collector_key NOT IN ('db_connector','api_connector')
   AND ds.approved_by IS NOT NULL AND ds.approved_at IS NOT NULL AND ds.approval_reference IS NOT NULL AND ds.privacy_reviewed_at IS NOT NULL)
 THEN RETURN QUERY SELECT NULL::uuid,false,'SOURCE_NOT_ELIGIBLE'::text; RETURN; END IF;
 SELECT CASE WHEN jsonb_typeof(pf.metadata->'configuration'->'monitoringFrequencyMinutes')='number' AND pf.metadata->'configuration'->>'monitoringFrequencyMinutes' ~ '^[0-9]{1,6}$'
  THEN (pf.metadata->'configuration'->>'monitoringFrequencyMinutes')::int ELSE NULL END INTO cadence
 FROM public.subscriptions s JOIN public.companies c ON c.tenant_id=s.tenant_id
 JOIN public.plan_features pf ON pf.plan_id=s.plan_id JOIN public.features f ON f.feature_id=pf.feature_id AND f.feature_code='competitor_management'
 WHERE s.tenant_id=request_tenant AND s.status IN ('active','trialing') AND c.deleted_at IS NULL AND c.platform_status='active'
  AND s.id=(SELECT latest.id FROM public.subscriptions latest WHERE latest.tenant_id=request_tenant AND latest.status IN ('active','trialing') ORDER BY latest.updated_at DESC,latest.created_at DESC LIMIT 1);
 IF cadence IS NULL OR cadence NOT BETWEEN 1 AND 525600 THEN RETURN QUERY SELECT NULL::uuid,false,'PLAN_NOT_ELIGIBLE'::text; RETURN; END IF;
 SELECT o.* INTO parent FROM public.market_tracking_outbox o WHERE o.tenant_id=request_tenant AND o.event_id=failed_event AND o.source_id=request_source AND o.kind='COLLECTION';
 -- Reconcile an old unreported failed source attempt only inside this tenant,
 -- when it is the latest request and no collector is active. No global backfill.
 IF parent.worker_status='QUEUED' AND parent.status='PUBLISHED' AND parent.worker_attempts=0 AND parent.worker_started_at IS NULL AND parent.worker_error_code IS NULL AND EXISTS(
  SELECT 1 FROM (SELECT i.job_status,i.created_at FROM public.ingestion_jobs i WHERE i.tenant_id=request_tenant AND i.source_id=request_source ORDER BY i.created_at DESC,i.job_id DESC LIMIT 1) j
  WHERE j.job_status='FAILED' AND j.created_at>=parent.published_at)
  AND NOT EXISTS(SELECT 1 FROM public.ingestion_jobs i WHERE i.tenant_id=request_tenant AND i.source_id=request_source AND i.job_status IN ('QUEUED','PROCESSING'))
  AND NOT EXISTS(SELECT 1 FROM public.market_tracking_outbox n WHERE n.tenant_id=request_tenant AND n.source_id=request_source AND n.kind='COLLECTION' AND (n.created_at,n.event_id)>(parent.created_at,parent.event_id))
 THEN UPDATE public.market_tracking_outbox o SET worker_status='FAILED',worker_finished_at=now(),worker_error_code='PREVIOUS_COLLECTION_FAILED',worker_result=jsonb_build_object('legacy_inferred',true)
  WHERE o.event_id=parent.event_id AND o.tenant_id=request_tenant RETURNING o.* INTO parent; END IF;
 IF parent.event_id IS NULL OR parent.worker_status<>'FAILED' OR parent.status='CANCELLED' THEN RETURN QUERY SELECT NULL::uuid,false,'COLLECTION_NOT_FAILED'::text; RETURN; END IF;
 SELECT o.event_id INTO new_id FROM public.market_tracking_outbox o WHERE o.tenant_id=request_tenant AND o.retry_of_event_id=failed_event;
 IF new_id IS NOT NULL THEN RETURN QUERY SELECT new_id,false,'EXISTING_RETRY'::text; RETURN; END IF;
 IF EXISTS(SELECT 1 FROM public.market_tracking_outbox o WHERE o.tenant_id=request_tenant AND o.source_id=request_source AND o.kind='COLLECTION' AND o.event_id<>failed_event
  AND o.status IN ('PENDING','PUBLISHED') AND o.worker_status IN ('QUEUED','RUNNING'))
  OR EXISTS(SELECT 1 FROM public.ingestion_jobs i WHERE i.tenant_id=request_tenant AND i.source_id=request_source AND i.job_status IN ('QUEUED','PROCESSING'))
 THEN RETURN QUERY SELECT NULL::uuid,false,'COLLECTION_ALREADY_ACTIVE'::text; RETURN; END IF;
 IF EXISTS(SELECT 1 FROM public.market_tracking_outbox o WHERE o.tenant_id=request_tenant AND o.source_id=request_source AND o.kind='COLLECTION' AND (o.created_at,o.event_id)>(parent.created_at,parent.event_id))
 THEN RETURN QUERY SELECT NULL::uuid,false,'COLLECTION_CHANGED'::text; RETURN; END IF;
 UPDATE public.data_sources ds SET sync_frequency_minutes=cadence WHERE ds.tenant_id=request_tenant AND ds.source_id=request_source;
 INSERT INTO public.market_tracking_outbox(tenant_id,kind,source_id,dedupe_key,retry_of_event_id)
 VALUES(request_tenant,'COLLECTION',request_source,'collection-retry:'||failed_event::text,failed_event) RETURNING market_tracking_outbox.event_id INTO new_id;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
 VALUES(request_tenant,NULLIF(current_setting('app.current_user_id',true),'')::uuid,'MARKET_COLLECTION_RETRY','market_tracking_outbox',new_id,
  jsonb_build_object('parentEventId',failed_event,'sourceId',request_source,'competitorId',request_competitor));
 RETURN QUERY SELECT new_id,true,'RETRY_QUEUED'::text;
END $$;
REVOKE ALL ON FUNCTION public.retry_market_collection(UUID,UUID,UUID,UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.retry_market_collection(UUID,UUID,UUID,UUID) TO ceopro_app;

-- Bound status lookups to the latest request/job per source, not its history.
CREATE INDEX market_collection_latest ON public.market_tracking_outbox(tenant_id,source_id,created_at DESC,event_id DESC) WHERE kind='COLLECTION';
CREATE INDEX ingestion_source_latest ON public.ingestion_jobs(tenant_id,source_id,created_at DESC,job_id DESC);
