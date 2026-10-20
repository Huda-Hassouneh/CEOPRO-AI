-- Keep caller-controlled temporary relations behind the trusted application
-- schema in the four pre-existing authentication SECURITY DEFINER functions.
-- ALTER FUNCTION preserves each function's body, owner, signature, and grants.
ALTER FUNCTION public.auth_email_verified(uuid)
    SET search_path = pg_catalog, public, pg_temp;

ALTER FUNCTION public.auth_join_tenant(uuid, uuid, character varying, bigint)
    SET search_path = pg_catalog, public, pg_temp;

ALTER FUNCTION public.auth_lookup_user_by_email(text)
    SET search_path = pg_catalog, public, pg_temp;

ALTER FUNCTION public.auth_mark_email_verified(uuid)
    SET search_path = pg_catalog, public, pg_temp;
