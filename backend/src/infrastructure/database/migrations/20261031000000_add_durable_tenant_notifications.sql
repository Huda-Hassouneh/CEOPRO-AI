-- Durable tenant in-app notifications (Migration 103).
-- One committed row is immediately visible in the inbox; no delivery worker
-- is required for an in-app database write. External channels remain out of
-- scope. Existing derived Smart Alerts and email digests are unchanged.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keel_notification_fn_owner') THEN
        CREATE ROLE keel_notification_fn_owner
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$roles$;

ALTER ROLE keel_notification_fn_owner
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO keel_notification_fn_owner;
GRANT CREATE ON SCHEMA public TO keel_notification_fn_owner;
GRANT SELECT ON public.tenant_users, public.users TO keel_notification_fn_owner;

CREATE TABLE public.notification_outbox (
    notification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    recipient_user_id uuid NOT NULL,
    event_key text NOT NULL
        CHECK (event_key ~ '^[a-z][a-z0-9_.-]{0,31}:[A-Za-z0-9._:-]{1,160}$'),
    event_kind text NOT NULL CHECK (event_kind IN (
        'restock','competitor_price','price_gap','competitor_comments_negative',
        'new_competitors','import_failed','payment_failed','trial_ending',
        'credits_low','credits_exhausted'
    )),
    category text NOT NULL CHECK (category IN ('stock','pricing','market','data','billing')),
    severity text NOT NULL CHECK (severity IN ('info','warning','danger')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384),
    source_type text,
    source_id text,
    CONSTRAINT chk_notification_source_bounds CHECK (
        (source_type IS NULL OR octet_length(source_type) <= 64)
        AND (source_id IS NULL OR octet_length(source_id) <= 160)
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    dismissed_at timestamptz,
    CONSTRAINT uq_notification_source_recipient
        UNIQUE (tenant_id, event_key, recipient_user_id),
    CONSTRAINT fk_notification_tenant_membership
        FOREIGN KEY (tenant_id, recipient_user_id)
        REFERENCES public.tenant_users(tenant_id, user_id) ON DELETE RESTRICT
);

CREATE INDEX ix_notification_inbox
    ON public.notification_outbox
       (tenant_id, recipient_user_id, created_at DESC, notification_id DESC)
    WHERE dismissed_at IS NULL;
CREATE INDEX ix_notification_unread
    ON public.notification_outbox
       (tenant_id, recipient_user_id, created_at DESC)
    WHERE read_at IS NULL AND dismissed_at IS NULL;

ALTER TABLE public.notification_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_users FORCE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users FORCE ROW LEVEL SECURITY;

CREATE POLICY notification_fn_tenant_read
    ON public.tenant_users FOR SELECT TO keel_notification_fn_owner
    USING (tenant_id = public.get_current_tenant());
CREATE POLICY notification_fn_user_read
    ON public.users FOR SELECT TO keel_notification_fn_owner
    USING (EXISTS (
        SELECT 1 FROM public.tenant_users tu
        WHERE tu.tenant_id = public.get_current_tenant()
          AND tu.user_id = users.user_id
          AND tu.removed_at IS NULL
          AND tu.platform_suspended_at IS NULL
    ));
CREATE POLICY notification_fn_row_access
    ON public.notification_outbox FOR ALL TO keel_notification_fn_owner
    USING (tenant_id = public.get_current_tenant())
    WITH CHECK (tenant_id = public.get_current_tenant());

REVOKE ALL ON public.notification_outbox FROM PUBLIC, ceopro_app;
GRANT SELECT, INSERT, UPDATE ON public.notification_outbox TO keel_notification_fn_owner;
REVOKE ALL ON public.tenant_users, public.users FROM keel_notification_fn_owner;
GRANT SELECT ON public.tenant_users, public.users TO keel_notification_fn_owner;
GRANT EXECUTE ON FUNCTION public.get_current_tenant() TO keel_notification_fn_owner;
GRANT EXECUTE ON FUNCTION public.keel_active_principal(uuid, uuid) TO keel_notification_fn_owner;

-- Enqueue is restricted to the trusted application DB role and its verified
-- active principal. This function only permits self-targeting; tenant-wide
-- event fan-out is handled by trusted database triggers in the source transaction.
CREATE FUNCTION public.enqueue_tenant_notification(
    p_tenant_id uuid, p_recipient_user_id uuid, p_event_key text,
    p_event_kind text, p_category text, p_severity text, p_payload jsonb,
    p_source_type text DEFAULT NULL, p_source_id text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE
    v_actor uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
    v_id uuid;
    v_allowed boolean;
BEGIN
    IF session_user <> 'ceopro_app' THEN
        RAISE EXCEPTION 'notification producer is not authorized' USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id IS NULL OR p_recipient_user_id IS NULL
       OR p_tenant_id IS DISTINCT FROM public.get_current_tenant()
       OR v_actor IS NULL OR v_actor = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_recipient_user_id IS DISTINCT FROM v_actor
       OR NOT public.keel_active_principal(v_actor, p_tenant_id) THEN
        RAISE EXCEPTION 'notification tenant context is not authorized' USING ERRCODE = '42501';
    END IF;
    IF p_event_key IS NULL OR p_event_key !~ '^[a-z][a-z0-9_.-]{0,31}:[A-Za-z0-9._:-]{1,160}$'
       OR p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object'
       OR octet_length(p_payload::text) > 16384
       OR p_category NOT IN ('stock','pricing','market','data','billing')
       OR p_severity IS NULL OR p_severity NOT IN ('info','warning','danger')
       OR (p_source_type IS NOT NULL AND octet_length(p_source_type) > 64)
       OR (p_source_id IS NOT NULL AND octet_length(p_source_id) > 160) THEN
        RAISE EXCEPTION 'notification payload or identity is invalid' USING ERRCODE = '22023';
    END IF;
    v_allowed := CASE p_event_kind
        WHEN 'restock' THEN p_category = 'stock'
        WHEN 'competitor_price' THEN p_category = 'pricing'
        WHEN 'price_gap' THEN p_category = 'pricing'
        WHEN 'competitor_comments_negative' THEN p_category = 'market'
        WHEN 'new_competitors' THEN p_category = 'market'
        WHEN 'import_failed' THEN p_category = 'data'
        WHEN 'payment_failed' THEN p_category = 'billing'
        WHEN 'trial_ending' THEN p_category = 'billing'
        WHEN 'credits_low' THEN p_category = 'billing'
        WHEN 'credits_exhausted' THEN p_category = 'billing'
        ELSE false
    END;
    IF NOT COALESCE(v_allowed, false) THEN
        RAISE EXCEPTION 'notification kind/category is unsupported' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.tenant_users tu
        JOIN public.users u ON u.user_id = tu.user_id
        WHERE tu.tenant_id = p_tenant_id
          AND tu.user_id = p_recipient_user_id
          AND tu.removed_at IS NULL
          AND tu.platform_suspended_at IS NULL
          AND u.platform_disabled_at IS NULL
    ) THEN
        RAISE EXCEPTION 'notification recipient is not an active tenant member' USING ERRCODE = '42501';
    END IF;
    SELECT NOT (
        jsonb_typeof(u.notification_preferences #> ARRAY['in_app', p_category]) = 'boolean'
        AND u.notification_preferences #>> ARRAY['in_app', p_category] = 'false'
    ) INTO v_allowed
    FROM public.users u WHERE u.user_id = p_recipient_user_id;
    IF NOT COALESCE(v_allowed, true) THEN
        RETURN NULL;
    END IF;

    INSERT INTO public.notification_outbox
        (tenant_id, recipient_user_id, event_key, event_kind, category,
         severity, payload, source_type, source_id)
    VALUES
        (p_tenant_id, p_recipient_user_id, p_event_key, p_event_kind, p_category,
         p_severity, p_payload, p_source_type, p_source_id)
    ON CONFLICT (tenant_id, event_key, recipient_user_id) DO NOTHING
    RETURNING notification_id INTO v_id;
    IF v_id IS NULL THEN
        SELECT n.notification_id INTO v_id
        FROM public.notification_outbox n
        WHERE n.tenant_id = p_tenant_id AND n.event_key = p_event_key
          AND n.recipient_user_id = p_recipient_user_id;
    END IF;
    RETURN v_id;
END
$fn$;

-- Inbox reads are bounded and keyset-paginated. The JSON response contains
-- only recipient-safe fields and counts; no database diagnostic/worker state.
CREATE FUNCTION public.list_tenant_notifications(
    p_tenant_id uuid, p_limit integer DEFAULT 20,
    p_before_created_at timestamptz DEFAULT NULL,
    p_before_notification_id uuid DEFAULT NULL,
    p_include_dismissed boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $fn$
DECLARE
    v_user uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
    v_items jsonb;
    v_total bigint;
    v_unread bigint;
    v_tenant uuid := public.get_current_tenant();
BEGIN
    IF session_user <> 'ceopro_app' OR p_tenant_id IS DISTINCT FROM v_tenant
       OR v_user IS NULL OR NOT public.keel_active_principal(v_user, p_tenant_id) THEN
        RAISE EXCEPTION 'notification access is not authorized' USING ERRCODE = '42501';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100
       OR ((p_before_created_at IS NULL) <> (p_before_notification_id IS NULL)) THEN
        RAISE EXCEPTION 'notification pagination is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT count(*) INTO v_total FROM public.notification_outbox n
     WHERE n.tenant_id = p_tenant_id AND n.recipient_user_id = v_user
       AND (p_include_dismissed OR n.dismissed_at IS NULL);
    SELECT count(*) INTO v_unread FROM public.notification_outbox n
     WHERE n.tenant_id = p_tenant_id AND n.recipient_user_id = v_user
       AND n.read_at IS NULL AND n.dismissed_at IS NULL;
    SELECT COALESCE(jsonb_agg(to_jsonb(page_row) ORDER BY page_row.created_at DESC, page_row.notification_id DESC), '[]'::jsonb)
      INTO v_items
      FROM (
        SELECT n.notification_id, n.event_key, n.event_kind, n.category, n.severity,
               n.payload, n.source_type, n.source_id, n.created_at, n.read_at, n.dismissed_at
        FROM public.notification_outbox n
        WHERE n.tenant_id = p_tenant_id AND n.recipient_user_id = v_user
          AND (p_include_dismissed OR n.dismissed_at IS NULL)
          AND (p_before_created_at IS NULL OR
               (n.created_at, n.notification_id) < (p_before_created_at, p_before_notification_id))
        ORDER BY n.created_at DESC, n.notification_id DESC
        LIMIT p_limit
      ) page_row;
    RETURN jsonb_build_object('items', v_items, 'total', v_total, 'unread_count', v_unread,
        'limit', p_limit,
        'next_cursor', CASE WHEN jsonb_array_length(v_items) = p_limit THEN
            jsonb_build_object('created_at', v_items->(p_limit - 1)->>'created_at',
                               'notification_id', v_items->(p_limit - 1)->>'notification_id')
            ELSE NULL END);
END
$fn$;

CREATE FUNCTION public.mark_tenant_notification_read(p_tenant_id uuid, p_notification_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_user uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
BEGIN
    IF session_user <> 'ceopro_app' OR p_tenant_id IS DISTINCT FROM public.get_current_tenant()
       OR v_user IS NULL OR NOT public.keel_active_principal(v_user, p_tenant_id) THEN
        RAISE EXCEPTION 'notification access is not authorized' USING ERRCODE = '42501';
    END IF;
    UPDATE public.notification_outbox SET read_at = COALESCE(read_at, now())
     WHERE tenant_id = p_tenant_id AND recipient_user_id = v_user
       AND notification_id = p_notification_id AND dismissed_at IS NULL;
    RETURN FOUND;
END
$fn$;

CREATE FUNCTION public.mark_all_tenant_notifications_read(p_tenant_id uuid)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_user uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
        v_count integer;
BEGIN
    IF session_user <> 'ceopro_app' OR p_tenant_id IS DISTINCT FROM public.get_current_tenant()
       OR v_user IS NULL OR NOT public.keel_active_principal(v_user, p_tenant_id) THEN
        RAISE EXCEPTION 'notification access is not authorized' USING ERRCODE = '42501';
    END IF;
    UPDATE public.notification_outbox SET read_at = now()
     WHERE tenant_id = p_tenant_id AND recipient_user_id = v_user
       AND read_at IS NULL AND dismissed_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END
$fn$;

CREATE FUNCTION public.dismiss_tenant_notification(p_tenant_id uuid, p_notification_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_user uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
BEGIN
    IF session_user <> 'ceopro_app' OR p_tenant_id IS DISTINCT FROM public.get_current_tenant()
       OR v_user IS NULL OR NOT public.keel_active_principal(v_user, p_tenant_id) THEN
        RAISE EXCEPTION 'notification access is not authorized' USING ERRCODE = '42501';
    END IF;
    UPDATE public.notification_outbox
       SET dismissed_at = COALESCE(dismissed_at, now()), read_at = COALESCE(read_at, now())
     WHERE tenant_id = p_tenant_id AND recipient_user_id = v_user
       AND notification_id = p_notification_id;
    RETURN FOUND;
END
$fn$;

CREATE FUNCTION public.notification_existing_event_keys(p_tenant_id uuid, p_event_keys text[])
RETURNS text[] LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_user uuid := NULLIF(current_setting('app.current_user_id', true), '')::uuid;
        v_keys text[];
BEGIN
    IF session_user <> 'ceopro_app' OR p_tenant_id IS DISTINCT FROM public.get_current_tenant()
       OR v_user IS NULL OR NOT public.keel_active_principal(v_user, p_tenant_id) THEN
        RAISE EXCEPTION 'notification access is not authorized' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(cardinality(p_event_keys), 0) > 100 THEN
        RAISE EXCEPTION 'too many notification keys' USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(array_agg(n.event_key), ARRAY[]::text[]) INTO v_keys
      FROM public.notification_outbox n
     WHERE n.tenant_id = p_tenant_id AND n.recipient_user_id = v_user
       AND n.event_key = ANY(COALESCE(p_event_keys, ARRAY[]::text[]));
    RETURN v_keys;
END
$fn$;

-- Capture the existing import-failed signal on the same transaction that
-- changes ingestion_jobs to FAILED. Repeated failure updates are deduped.
CREATE FUNCTION public.notify_ingestion_job_failure()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE v_old_tenant text := COALESCE(current_setting('app.current_tenant_id', true), '');
        v_old_user text := COALESCE(current_setting('app.current_user_id', true), '');
        v_member record;
BEGIN
    PERFORM set_config('app.current_tenant_id', NEW.tenant_id::text, true);
    PERFORM set_config('app.current_user_id', '00000000-0000-0000-0000-000000000000', true);
    FOR v_member IN
        SELECT tu.user_id
        FROM public.tenant_users tu
        JOIN public.users u ON u.user_id = tu.user_id
        WHERE tu.tenant_id = NEW.tenant_id
          AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL
          AND u.platform_disabled_at IS NULL
          AND NOT COALESCE(
            jsonb_typeof(u.notification_preferences #> '{in_app,data}') = 'boolean'
            AND u.notification_preferences #>> '{in_app,data}' = 'false',
            false
          )
    LOOP
        INSERT INTO public.notification_outbox
            (tenant_id, recipient_user_id, event_key, event_kind, category,
             severity, payload, source_type, source_id)
        VALUES
            (NEW.tenant_id, v_member.user_id, 'import:failed:' || NEW.job_id::text,
             'import_failed', 'data', 'danger',
             jsonb_build_object('params', jsonb_build_object('name', left(COALESCE(NEW.file_name, ''), 255)),
                                'link', '/connect-data'),
             'ingestion_job', NEW.job_id::text)
        ON CONFLICT (tenant_id, event_key, recipient_user_id) DO NOTHING;
    END LOOP;
    PERFORM set_config('app.current_tenant_id', v_old_tenant, true);
    PERFORM set_config('app.current_user_id', v_old_user, true);
    RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_notify_ingestion_job_failure
AFTER UPDATE OF job_status ON public.ingestion_jobs
FOR EACH ROW WHEN (OLD.job_status IS DISTINCT FROM NEW.job_status AND NEW.job_status = 'FAILED')
EXECUTE FUNCTION public.notify_ingestion_job_failure();

-- Transfer all definer functions to the non-login, non-BYPASSRLS owner.
ALTER FUNCTION public.enqueue_tenant_notification(uuid,uuid,text,text,text,text,jsonb,text,text) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.list_tenant_notifications(uuid,integer,timestamptz,uuid,boolean) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.mark_tenant_notification_read(uuid,uuid) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.mark_all_tenant_notifications_read(uuid) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.dismiss_tenant_notification(uuid,uuid) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.notification_existing_event_keys(uuid,text[]) OWNER TO keel_notification_fn_owner;
ALTER FUNCTION public.notify_ingestion_job_failure() OWNER TO keel_notification_fn_owner;
REVOKE CREATE ON SCHEMA public FROM keel_notification_fn_owner;

REVOKE ALL ON FUNCTION public.enqueue_tenant_notification(uuid,uuid,text,text,text,text,jsonb,text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_tenant_notifications(uuid,integer,timestamptz,uuid,boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_tenant_notification_read(uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_all_tenant_notifications_read(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.dismiss_tenant_notification(uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notification_existing_event_keys(uuid,text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notify_ingestion_job_failure() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.enqueue_tenant_notification(uuid,uuid,text,text,text,text,jsonb,text,text) TO ceopro_app;
GRANT EXECUTE ON FUNCTION public.list_tenant_notifications(uuid,integer,timestamptz,uuid,boolean) TO ceopro_app;
GRANT EXECUTE ON FUNCTION public.mark_tenant_notification_read(uuid,uuid) TO ceopro_app;
GRANT EXECUTE ON FUNCTION public.mark_all_tenant_notifications_read(uuid) TO ceopro_app;
GRANT EXECUTE ON FUNCTION public.dismiss_tenant_notification(uuid,uuid) TO ceopro_app;
GRANT EXECUTE ON FUNCTION public.notification_existing_event_keys(uuid,text[]) TO ceopro_app;

COMMENT ON TABLE public.notification_outbox IS
    'Durable tenant in-app inbox. Rows are inserted transactionally and visible immediately; no async delivery worker or automatic purge.';
