-- Migration 98: PII-minimized, provider-scoped typed business-record staging.
-- Owner approved schema/security scope on 2026-10-22.
-- This stores provider evidence only; it never posts canonical business data.

CREATE TABLE public.keel_provider_business_revisions (
    tenant_id UUID NOT NULL,
    business_revision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('shopify','woocommerce')),
    provider_record_identity_id UUID NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('product','variant','order','order_line_item')),
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    provider_identity_revision_sha256 CHAR(64) NOT NULL CHECK (provider_identity_revision_sha256 ~ '^[0-9a-f]{64}$'),
    business_values_sha256 CHAR(64) NOT NULL CHECK (business_values_sha256 ~ '^[0-9a-f]{64}$'),
    typed_values JSONB NOT NULL CHECK (jsonb_typeof(typed_values)='object' AND octet_length(typed_values::text)<=65536),
    validation_findings JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(validation_findings)='array' AND jsonb_array_length(validation_findings)<=200
        AND octet_length(validation_findings::text)<=16384
    ),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('valid','invalid','review_required')),
    ingestion_job_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,business_revision_id),
    CONSTRAINT uq_keel_provider_business_revision_no98 UNIQUE (tenant_id,provider_record_identity_id,revision_number),
    CONSTRAINT uq_keel_provider_business_content98 UNIQUE (tenant_id,provider_record_identity_id,business_values_sha256),
    CONSTRAINT uq_keel_provider_business_scope98 UNIQUE (tenant_id,source_id,provider,business_revision_id),
    CONSTRAINT fk_keel_provider_business_tenant98 FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_business_source98 FOREIGN KEY (tenant_id,source_id,provider)
        REFERENCES public.keel_provider_sources(tenant_id,source_id,provider) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_business_identity98 FOREIGN KEY (tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_business_job98 FOREIGN KEY (tenant_id,source_id,ingestion_job_id)
        REFERENCES public.ingestion_jobs(tenant_id,source_id,job_id) ON DELETE RESTRICT
);
CREATE INDEX idx_keel_provider_business_revision98
    ON public.keel_provider_business_revisions(tenant_id,source_id,entity_type,created_at DESC);
CREATE INDEX idx_keel_provider_business_job98
    ON public.keel_provider_business_revisions(tenant_id,source_id,ingestion_job_id);

