-- Forward-only: preserve every mapping, price, source and job. Archived mappings
-- remain addressable by their original IDs and cannot contaminate a replacement.
ALTER TABLE public.competitor_product_mappings DROP CONSTRAINT uq_tenant_competitor_product;
CREATE UNIQUE INDEX uq_tenant_competitor_product
 ON public.competitor_product_mappings(tenant_id,global_competitor_id,product_id)
 WHERE is_active OR tracking_paused;

CREATE TABLE public.competitor_product_candidates (
 candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id UUID NOT NULL,
 global_competitor_id UUID NOT NULL,
 product_id UUID NOT NULL,
 product_url TEXT NOT NULL CHECK(length(product_url) BETWEEN 1 AND 2048),
 title TEXT NOT NULL DEFAULT '' CHECK(length(title)<=500),
 discovery_score NUMERIC(6,5) NOT NULL DEFAULT 0 CHECK(discovery_score BETWEEN 0 AND 1),
 status TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK(status IN ('DISCOVERED','SELECTED','REJECTED')),
 evidence JSONB,
 checked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT candidate_tenant_competitor FOREIGN KEY(tenant_id,global_competitor_id)
  REFERENCES public.tenant_competitors(tenant_id,global_competitor_id) ON DELETE CASCADE,
 CONSTRAINT candidate_tenant_product FOREIGN KEY(tenant_id,product_id)
  REFERENCES public.products(tenant_id,product_id) ON DELETE CASCADE,
 CONSTRAINT candidate_unique_url UNIQUE(tenant_id,global_competitor_id,product_id,product_url)
);
CREATE INDEX candidate_product_lookup ON public.competitor_product_candidates(tenant_id,global_competitor_id,product_id,last_seen_at DESC);
ALTER TABLE public.competitor_product_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_product_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY candidate_tenant_perimeter ON public.competitor_product_candidates
 FOR ALL USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
REVOKE ALL ON public.competitor_product_candidates FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.competitor_product_candidates TO ceopro_app;
DO $$ DECLARE runtime TEXT; BEGIN
 FOREACH runtime IN ARRAY ARRAY['ceopro_ai_prod_user','ceopro_ai_test_user','ceopro_ai_test_writer'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=runtime) THEN
   EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.competitor_product_candidates TO %I',runtime);
  END IF;
 END LOOP;
END $$;

CREATE FUNCTION public.guard_mapping_identity_history() RETURNS TRIGGER
 LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.competitor_product_url IS DISTINCT FROM OLD.competitor_product_url
  OR NEW.source_id IS DISTINCT FROM OLD.source_id OR NEW.product_id IS DISTINCT FROM OLD.product_id
  OR NEW.global_competitor_id IS DISTINCT FROM OLD.global_competitor_id
 THEN RAISE EXCEPTION 'MAPPING_REPLACEMENT_REQUIRED' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_mapping_identity_history() FROM PUBLIC;
CREATE TRIGGER mapping_identity_history BEFORE UPDATE ON public.competitor_product_mappings
 FOR EACH ROW EXECUTE FUNCTION public.guard_mapping_identity_history();

-- Preview checks are read-only and separate. Recurring collection requires a
-- confirmed identity; robots/terms alone must not schedule unconfirmed matches.
CREATE FUNCTION public.guard_confirmed_market_request() RETURNS TRIGGER
 LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.kind='COLLECTION' AND NOT EXISTS(
  SELECT 1 FROM public.competitor_product_mappings m
  JOIN public.tenant_competitors tc ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
  WHERE m.tenant_id=NEW.tenant_id AND m.source_id=NEW.source_id
   AND m.is_active AND m.comparison_confirmed AND tc.is_tracked
 ) THEN RETURN NULL; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_confirmed_market_request() FROM PUBLIC;
CREATE TRIGGER confirmed_market_request BEFORE INSERT ON public.market_tracking_outbox
 FOR EACH ROW EXECUTE FUNCTION public.guard_confirmed_market_request();

