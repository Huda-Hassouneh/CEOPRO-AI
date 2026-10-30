-- Durable request/row ownership around the existing extraction authority.
CREATE TABLE public.keel_file_upload_requests(
 request_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
 actor_id uuid NOT NULL REFERENCES users(user_id),request_key varchar(128) NOT NULL,payload_hash char(64) NOT NULL,
 file_name text NOT NULL,payload bytea NOT NULL CHECK(octet_length(payload)<=10485760),
 job_id uuid REFERENCES ingestion_jobs(job_id),reservation jsonb,state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','processing','failed','completed')),
 response jsonb,error_code text,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,request_key));
ALTER TABLE public.keel_file_upload_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_file_upload_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY upload_actor ON public.keel_file_upload_requests TO ceopro_app
 USING(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
REVOKE ALL ON public.keel_file_upload_requests FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.keel_file_upload_requests TO ceopro_app;
CREATE FUNCTION public.keel_upload_request_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF (OLD.tenant_id,OLD.actor_id,OLD.request_key,OLD.payload_hash,OLD.payload,OLD.file_name) IS DISTINCT FROM (NEW.tenant_id,NEW.actor_id,NEW.request_key,NEW.payload_hash,NEW.payload,NEW.file_name)
 OR (OLD.job_id IS NOT NULL AND OLD.job_id IS DISTINCT FROM NEW.job_id)
 OR (OLD.reservation IS NOT NULL AND OLD.reservation IS DISTINCT FROM NEW.reservation)
 OR OLD.state='completed' THEN RAISE EXCEPTION 'Upload identity and completed evidence are immutable';END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER upload_request_immutable BEFORE UPDATE ON public.keel_file_upload_requests FOR EACH ROW EXECUTE FUNCTION public.keel_upload_request_immutable();
REVOKE ALL ON FUNCTION public.keel_upload_request_immutable() FROM PUBLIC;
