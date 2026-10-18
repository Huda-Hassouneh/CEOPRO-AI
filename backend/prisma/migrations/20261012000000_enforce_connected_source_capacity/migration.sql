-- Enforce source access, quota, and active-identity uniqueness for every
-- writer of data_sources, including the AI service's direct PostgreSQL path.
-- Node still performs the same checks to return localized API errors; this
-- trigger is the shared database boundary that prevents another writer from
-- bypassing them.

CREATE OR REPLACE FUNCTION public.connected_data_source_identity(
    p_source_type TEXT,
    p_source_name TEXT,
    p_source_url TEXT,
    p_collector_key TEXT,
    p_collector_config JSONB
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    SELECT lower(btrim(p_source_type)) || ':' || CASE
        WHEN upper(p_source_type) = 'OWN_SYSTEM_CONNECTOR'
             AND p_collector_key = 'db_connector' THEN
            'database:' || lower(btrim(coalesce(p_collector_config ->> 'host', ''))) || ':' ||
            coalesce(p_collector_config ->> 'port', '5432') || '/' ||
            btrim(coalesce(p_collector_config ->> 'dbname', ''))
        WHEN upper(p_source_type) = 'OWN_SYSTEM_CONNECTOR'
             AND p_collector_key = 'api_connector' THEN
            'api:' || regexp_replace(btrim(coalesce(p_collector_config ->> 'base_url', '')), '/+$', '')
        WHEN nullif(btrim(coalesce(p_source_url, '')), '') IS NOT NULL THEN
            'url:' || regexp_replace(btrim(p_source_url), '/+$', '')
        ELSE
            'name:' || regexp_replace(lower(btrim(coalesce(p_source_name, ''))), '\s+', ' ', 'g')
    END
$$;

CREATE OR REPLACE FUNCTION public.enforce_connected_data_source_capacity()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_source_type_is_counted BOOLEAN;
    v_was_counted BOOLEAN := FALSE;
    v_plan_id UUID;
    v_source_limit INTEGER;
    v_current_usage BIGINT;
    v_identity TEXT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_TENANT_IMMUTABLE'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' AND NEW.source_type IS DISTINCT FROM OLD.source_type THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_TYPE_IMMUTABLE'
            USING ERRCODE = '23514';
    END IF;

    v_source_type_is_counted := NEW.source_type IN (
        'shopify', 'postgresql', 'mysql', 'sqlserver', 'ga4', 'website',
        'OWN_SYSTEM_CONNECTOR'
    );

    IF TG_OP = 'UPDATE' THEN
        v_was_counted := OLD.is_active AND OLD.source_type IN (
            'shopify', 'postgresql', 'mysql', 'sqlserver', 'ga4', 'website',
            'OWN_SYSTEM_CONNECTOR'
        );
    END IF;

    IF NOT NEW.is_active OR NOT v_source_type_is_counted THEN
        RETURN NEW;
    END IF;

    -- Use the same transaction-scoped lock as the Node registration path so
    -- app and direct database writers cannot take the same remaining slot.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('connected-data-sources:' || NEW.tenant_id::TEXT, 0)
    );

    v_identity := public.connected_data_source_identity(
        NEW.source_type, NEW.source_name, NEW.source_url,
        NEW.collector_key, NEW.collector_config
    );

    IF EXISTS (
        SELECT 1
        FROM public.data_sources existing
        WHERE existing.tenant_id = NEW.tenant_id
          AND existing.is_active = TRUE
          AND existing.source_type IN (
              'shopify', 'postgresql', 'mysql', 'sqlserver', 'ga4', 'website',
              'OWN_SYSTEM_CONNECTOR'
          )
          AND existing.source_id <> NEW.source_id
          AND public.connected_data_source_identity(
              existing.source_type, existing.source_name, existing.source_url,
              existing.collector_key, existing.collector_config
          ) = v_identity
    ) THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_DUPLICATE'
            USING ERRCODE = '23505';
    END IF;

    -- Updates to an already-active source do not consume an additional slot.
    IF v_was_counted THEN
        RETURN NEW;
    END IF;

    -- Lock the chosen subscription row while reading its plan. A concurrent
    -- downgrade is therefore ordered before or after this registration.
    SELECT subscription.plan_id
      INTO v_plan_id
      FROM public.subscriptions AS subscription
     WHERE subscription.tenant_id = NEW.tenant_id
       AND subscription.status IN ('active', 'trialing')
     ORDER BY subscription.updated_at DESC, subscription.created_at DESC
     LIMIT 1
     FOR SHARE;

    IF v_plan_id IS NULL THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_SUBSCRIPTION_REQUIRED'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.plan_features AS plan_feature
          JOIN public.features AS feature
            ON feature.feature_id = plan_feature.feature_id
         WHERE plan_feature.plan_id = v_plan_id
           AND feature.feature_code = 'data_integration'
           AND feature.feature_type = 'boolean'
    ) THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_DATA_INTEGRATION_DISABLED'
            USING ERRCODE = '23514';
    END IF;

    SELECT plan_feature.limit_value
      INTO v_source_limit
      FROM public.plan_features AS plan_feature
      JOIN public.features AS feature
        ON feature.feature_id = plan_feature.feature_id
     WHERE plan_feature.plan_id = v_plan_id
       AND feature.feature_code = 'connected_data_sources'
       AND feature.feature_type = 'limit'
       AND feature.aggregation_type = 'max'
       AND feature.reset_cycle = 'lifetime';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_CAPACITY_NOT_CONFIGURED'
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*)
      INTO v_current_usage
      FROM public.data_sources AS existing
     WHERE existing.tenant_id = NEW.tenant_id
       AND existing.is_active = TRUE
       AND existing.source_type IN (
           'shopify', 'postgresql', 'mysql', 'sqlserver', 'ga4', 'website',
           'OWN_SYSTEM_CONNECTOR'
       )
       AND existing.source_id <> NEW.source_id;

    -- A NULL limit is the explicit unlimited entitlement for an accepted
    -- custom plan. A finite plan, including a zero-source plan, stays capped.
    IF v_source_limit IS NOT NULL AND v_current_usage + 1 > v_source_limit THEN
        RAISE EXCEPTION 'CONNECTED_SOURCE_CAPACITY_EXCEEDED'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS enforce_connected_data_source_capacity_trigger
    ON public.data_sources;

CREATE TRIGGER enforce_connected_data_source_capacity_trigger
    BEFORE INSERT OR UPDATE OF tenant_id, source_type, source_name, source_url,
        collector_key, collector_config, is_active
    ON public.data_sources
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_connected_data_source_capacity();

REVOKE ALL ON FUNCTION public.enforce_connected_data_source_capacity() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.connected_data_source_identity(TEXT, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC;