CREATE TABLE public.keel_provider_business_reviews (
    tenant_id UUID NOT NULL,
    business_review_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('shopify','woocommerce')),
    provider_record_identity_id UUID NOT NULL,
    business_revision_id UUID NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve','reject')),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 180),
    reason_code TEXT NOT NULL CHECK (length(btrim(reason_code)) BETWEEN 1 AND 100),
    reviewer_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,business_review_id),
    CONSTRAINT uq_keel_provider_business_review_revision98 UNIQUE (tenant_id,business_revision_id),
    CONSTRAINT uq_keel_provider_business_review_idem98 UNIQUE (tenant_id,provider_record_identity_id,business_revision_id,idempotency_key),
    CONSTRAINT fk_keel_provider_business_review_identity98 FOREIGN KEY (tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_business_review_revision98 FOREIGN KEY (tenant_id,source_id,provider,business_revision_id)
        REFERENCES public.keel_provider_business_revisions(tenant_id,source_id,provider,business_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_business_review_actor98 FOREIGN KEY (reviewer_user_id)
        REFERENCES public.users(user_id) ON DELETE RESTRICT
);
CREATE INDEX idx_keel_provider_business_reviews98
    ON public.keel_provider_business_reviews(tenant_id,source_id,created_at DESC);

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['keel_provider_business_revisions','keel_provider_business_reviews'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO ceopro_app USING (tenant_id=public.get_current_tenant())','tenant_read_'||t,t);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
    EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app',t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.keel_provider_business_immutable98()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN RAISE EXCEPTION 'provider business staging and review evidence is immutable' USING ERRCODE='55000'; END $$;
REVOKE ALL ON FUNCTION public.keel_provider_business_immutable98() FROM PUBLIC;
CREATE TRIGGER keel_provider_business_revision_immutable98 BEFORE UPDATE OR DELETE ON public.keel_provider_business_revisions
  FOR EACH ROW EXECUTE FUNCTION public.keel_provider_business_immutable98();
CREATE TRIGGER keel_provider_business_review_immutable98 BEFORE UPDATE OR DELETE ON public.keel_provider_business_reviews
  FOR EACH ROW EXECUTE FUNCTION public.keel_provider_business_immutable98();

CREATE OR REPLACE FUNCTION public.keel_provider_business_stage98(
  p_source UUID,p_identity UUID,p_job UUID,p_receipt UUID,p_lease_owner TEXT,p_lease_generation BIGINT,
  p_configuration_version BIGINT,p_values_sha256 TEXT,p_values JSONB,p_findings JSONB,p_validation_status TEXT
) RETURNS TABLE(business_revision_id UUID,revision_number INTEGER,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        prov TEXT; entity TEXT; current_hash TEXT; existing_id UUID; existing_no INTEGER; n INTEGER; result_id UUID;
        receipt_row public.keel_operation_receipts%ROWTYPE; allowed_keys TEXT[]; value_key TEXT;
        existing_values JSONB; existing_findings JSONB; existing_status TEXT;
BEGIN
 IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid) OR p_source IS NULL OR p_identity IS NULL OR p_job IS NULL OR p_receipt IS NULL
   OR p_lease_owner IS NULL OR length(p_lease_owner)>200 OR p_lease_generation IS NULL OR p_lease_generation<1
   OR p_configuration_version IS NULL OR p_configuration_version<1
   OR p_values_sha256 IS NULL OR p_values_sha256 !~ '^[0-9a-f]{64}$'
   OR p_values IS NULL OR jsonb_typeof(p_values)<>'object' OR octet_length(p_values::text)>65536
   OR jsonb_typeof(coalesce(p_findings,'[]'::jsonb))<>'array' OR jsonb_array_length(coalesce(p_findings,'[]'::jsonb))>200
   OR octet_length(coalesce(p_findings,'[]'::jsonb)::text)>16384 OR p_validation_status IS NULL
   OR p_validation_status NOT IN ('valid','invalid','review_required') THEN
   RAISE EXCEPTION 'provider business staging request is invalid' USING ERRCODE='22023';
 END IF;
 SELECT * INTO receipt_row FROM public.keel_operation_receipts r WHERE r.tenant_id=tid AND r.receipt_id=p_receipt
   AND r.operation_type='scheduled_connector_sync' AND r.source_id=p_source AND r.target_kind='source' AND r.target_id=p_source
   AND r.principal_kind='service' AND r.state='provider_started'
   AND r.lease_owner=p_lease_owner AND r.lease_generation=p_lease_generation
   AND r.lease_expires_at>clock_timestamp() AND r.actor_user_id=actor FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'active provider synchronization lease is required' USING ERRCODE='42501'; END IF;
 SELECT s.provider,i.entity_type,i.current_revision_sha256 INTO prov,entity,current_hash
   FROM public.keel_provider_sources s JOIN public.data_sources ds ON ds.tenant_id=s.tenant_id AND ds.source_id=s.source_id
   JOIN public.keel_provider_record_identities i ON i.tenant_id=s.tenant_id AND i.source_id=s.source_id AND i.provider=s.provider
   WHERE s.tenant_id=tid AND s.source_id=p_source AND s.connection_state='verified' AND s.configuration_version=p_configuration_version
     AND ds.is_active IS TRUE AND ds.policy_status='ALLOWED' AND i.provider_record_identity_id=p_identity FOR SHARE OF ds;
 IF NOT FOUND OR receipt_row.ingestion_job_id IS DISTINCT FROM p_job THEN RAISE EXCEPTION 'verified source, identity, job, or configuration changed' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(tid::text||':'||p_identity::text,98));
 -- Re-read after acquiring the per-identity lock so concurrent staging attempts
 -- serialize without granting ceopro_app row-update privileges on M95 evidence.
 SELECT i.current_revision_sha256 INTO current_hash FROM public.keel_provider_record_identities i
   WHERE i.tenant_id=tid AND i.source_id=p_source AND i.provider=prov AND i.provider_record_identity_id=p_identity;
 IF NOT FOUND THEN RAISE EXCEPTION 'provider identity is unavailable' USING ERRCODE='23503'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.ingestion_jobs j WHERE j.tenant_id=tid AND j.source_id=p_source AND j.job_id=p_job AND j.job_status='PROCESSING') THEN
   RAISE EXCEPTION 'provider staging job is not processing' USING ERRCODE='42501'; END IF;
 IF NOT public.keel_provider_json_safe(p_values) OR NOT public.keel_provider_json_safe(coalesce(p_findings,'[]'::jsonb)) THEN
   RAISE EXCEPTION 'sensitive provider fields are not permitted in staging' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(p_findings,'[]'::jsonb)) f
   WHERE jsonb_typeof(f) IS DISTINCT FROM 'object' OR (f-ARRAY['field','code'])<>'{}'::jsonb
      OR jsonb_typeof(f->'field') IS DISTINCT FROM 'string' OR jsonb_typeof(f->'code') IS DISTINCT FROM 'string'
      OR length(f->>'field')>100 OR length(f->>'code')>100 OR length(btrim(f->>'field'))=0 OR length(btrim(f->>'code'))=0) THEN
   RAISE EXCEPTION 'provider validation finding is invalid' USING ERRCODE='22023'; END IF;
 allowed_keys:=CASE entity
   WHEN 'product' THEN ARRAY['title','handle','status','vendor','created_at','updated_at']
   WHEN 'variant' THEN ARRAY['title','sku','barcode','price','compare_at_price','inventory_tracked','created_at','updated_at','product_type','regular_price','sale_price','currency_code']
   WHEN 'order' THEN ARRAY['name','status','fulfillment_status','cancelled_at','test_order','currency_code','provider_totals','created_at','updated_at','refund_references']
   WHEN 'order_line_item' THEN ARRAY['title','quantity','sku','product_provider_id','variant_provider_id','original_unit_price','discounted_total','provider_amounts','currency_code']
 END;
 FOR value_key IN SELECT jsonb_object_keys(p_values) LOOP
   IF NOT value_key=ANY(allowed_keys) THEN RAISE EXCEPTION 'provider business field is not approved for staging' USING ERRCODE='22023'; END IF;
 END LOOP;
 SELECT b.business_revision_id,b.revision_number,b.typed_values,b.validation_findings,b.validation_status
   INTO existing_id,existing_no,existing_values,existing_findings,existing_status FROM public.keel_provider_business_revisions b
   WHERE b.tenant_id=tid AND b.provider_record_identity_id=p_identity AND b.business_values_sha256=p_values_sha256;
 IF FOUND THEN
   IF existing_values IS DISTINCT FROM p_values OR existing_findings IS DISTINCT FROM coalesce(p_findings,'[]'::jsonb)
       OR existing_status IS DISTINCT FROM p_validation_status THEN
     RAISE EXCEPTION 'provider business content fingerprint collision' USING ERRCODE='23505';
   END IF;
   RETURN QUERY SELECT existing_id,existing_no,TRUE; RETURN;
 END IF;
 SELECT coalesce(max(b.revision_number),0)+1 INTO n FROM public.keel_provider_business_revisions b
   WHERE b.tenant_id=tid AND b.provider_record_identity_id=p_identity;
 INSERT INTO public.keel_provider_business_revisions(tenant_id,source_id,provider,provider_record_identity_id,entity_type,revision_number,
   provider_identity_revision_sha256,business_values_sha256,typed_values,validation_findings,validation_status,ingestion_job_id)
 VALUES(tid,p_source,prov,p_identity,entity,n,current_hash,p_values_sha256,p_values,coalesce(p_findings,'[]'::jsonb),p_validation_status,p_job)
 RETURNING public.keel_provider_business_revisions.business_revision_id INTO result_id;
 RETURN QUERY SELECT result_id,n,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_business_stage98(UUID,UUID,UUID,UUID,TEXT,BIGINT,BIGINT,TEXT,JSONB,JSONB,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_business_stage98(UUID,UUID,UUID,UUID,TEXT,BIGINT,BIGINT,TEXT,JSONB,JSONB,TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_provider_business_review98(
  p_business_revision UUID,p_decision TEXT,p_idempotency_key TEXT,p_reason_code TEXT
) RETURNS TABLE(business_review_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        b public.keel_provider_business_revisions%ROWTYPE; i public.keel_provider_record_identities%ROWTYPE;
        old_id UUID; old_decision TEXT; old_reason TEXT; old_actor UUID; result_id UUID;
BEGIN
 IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid)
   OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=tid AND u.user_id=actor
      AND lower(u.role_key) IN ('owner','admin') AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL) THEN
   RAISE EXCEPTION 'tenant owner or admin is required to review provider records' USING ERRCODE='42501'; END IF;
 IF p_decision IS NULL OR p_decision NOT IN ('approve','reject') OR p_idempotency_key IS NULL OR length(btrim(p_idempotency_key)) NOT BETWEEN 1 AND 180
   OR p_reason_code IS NULL OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 100
   OR btrim(p_reason_code) !~ '^[A-Za-z0-9_.:-]+$' THEN RAISE EXCEPTION 'provider review request is invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO b FROM public.keel_provider_business_revisions x WHERE x.tenant_id=tid AND x.business_revision_id=p_business_revision;
 IF NOT FOUND THEN RAISE EXCEPTION 'provider business revision not found' USING ERRCODE='23503'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(tid::text||':'||b.provider_record_identity_id::text,98));
 SELECT * INTO i FROM public.keel_provider_record_identities x WHERE x.tenant_id=tid AND x.provider_record_identity_id=b.provider_record_identity_id FOR SHARE;
 SELECT r.business_review_id,r.decision,r.reason_code,r.reviewer_user_id INTO old_id,old_decision,old_reason,old_actor
   FROM public.keel_provider_business_reviews r WHERE r.tenant_id=tid AND r.provider_record_identity_id=b.provider_record_identity_id
    AND r.business_revision_id=p_business_revision AND r.idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF old_decision<>p_decision OR old_reason<>p_reason_code OR old_actor<>actor THEN RAISE EXCEPTION 'review idempotency key reused with different content' USING ERRCODE='23505'; END IF;
   RETURN QUERY SELECT old_id,TRUE; RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM public.keel_provider_business_revisions x WHERE x.tenant_id=tid AND x.provider_record_identity_id=b.provider_record_identity_id
      AND x.revision_number>b.revision_number) OR i.current_revision_sha256 IS DISTINCT FROM b.provider_identity_revision_sha256 THEN
   RAISE EXCEPTION 'provider business revision is stale' USING ERRCODE='55000'; END IF;
 IF p_decision='approve' AND b.validation_status='invalid' THEN RAISE EXCEPTION 'invalid provider record cannot be approved' USING ERRCODE='23514'; END IF;
 INSERT INTO public.keel_provider_business_reviews(tenant_id,source_id,provider,provider_record_identity_id,business_revision_id,decision,idempotency_key,reason_code,reviewer_user_id)
 VALUES(tid,b.source_id,b.provider,b.provider_record_identity_id,b.business_revision_id,p_decision,p_idempotency_key,btrim(p_reason_code),actor)
 RETURNING public.keel_provider_business_reviews.business_review_id INTO result_id;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
 VALUES(tid,actor,'PROVIDER_BUSINESS_RECORD_'||upper(p_decision),'keel_provider_business_revisions',p_business_revision,
   jsonb_build_object('source_id',b.source_id,'provider',b.provider,'entity_type',b.entity_type,'revision_number',b.revision_number,'decision',p_decision,'reason_code',btrim(p_reason_code),'canonical_write_performed',false));
 RETURN QUERY SELECT result_id,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_business_review98(UUID,TEXT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_business_review98(UUID,TEXT,TEXT,TEXT) TO ceopro_app;

COMMENT ON TABLE public.keel_provider_business_revisions IS 'Immutable PII-minimized provider product/order business values; evidence only, never canonical posting.';
COMMENT ON TABLE public.keel_provider_business_reviews IS 'Append-only tenant owner/admin review decisions; approval does not post canonical data.';
