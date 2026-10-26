-- Extend the existing typed provider authority for real Woo simple-product fields.
-- All original fence, identity, immutability and tenant checks remain unchanged.
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
   WHEN 'product' THEN ARRAY['title','handle','status','vendor','created_at','updated_at','sku','barcode','price','product_type','regular_price','sale_price','currency_code']
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
