-- Image queue access is separate from tenant request and migration identities.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_image_worker') THEN
        CREATE ROLE ceopro_image_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ceopro_image_worker' AND
        (rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication OR rolbypassrls OR NOT rolcanlogin))
       OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_image_worker')) THEN
        RAISE EXCEPTION 'image worker role has unsafe attributes or memberships';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO ceopro_image_worker;

CREATE OR REPLACE FUNCTION public.image_worker_claim(p_worker_id text, p_stale_seconds integer)
RETURNS TABLE(job_id uuid, tenant_id uuid, created_by uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 120 OR
       p_stale_seconds IS NULL OR p_stale_seconds < 1 THEN
        RAISE EXCEPTION 'invalid image worker claim';
    END IF;
    RETURN QUERY SELECT * FROM public.claim_image_generation_job(p_worker_id, p_stale_seconds);
END $$;

CREATE OR REPLACE FUNCTION public.image_worker_heartbeat(p_worker_id text, p_host text, p_servers integer, p_made integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 120 OR
       p_host IS NULL OR length(p_host) NOT BETWEEN 1 AND 200 OR
       p_servers IS NULL OR p_servers < 1 OR p_servers > 1024 OR
       p_made IS NULL OR p_made < 0 THEN
        RAISE EXCEPTION 'invalid image worker heartbeat';
    END IF;
    INSERT INTO public.image_workers (worker_id,host,servers,heartbeat_at,images_made)
    VALUES (p_worker_id,p_host,p_servers,now(),p_made)
    ON CONFLICT (worker_id) DO UPDATE SET heartbeat_at=now(),servers=EXCLUDED.servers,
        images_made=public.image_workers.images_made+EXCLUDED.images_made;
END $$;

CREATE OR REPLACE FUNCTION public.image_job_heartbeat(p_job_id uuid, p_worker_id text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF p_job_id IS NULL OR p_worker_id IS NULL OR length(p_worker_id) NOT BETWEEN 1 AND 120 THEN
        RAISE EXCEPTION 'invalid image job heartbeat';
    END IF;
    UPDATE public.image_generation_jobs SET heartbeat_at=now()
        WHERE job_id=p_job_id AND worker_id=p_worker_id AND status='RUNNING';
    RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.image_worker_heartbeat(text,text,integer,integer) FROM PUBLIC, ceopro_app;
REVOKE ALL ON FUNCTION public.image_job_heartbeat(uuid,text) FROM PUBLIC, ceopro_app;
REVOKE ALL ON FUNCTION public.image_worker_claim(text,integer) FROM PUBLIC, ceopro_app;
GRANT EXECUTE ON FUNCTION public.image_worker_claim(text,integer) TO ceopro_image_worker;
GRANT EXECUTE ON FUNCTION public.image_worker_heartbeat(text,text,integer,integer) TO ceopro_image_worker;
GRANT EXECUTE ON FUNCTION public.image_job_heartbeat(uuid,text) TO ceopro_image_worker;