CREATE FUNCTION public.cancel_ineligible_mapping_collection() RETURNS TRIGGER
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.is_active AND NEW.comparison_confirmed THEN RETURN NEW; END IF;
 UPDATE public.market_tracking_outbox o SET worker_status='CANCELLED',worker_finished_at=now(),
  worker_error_code='MAPPING_NO_LONGER_ELIGIBLE',status='CANCELLED'
 WHERE o.tenant_id=NEW.tenant_id AND o.source_id=NEW.source_id AND o.kind='COLLECTION'
  AND o.worker_status IN ('QUEUED','RUNNING') AND NOT EXISTS(
   SELECT 1 FROM public.competitor_product_mappings m JOIN public.tenant_competitors tc
    ON tc.tenant_id=m.tenant_id AND tc.global_competitor_id=m.global_competitor_id
   WHERE m.tenant_id=NEW.tenant_id AND m.source_id=NEW.source_id AND m.is_active AND m.comparison_confirmed AND tc.is_tracked);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.cancel_ineligible_mapping_collection() FROM PUBLIC;
CREATE TRIGGER cancel_mapping_collection AFTER UPDATE OF is_active,comparison_confirmed ON public.competitor_product_mappings
 FOR EACH ROW EXECUTE FUNCTION public.cancel_ineligible_mapping_collection();

-- Include brand/GTIN edits, reusing the existing product confirmation reset.
CREATE OR REPLACE FUNCTION public.reset_catalog_competitor_confirmations() RETURNS TRIGGER
 LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.product_name IS DISTINCT FROM OLD.product_name OR NEW.sku IS DISTINCT FROM OLD.sku
  OR NEW.gtin IS DISTINCT FROM OLD.gtin OR NEW.brand IS DISTINCT FROM OLD.brand THEN
  UPDATE public.competitor_product_mappings SET comparison_confirmed=FALSE
   WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND comparison_confirmed;
  UPDATE public.competitor_product_candidates SET evidence=NULL,checked_at=NULL
   WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER catalog_competitor_confirmation_guard ON public.products;
CREATE TRIGGER catalog_competitor_confirmation_guard AFTER UPDATE OF product_name,sku,gtin,brand ON public.products
 FOR EACH ROW EXECUTE FUNCTION public.reset_catalog_competitor_confirmations();

GRANT SELECT(comparison_confirmed) ON public.competitor_product_mappings TO ceopro_market_dispatcher;

CREATE OR REPLACE FUNCTION public.retry_market_collection(request_tenant UUID,request_competitor UUID,request_source UUID,failed_event UUID)
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
  WHERE ds.tenant_id=request_tenant AND ds.source_id=request_source AND tc.global_competitor_id=request_competitor AND tc.is_tracked AND m.is_active AND m.comparison_confirmed AND p.deleted_at IS NULL
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

CREATE OR REPLACE FUNCTION public.cancel_unapproved_source_collection() RETURNS TRIGGER
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE saved_tenant TEXT:=current_setting('app.current_tenant_id',true);
BEGIN
 IF NEW.is_active AND NEW.policy_status='ALLOWED' AND NEW.approved_at IS NOT NULL
  AND NEW.approved_by IS NOT NULL AND NEW.approval_reference IS NOT NULL AND NEW.privacy_reviewed_at IS NOT NULL THEN RETURN NEW; END IF;
 PERFORM set_config('app.current_tenant_id',NEW.tenant_id::TEXT,true);
 UPDATE public.market_tracking_outbox o SET status='CANCELLED',worker_status='CANCELLED',worker_finished_at=now(),worker_error_code='SOURCE_NO_LONGER_ELIGIBLE',last_error_code='NO_LONGER_ELIGIBLE'
  WHERE o.tenant_id=NEW.tenant_id AND o.source_id=NEW.source_id AND o.kind='COLLECTION' AND (o.status='PENDING' OR o.worker_status IN ('QUEUED','RUNNING'));
 PERFORM set_config('app.current_tenant_id',coalesce(saved_tenant,''),true);
 RETURN NEW;
END $$;
