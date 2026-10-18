-- Hosted RAG parses source bytes per query; Stored does not claim indexing.
ALTER TABLE public.rag_documents_metadata DROP CONSTRAINT chk_rag_doc_processed_status;
ALTER TABLE public.rag_documents_metadata ADD CONSTRAINT chk_rag_doc_processed_status
  CHECK (processed_status IN ('Pending','Stored','Processed','Failed'));

-- BYTEA length is authoritative. External originals reserve their declared size;
-- orphan ceopro-db markers contain no retained original and consume no capacity.
CREATE FUNCTION public.retained_document_bytes(request_tenant uuid) RETURNS bigint
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public, pg_temp AS $$
 SELECT COALESCE(SUM(CASE WHEN source_file_content IS NOT NULL THEN octet_length(source_file_content)::bigint
   WHEN storage_bucket_path LIKE 'ceopro-db://%' THEN 0 ELSE file_size_bytes END),0)::bigint
 FROM public.rag_documents_metadata WHERE tenant_id = request_tenant
$$;
REVOKE ALL ON FUNCTION public.retained_document_bytes(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.retained_document_bytes(uuid) TO ceopro_app;

CREATE FUNCTION public.enforce_document_storage_capacity() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE previous_bytes bigint := 0; incoming_bytes bigint; used_bytes bigint; plan uuid; cap integer;
BEGIN
 IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
   RAISE EXCEPTION 'DOCUMENT_TENANT_IMMUTABLE' USING ERRCODE='23514';
 END IF;
 -- This guard owns Node BYTEA originals. External object writers must reserve
 -- object capacity in their own transaction; this migration does not operate MinIO.
 IF NEW.storage_bucket_path NOT LIKE 'ceopro-db://%' AND current_user <> 'ceopro_app' THEN RETURN NEW; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('document-storage:' || NEW.tenant_id::text,0));
 IF NEW.source_file_content IS NOT NULL THEN NEW.file_size_bytes := octet_length(NEW.source_file_content); END IF;
 incoming_bytes := CASE WHEN NEW.source_file_content IS NOT NULL THEN octet_length(NEW.source_file_content)
   WHEN NEW.storage_bucket_path LIKE 'ceopro-db://%' THEN 0 ELSE NEW.file_size_bytes END;
 IF TG_OP='UPDATE' THEN
   previous_bytes := CASE WHEN OLD.source_file_content IS NOT NULL THEN octet_length(OLD.source_file_content)
     WHEN OLD.storage_bucket_path LIKE 'ceopro-db://%' THEN 0 ELSE OLD.file_size_bytes END;
 END IF;
 IF incoming_bytes <= previous_bytes THEN RETURN NEW; END IF;
 -- A wait on the advisory lock must be followed by a fresh READ COMMITTED snapshot.
 IF current_setting('transaction_isolation') <> 'read committed' THEN
   RAISE EXCEPTION 'DOCUMENT_STORAGE_REQUIRES_READ_COMMITTED' USING ERRCODE='23514';
 END IF;
 SELECT s.plan_id INTO plan FROM public.subscriptions s
 WHERE s.tenant_id=NEW.tenant_id AND s.status IN ('active','trialing')
 ORDER BY s.updated_at DESC,s.created_at DESC LIMIT 1 FOR SHARE;
 SELECT pf.limit_value INTO cap FROM public.plan_features pf JOIN public.features f ON f.feature_id=pf.feature_id
 WHERE pf.plan_id=plan AND f.feature_code='document_storage_mb' AND f.feature_type='limit' AND f.aggregation_type='max';
 IF NOT FOUND THEN RAISE EXCEPTION 'DOCUMENT_STORAGE_NOT_INCLUDED' USING ERRCODE='23514'; END IF;
 used_bytes := public.retained_document_bytes(NEW.tenant_id);
 IF cap IS NOT NULL AND used_bytes-previous_bytes+incoming_bytes > cap::bigint*1048576 THEN
   RAISE EXCEPTION 'DOCUMENT_STORAGE_CAPACITY_EXCEEDED' USING ERRCODE='23514',CONSTRAINT='document_storage_capacity';
 END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.enforce_document_storage_capacity() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enforce_document_storage_capacity() TO ceopro_app;
CREATE TRIGGER guard_document_storage_capacity BEFORE INSERT OR UPDATE OF tenant_id,source_file_content,file_size_bytes,storage_bucket_path
 ON public.rag_documents_metadata FOR EACH ROW EXECUTE FUNCTION public.enforce_document_storage_capacity();
