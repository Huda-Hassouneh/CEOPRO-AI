-- Migration 99: authorized platform company/user search with filtered counts.
-- No customer rows or platform authority data are changed by this migration.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Substring search uses lower(column) LIKE '%term%'. These indexes support the
-- exact expressions below as the platform directory grows. Short terms remain
-- correct but PostgreSQL may choose a sequential scan when trigrams are not selective.
CREATE INDEX IF NOT EXISTS companies_platform_name_search_trgm_idx
    ON public.companies USING gin ((lower(coalesce(business_name, ''))) gin_trgm_ops)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS users_platform_name_search_trgm_idx
    ON public.users USING gin ((lower(coalesce(full_name, ''))) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS users_platform_email_search_trgm_idx
    ON public.users USING gin ((lower(coalesce(email, ''))) gin_trgm_ops);

CREATE OR REPLACE FUNCTION public.keel_platform_search(
    resource text,
    search_text text,
    result_limit integer,
    result_offset integer
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    actor uuid := nullif(current_setting('app.current_user_id', true), '')::uuid;
    actor_role text;
    query_text text := lower(btrim(coalesce(search_text, '')));
    like_pattern text;
    total_count bigint;
    rows jsonb;
BEGIN
    IF resource NOT IN ('companies', 'users') THEN
        RAISE EXCEPTION 'Unsupported platform search resource' USING ERRCODE = '22023';
    END IF;
    IF result_limit IS NULL OR result_limit < 1 OR result_limit > 100
       OR result_offset IS NULL OR result_offset < 0 OR result_offset > 1000000 THEN
        RAISE EXCEPTION 'Invalid platform search pagination' USING ERRCODE = '22023';
    END IF;
    IF length(query_text) > 200 THEN
        RAISE EXCEPTION 'Platform search term is too long' USING ERRCODE = '22023';
    END IF;

    -- Keep authorization and revocation serialized with other platform
    -- authority changes; no caller-supplied role or actor is trusted.
    PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority', 0));
    SELECT m.role_key INTO actor_role
      FROM public.keel_platform_members AS m
      JOIN public.users AS u USING (user_id)
     WHERE m.user_id = actor
       AND m.status = 'active'
       AND m.role_key IN ('owner', 'admin')
       AND u.platform_disabled_at IS NULL;

    IF actor_role IS NULL THEN
        INSERT INTO public.keel_platform_audit(actor_user_id, actor_role, action, subject, reason, outcome)
        VALUES (actor, NULL, 'platform_search', resource, 'Permission denied', 'denied');
        RETURN jsonb_build_object('error', 'forbidden');
    END IF;

    -- Escape LIKE metacharacters so '%' and '_' are treated as literal search
    -- characters rather than user-controlled wildcards. All values remain SQL
    -- variables; no request text is interpolated into SQL source.
    like_pattern := '%' || replace(replace(replace(query_text, E'\\', E'\\\\'), '%', E'\\%'), '_', E'\\_') || '%';

    IF resource = 'companies' THEN
        SELECT count(*) INTO total_count
          FROM public.companies AS c
         WHERE c.deleted_at IS NULL
           AND (query_text = '' OR lower(coalesce(c.business_name, '')) LIKE like_pattern ESCAPE E'\\');

        SELECT coalesce(jsonb_agg(
                   jsonb_build_object(
                       'tenant_id', p.tenant_id,
                       'business_name', p.business_name,
                       'country_code', p.country_code,
                       'primary_currency', p.primary_currency,
                       'platform_suspended_at', p.platform_suspended_at,
                       'platform_notes', p.platform_notes
                   ) ORDER BY p.created_at DESC, p.tenant_id DESC
               ), '[]'::jsonb)
          INTO rows
          FROM (
              SELECT c.tenant_id, c.business_name, c.country_code, c.primary_currency,
                     c.platform_suspended_at, c.platform_notes, c.created_at
                FROM public.companies AS c
               WHERE c.deleted_at IS NULL
                 AND (query_text = '' OR lower(coalesce(c.business_name, '')) LIKE like_pattern ESCAPE E'\\')
               ORDER BY c.created_at DESC, c.tenant_id DESC
               LIMIT result_limit OFFSET result_offset
          ) AS p;
    ELSE
        SELECT count(*) INTO total_count
          FROM public.users AS u
         WHERE query_text = ''
            OR lower(coalesce(u.full_name, '')) LIKE like_pattern ESCAPE E'\\'
            OR lower(coalesce(u.email, '')) LIKE like_pattern ESCAPE E'\\';

        SELECT coalesce(jsonb_agg(
                   jsonb_build_object(
                       'user_id', p.user_id,
                       'email', p.email,
                       'full_name', p.full_name,
                       'email_verified_at', p.email_verified_at,
                       'platform_disabled_at', p.platform_disabled_at
                   ) ORDER BY p.created_at DESC, p.user_id DESC
               ), '[]'::jsonb)
          INTO rows
          FROM (
              SELECT u.user_id, u.email, u.full_name, u.email_verified_at,
                     u.platform_disabled_at, u.created_at
                FROM public.users AS u
               WHERE query_text = ''
                  OR lower(coalesce(u.full_name, '')) LIKE like_pattern ESCAPE E'\\'
                  OR lower(coalesce(u.email, '')) LIKE like_pattern ESCAPE E'\\'
               ORDER BY u.created_at DESC, u.user_id DESC
               LIMIT result_limit OFFSET result_offset
          ) AS p;
    END IF;

    RETURN jsonb_build_object(
        'items', coalesce(rows, '[]'::jsonb),
        'total', total_count,
        'limit', result_limit,
        'offset', result_offset
    );
END;
$$;

REVOKE ALL ON FUNCTION public.keel_platform_search(text, text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_platform_search(text, text, integer, integer) TO ceopro_app;
