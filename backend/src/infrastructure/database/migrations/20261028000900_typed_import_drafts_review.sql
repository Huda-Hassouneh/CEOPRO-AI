-- Migration 97: typed import batches, immutable revisions, rows, and review evidence.
-- Owner approved scope and restrictive evidence deletion on 2026-10-21.
-- Existing raw staging, ingestion jobs, canonical records, and billing remain authoritative.

CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_job_source97
    ON public.ingestion_jobs(tenant_id,source_id,job_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_staging_row_tenant97
    ON public.import_staging_rows(tenant_id,staging_row_id);

CREATE TABLE public.keel_import_batches (
    tenant_id UUID NOT NULL,
    batch_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    job_id UUID NOT NULL,
    import_category TEXT NOT NULL CHECK (import_category IN ('sales','invoice','inventory')),
    source_provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(source_provenance)='object'),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 180),
    request_sha256 CHAR(64) NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    schema_version TEXT NOT NULL CHECK (length(btrim(schema_version)) BETWEEN 1 AND 64),
    current_revision_id UUID,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('draft','review_required','approved','rejected')),
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,batch_id),
    CONSTRAINT uq_keel_import_batch_idem97 UNIQUE (tenant_id,source_id,job_id,import_category,idempotency_key),
    CONSTRAINT uq_keel_import_batch_scope97 UNIQUE (tenant_id,batch_id,source_id,job_id),
    CONSTRAINT fk_keel_import_batch_tenant97 FOREIGN KEY (tenant_id) REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_batch_source97 FOREIGN KEY (tenant_id,source_id) REFERENCES public.data_sources(tenant_id,source_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_batch_job97 FOREIGN KEY (tenant_id,source_id,job_id) REFERENCES public.ingestion_jobs(tenant_id,source_id,job_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_batch_actor97 FOREIGN KEY (created_by_user_id) REFERENCES public.users(user_id) ON DELETE RESTRICT
);

CREATE TABLE public.keel_import_revisions (
    tenant_id UUID NOT NULL,
    revision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number>0),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 180),
    prior_revision_id UUID,
    schema_version TEXT NOT NULL CHECK (length(btrim(schema_version)) BETWEEN 1 AND 64),
    revision_sha256 CHAR(64) NOT NULL CHECK (revision_sha256 ~ '^[0-9a-f]{64}$'),
    source_provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(source_provenance)='object'),
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,revision_id),
    CONSTRAINT uq_keel_import_revision_number97 UNIQUE (tenant_id,batch_id,revision_number),
    CONSTRAINT uq_keel_import_revision_idem97 UNIQUE (tenant_id,batch_id,idempotency_key),
    CONSTRAINT uq_keel_import_revision_batch97 UNIQUE (tenant_id,batch_id,revision_id),
    CONSTRAINT fk_keel_import_revision_batch97 FOREIGN KEY (tenant_id,batch_id) REFERENCES public.keel_import_batches(tenant_id,batch_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_revision_prior97 FOREIGN KEY (tenant_id,batch_id,prior_revision_id) REFERENCES public.keel_import_revisions(tenant_id,batch_id,revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_revision_actor97 FOREIGN KEY (created_by_user_id) REFERENCES public.users(user_id) ON DELETE RESTRICT
);
ALTER TABLE public.keel_import_batches ADD CONSTRAINT fk_keel_import_batch_current_revision97
    FOREIGN KEY (tenant_id,batch_id,current_revision_id) REFERENCES public.keel_import_revisions(tenant_id,batch_id,revision_id) ON DELETE RESTRICT;

CREATE TABLE public.keel_import_draft_rows (
    tenant_id UUID NOT NULL,
    draft_row_id UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    source_row_key TEXT NOT NULL CHECK (length(btrim(source_row_key)) BETWEEN 1 AND 180),
    staging_row_id BIGINT,
    row_number INTEGER NOT NULL CHECK (row_number>=0),
    import_category TEXT NOT NULL CHECK (import_category IN ('sales','invoice','inventory')),
    typed_values JSONB NOT NULL CHECK (jsonb_typeof(typed_values)='object'),
    validation_findings JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(validation_findings)='array'),
    validation_outcome TEXT NOT NULL CHECK (validation_outcome IN ('valid','invalid','review_required')),
    product_candidate JSONB CHECK (product_candidate IS NULL OR jsonb_typeof(product_candidate)='object'),
    ambiguity_code TEXT,
    source_provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(source_provenance)='object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,draft_row_id),
    CONSTRAINT uq_keel_import_draft_row_key97 UNIQUE (tenant_id,revision_id,source_row_key),
    CONSTRAINT uq_keel_import_draft_row_scope97 UNIQUE (tenant_id,batch_id,revision_id,draft_row_id),
    CONSTRAINT fk_keel_import_draft_revision97 FOREIGN KEY (tenant_id,batch_id,revision_id) REFERENCES public.keel_import_revisions(tenant_id,batch_id,revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_draft_staging97 FOREIGN KEY (tenant_id,staging_row_id) REFERENCES public.import_staging_rows(tenant_id,staging_row_id) ON DELETE RESTRICT
);
CREATE INDEX idx_keel_import_batch_state97 ON public.keel_import_batches(tenant_id,lifecycle_state,created_at DESC);
CREATE INDEX idx_keel_import_rows_revision97 ON public.keel_import_draft_rows(tenant_id,batch_id,revision_id,row_number);

CREATE TABLE public.keel_import_review_decisions (
    tenant_id UUID NOT NULL,
    decision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    draft_row_id UUID,
    decision TEXT NOT NULL CHECK (decision IN ('approve','reject')),
    idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 180),
    reason_code TEXT NOT NULL CHECK (length(btrim(reason_code)) BETWEEN 1 AND 100),
    reviewer_user_id UUID NOT NULL,
    prior_decision_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,decision_id),
    CONSTRAINT uq_keel_import_review_idem97 UNIQUE (tenant_id,batch_id,revision_id,draft_row_id,idempotency_key),
    CONSTRAINT fk_keel_import_review_batch97 FOREIGN KEY (tenant_id,batch_id,revision_id) REFERENCES public.keel_import_revisions(tenant_id,batch_id,revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_review_row97 FOREIGN KEY (tenant_id,batch_id,revision_id,draft_row_id) REFERENCES public.keel_import_draft_rows(tenant_id,batch_id,revision_id,draft_row_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_review_prior97 FOREIGN KEY (tenant_id,prior_decision_id) REFERENCES public.keel_import_review_decisions(tenant_id,decision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_import_review_actor97 FOREIGN KEY (reviewer_user_id) REFERENCES public.users(user_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION public.keel_import_immutable97() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN RAISE EXCEPTION 'import draft evidence is immutable' USING ERRCODE='55000'; END $$;
CREATE TRIGGER keel_import_revision_immutable97 BEFORE UPDATE OR DELETE ON public.keel_import_revisions FOR EACH ROW EXECUTE FUNCTION public.keel_import_immutable97();
CREATE TRIGGER keel_import_row_immutable97 BEFORE UPDATE OR DELETE ON public.keel_import_draft_rows FOR EACH ROW EXECUTE FUNCTION public.keel_import_immutable97();
CREATE TRIGGER keel_import_decision_immutable97 BEFORE UPDATE OR DELETE ON public.keel_import_review_decisions FOR EACH ROW EXECUTE FUNCTION public.keel_import_immutable97();

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['keel_import_batches','keel_import_revisions','keel_import_draft_rows','keel_import_review_decisions'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT USING (tenant_id=public.get_current_tenant())', 'tenant_read_'||t,t);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
    EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app',t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.keel_import_batch_create97(
 p_source UUID,p_job UUID,p_category TEXT,p_schema TEXT,p_idem TEXT,p_fingerprint TEXT,p_rows JSONB,p_provenance JSONB DEFAULT '{}'::jsonb
) RETURNS TABLE(batch_id UUID,revision_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        b UUID; r UUID; old_hash TEXT; row_item JSONB; inserted_id UUID; idx BIGINT; overall TEXT;
BEGIN
 IF tid IS NULL OR actor IS NULL OR public.get_current_tenant() IS DISTINCT FROM tid OR NOT public.keel_active_principal(actor,tid) THEN RAISE EXCEPTION 'active tenant actor required' USING ERRCODE='42501'; END IF;
 IF p_category NOT IN ('sales','invoice','inventory') OR p_schema IS NULL OR length(btrim(p_schema)) NOT BETWEEN 1 AND 64
  OR p_idem IS NULL OR length(btrim(p_idem)) NOT BETWEEN 1 AND 180 OR p_fingerprint !~ '^[0-9a-f]{64}$'
  OR jsonb_typeof(p_rows)<>'array' OR jsonb_array_length(p_rows)>10000 OR octet_length(p_rows::text)>8000000
  OR jsonb_typeof(coalesce(p_provenance,'{}'::jsonb))<>'object' THEN RAISE EXCEPTION 'typed import batch request is invalid' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.data_sources s JOIN public.ingestion_jobs j ON j.tenant_id=s.tenant_id AND j.source_id=s.source_id
   WHERE s.tenant_id=tid AND s.source_id=p_source AND j.job_id=p_job) THEN RAISE EXCEPTION 'tenant source and ingestion job do not match' USING ERRCODE='23503'; END IF;
 -- Serialize first creation as well as retries: SELECT FOR UPDATE alone does
 -- not lock a missing idempotency row, so concurrent first submissions race.
 PERFORM pg_advisory_xact_lock(hashtextextended(
   tid::text||':'||p_source::text||':'||p_job::text||':'||p_category||':'||p_idem,0));
 SELECT x.batch_id,x.current_revision_id,x.request_sha256 INTO b,r,old_hash FROM public.keel_import_batches x
  WHERE x.tenant_id=tid AND x.source_id=p_source AND x.job_id=p_job AND x.import_category=p_category AND x.idempotency_key=p_idem FOR UPDATE;
 IF FOUND THEN IF old_hash<>p_fingerprint THEN RAISE EXCEPTION 'import idempotency key reused with different content' USING ERRCODE='23505'; END IF; RETURN QUERY SELECT b,r,TRUE; RETURN; END IF;
 overall:=CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p_rows) e WHERE e->>'validation_outcome'<>'valid') THEN 'review_required' ELSE 'draft' END;
 INSERT INTO public.keel_import_batches(tenant_id,source_id,job_id,import_category,source_provenance,idempotency_key,request_sha256,schema_version,lifecycle_state,created_by_user_id)
  VALUES(tid,p_source,p_job,p_category,coalesce(p_provenance,'{}'::jsonb),p_idem,p_fingerprint,p_schema,overall,actor) RETURNING public.keel_import_batches.batch_id INTO b;
 INSERT INTO public.keel_import_revisions(tenant_id,batch_id,revision_number,idempotency_key,schema_version,revision_sha256,source_provenance,created_by_user_id)
  VALUES(tid,b,1,p_idem,p_schema,p_fingerprint,coalesce(p_provenance,'{}'::jsonb),actor) RETURNING public.keel_import_revisions.revision_id INTO r;
 UPDATE public.keel_import_batches SET current_revision_id=r WHERE tenant_id=tid AND public.keel_import_batches.batch_id=b;
 FOR row_item,idx IN SELECT value,ordinality FROM jsonb_array_elements(p_rows) WITH ORDINALITY LOOP
  INSERT INTO public.keel_import_draft_rows(tenant_id,batch_id,revision_id,source_row_key,staging_row_id,row_number,import_category,typed_values,validation_findings,validation_outcome,product_candidate,ambiguity_code,source_provenance)
  VALUES(tid,b,r,row_item->>'source_row_key',nullif(row_item->>'staging_row_id','')::bigint,coalesce(nullif(row_item->>'row_number','')::int,(idx-1)::int),p_category,
   coalesce(row_item->'typed_values','{}'::jsonb),coalesce(row_item->'validation_findings','[]'::jsonb),row_item->>'validation_outcome',row_item->'product_candidate',row_item->>'ambiguity_code',coalesce(row_item->'source_provenance','{}'::jsonb));
 END LOOP;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
  VALUES(tid,actor,'IMPORT_DRAFT_CREATED','keel_import_batches',b,jsonb_build_object('category',p_category,'job_id',p_job,'revision_id',r,'row_count',jsonb_array_length(p_rows)));
 RETURN QUERY SELECT b,r,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_import_batch_create97(UUID,UUID,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_import_batch_create97(UUID,UUID,TEXT,TEXT,TEXT,TEXT,JSONB,JSONB) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_import_revision_create97(p_batch UUID,p_schema TEXT,p_idem TEXT,p_fingerprint TEXT,p_rows JSONB,p_provenance JSONB DEFAULT '{}'::jsonb)
RETURNS TABLE(revision_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid; b public.keel_import_batches%ROWTYPE; r UUID; n INT; prior UUID; old_hash TEXT;
BEGIN
 IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid) OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=tid AND u.user_id=actor AND lower(u.role_key) IN ('owner','admin') AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL) THEN RAISE EXCEPTION 'tenant owner or admin required to amend an import draft' USING ERRCODE='42501'; END IF;
 IF p_schema IS NULL OR length(btrim(p_schema)) NOT BETWEEN 1 AND 64 OR p_idem IS NULL OR length(btrim(p_idem)) NOT BETWEEN 1 AND 180
  OR p_fingerprint !~ '^[0-9a-f]{64}$' OR jsonb_typeof(p_rows)<>'array' OR jsonb_array_length(p_rows)>10000 OR octet_length(p_rows::text)>8000000 THEN
  RAISE EXCEPTION 'import revision request is invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO b FROM public.keel_import_batches x WHERE x.tenant_id=tid AND x.batch_id=p_batch FOR UPDATE;
 IF NOT FOUND OR b.lifecycle_state IN ('approved','rejected') THEN RAISE EXCEPTION 'import draft cannot be amended' USING ERRCODE='55000'; END IF;
 SELECT x.revision_id,x.revision_number,x.revision_sha256 INTO r,n,old_hash FROM public.keel_import_revisions x WHERE x.tenant_id=tid AND x.batch_id=p_batch AND x.idempotency_key=p_idem;
 IF FOUND THEN IF old_hash<>p_fingerprint THEN RAISE EXCEPTION 'revision idempotency key reused with different content' USING ERRCODE='23505'; END IF; RETURN QUERY SELECT r,TRUE; RETURN; END IF;
 SELECT x.revision_id,x.revision_number INTO prior,n FROM public.keel_import_revisions x WHERE x.tenant_id=tid AND x.batch_id=p_batch ORDER BY x.revision_number DESC LIMIT 1;
 INSERT INTO public.keel_import_revisions(tenant_id,batch_id,revision_number,idempotency_key,prior_revision_id,schema_version,revision_sha256,source_provenance,created_by_user_id)
  VALUES(tid,p_batch,n+1,p_idem,prior,p_schema,p_fingerprint,coalesce(p_provenance,'{}'::jsonb),actor) RETURNING public.keel_import_revisions.revision_id INTO r;
 INSERT INTO public.keel_import_draft_rows(tenant_id,batch_id,revision_id,source_row_key,staging_row_id,row_number,import_category,typed_values,validation_findings,validation_outcome,product_candidate,ambiguity_code,source_provenance)
  SELECT tid,p_batch,r,x->>'source_row_key',nullif(x->>'staging_row_id','')::bigint,coalesce(nullif(x->>'row_number','')::int,(ord-1)::int),b.import_category,coalesce(x->'typed_values','{}'::jsonb),coalesce(x->'validation_findings','[]'::jsonb),x->>'validation_outcome',x->'product_candidate',x->>'ambiguity_code',coalesce(x->'source_provenance','{}'::jsonb)
  FROM jsonb_array_elements(p_rows) WITH ORDINALITY AS j(x,ord);
 UPDATE public.keel_import_batches SET current_revision_id=r,lifecycle_state=CASE WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(p_rows) x WHERE x->>'validation_outcome'<>'valid') THEN 'review_required' ELSE 'draft' END,request_sha256=p_fingerprint,schema_version=p_schema,updated_at=clock_timestamp()
  WHERE tenant_id=tid AND batch_id=p_batch;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(tid,actor,'IMPORT_DRAFT_AMENDED','keel_import_batches',p_batch,jsonb_build_object('revision_id',r,'prior_revision_id',prior,'row_count',jsonb_array_length(p_rows)));
 RETURN QUERY SELECT r,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_import_revision_create97(UUID,TEXT,TEXT,TEXT,JSONB,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_import_revision_create97(UUID,TEXT,TEXT,TEXT,JSONB,JSONB) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_import_review_decide97(p_batch UUID,p_revision UUID,p_row UUID,p_decision TEXT,p_idem TEXT,p_reason TEXT)
RETURNS TABLE(decision_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid; b public.keel_import_batches%ROWTYPE; d UUID; prev UUID; outcome TEXT;
BEGIN
 IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid) OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=tid AND u.user_id=actor AND lower(u.role_key) IN ('owner','admin') AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL) THEN RAISE EXCEPTION 'tenant owner or admin reviewer required' USING ERRCODE='42501'; END IF;
 IF p_decision NOT IN ('approve','reject') OR p_idem IS NULL OR length(btrim(p_idem)) NOT BETWEEN 1 AND 180 OR p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'review decision is invalid' USING ERRCODE='22023'; END IF;
 SELECT * INTO b FROM public.keel_import_batches x WHERE x.tenant_id=tid AND x.batch_id=p_batch FOR UPDATE;
 IF NOT FOUND OR b.current_revision_id IS DISTINCT FROM p_revision THEN RAISE EXCEPTION 'review must target the current revision' USING ERRCODE='55000'; END IF;
 -- Return a committed idempotent retry even if the original decision made
 -- this batch final. New decisions still require an open batch below.
 SELECT x.decision_id INTO d FROM public.keel_import_review_decisions x WHERE x.tenant_id=tid AND x.batch_id=p_batch AND x.revision_id=p_revision AND x.draft_row_id IS NOT DISTINCT FROM p_row AND x.idempotency_key=p_idem;
 IF FOUND THEN IF NOT EXISTS(SELECT 1 FROM public.keel_import_review_decisions x WHERE x.tenant_id=tid AND x.decision_id=d AND x.decision=p_decision AND x.reason_code=p_reason AND x.reviewer_user_id=actor) THEN RAISE EXCEPTION 'review idempotency key reused with different decision' USING ERRCODE='23505'; END IF; RETURN QUERY SELECT d,TRUE; RETURN; END IF;
 IF b.lifecycle_state IN ('approved','rejected') THEN RAISE EXCEPTION 'review must target the current open revision' USING ERRCODE='55000'; END IF;
 IF p_row IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.keel_import_draft_rows x WHERE x.tenant_id=tid AND x.batch_id=p_batch AND x.revision_id=p_revision AND x.draft_row_id=p_row) THEN RAISE EXCEPTION 'review row is outside this tenant revision' USING ERRCODE='23503'; END IF;
 IF p_row IS NULL AND p_decision='approve' AND EXISTS(
   SELECT 1 FROM public.keel_import_draft_rows x WHERE x.tenant_id=tid AND x.batch_id=p_batch AND x.revision_id=p_revision
    AND x.validation_outcome<>'valid' AND NOT EXISTS(
      SELECT 1 FROM public.keel_import_review_decisions d WHERE d.tenant_id=tid AND d.batch_id=p_batch AND d.revision_id=p_revision
       AND d.draft_row_id=x.draft_row_id AND d.decision='approve'
       AND d.created_at=(SELECT max(last.created_at) FROM public.keel_import_review_decisions last WHERE last.tenant_id=tid AND last.batch_id=p_batch AND last.revision_id=p_revision AND last.draft_row_id=x.draft_row_id)
    )
 ) THEN RAISE EXCEPTION 'invalid or ambiguous rows require explicit row review before batch approval' USING ERRCODE='23514'; END IF;
 SELECT x.decision_id INTO prev FROM public.keel_import_review_decisions x WHERE x.tenant_id=tid AND x.batch_id=p_batch AND x.revision_id=p_revision AND x.draft_row_id IS NOT DISTINCT FROM p_row ORDER BY x.created_at DESC LIMIT 1;
 INSERT INTO public.keel_import_review_decisions(tenant_id,batch_id,revision_id,draft_row_id,decision,idempotency_key,reason_code,reviewer_user_id,prior_decision_id)
 VALUES(tid,p_batch,p_revision,p_row,p_decision,p_idem,p_reason,actor,prev) RETURNING public.keel_import_review_decisions.decision_id INTO d;
 IF p_row IS NULL THEN UPDATE public.keel_import_batches SET lifecycle_state=CASE WHEN p_decision='approve' THEN 'approved' ELSE 'rejected' END,updated_at=clock_timestamp() WHERE tenant_id=tid AND batch_id=p_batch; END IF;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json) VALUES(tid,actor,'IMPORT_DRAFT_'||upper(p_decision),'keel_import_review_decisions',d,jsonb_build_object('batch_id',p_batch,'revision_id',p_revision,'draft_row_id',p_row,'decision',p_decision,'reason_code',p_reason,'prior_decision_id',prev,'eligible_for_existing_path',p_decision='approve'));
 RETURN QUERY SELECT d,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_import_review_decide97(UUID,UUID,UUID,TEXT,TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_import_review_decide97(UUID,UUID,UUID,TEXT,TEXT,TEXT) TO ceopro_app;

