-- Phase 3/4 provider lifecycle foundation (owner-approved O-IMPORT,
-- O-SOURCE, U6, and safe PRIVACY-001 intake). Migrations 1-93 are unchanged.
-- No provider payload, credential, canonical identity mapping, inventory
-- authority, privacy erasure, or accounting data is added here.

-- The receipt ID is globally unique already, but the provider checkpoint's
-- composite tenant FK also needs a matching key so tenant integrity is
-- enforced by PostgreSQL rather than only by application predicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_keel_operation_receipts_tenant_receipt
    ON public.keel_operation_receipts(tenant_id,receipt_id);

CREATE TABLE public.keel_provider_sources (
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('woocommerce','shopify')),
    verified_store_id TEXT NOT NULL CHECK (length(btrim(verified_store_id)) BETWEEN 1 AND 255),
    verified_store_domain TEXT NOT NULL CHECK (length(btrim(verified_store_domain)) BETWEEN 1 AND 255),
    identity_provenance TEXT NOT NULL CHECK (identity_provenance IN
        ('shopify_authenticated_shop_query','woocommerce_authenticated_store_identity')),
    verification_evidence JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(verification_evidence)='object' AND octet_length(verification_evidence::text) <= 8192),
    connection_state TEXT NOT NULL DEFAULT 'verified'
        CHECK (connection_state IN ('verified','verification_required','disabled','disconnected')),
    configuration_version BIGINT NOT NULL DEFAULT 1 CHECK (configuration_version > 0),
    credential_version BIGINT NOT NULL DEFAULT 1 CHECK (credential_version > 0),
    verified_at TIMESTAMPTZ NOT NULL,
    verified_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, source_id),
    CONSTRAINT fk_keel_provider_source_tenant FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_source_data_source FOREIGN KEY (tenant_id,source_id)
        REFERENCES public.data_sources(tenant_id,source_id) ON DELETE RESTRICT,
    CONSTRAINT uq_keel_provider_store_identity UNIQUE (tenant_id,provider,verified_store_id),
    CONSTRAINT ck_keel_provider_verification_shape CHECK (
        (provider='shopify' AND identity_provenance='shopify_authenticated_shop_query'
          AND verified_store_id ~ '^gid://shopify/Shop/[0-9]+$')
        OR
        (provider='woocommerce' AND identity_provenance='woocommerce_authenticated_store_identity')
    )
);
CREATE INDEX idx_keel_provider_sources_state ON public.keel_provider_sources(tenant_id,connection_state);

CREATE TABLE public.keel_provider_sync_checkpoints (
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    stream_key TEXT NOT NULL CHECK (length(btrim(stream_key)) BETWEEN 1 AND 100),
    continuation JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(continuation)='object' AND octet_length(continuation::text) <= 8192
        AND continuation - ARRAY['cursor','page','modified_since'] = '{}'::jsonb
        AND (NOT continuation ? 'cursor' OR jsonb_typeof(continuation->'cursor')='string')
        AND (NOT continuation ? 'page' OR jsonb_typeof(continuation->'page')='number')
        AND (NOT continuation ? 'modified_since' OR jsonb_typeof(continuation->'modified_since')='string')
    ),
    checkpoint_version BIGINT NOT NULL DEFAULT 0 CHECK (checkpoint_version >= 0),
    configuration_version BIGINT NOT NULL CHECK (configuration_version > 0),
    last_successful_at TIMESTAMPTZ,
    last_receipt_id UUID,
    last_lease_generation BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,source_id,stream_key),
    CONSTRAINT fk_keel_checkpoint_source FOREIGN KEY (tenant_id,source_id)
        REFERENCES public.keel_provider_sources(tenant_id,source_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_checkpoint_receipt FOREIGN KEY (tenant_id,last_receipt_id)
        REFERENCES public.keel_operation_receipts(tenant_id,receipt_id) ON DELETE RESTRICT,
    CONSTRAINT ck_keel_checkpoint_receipt_generation CHECK (
        (last_receipt_id IS NULL) = (last_lease_generation IS NULL)
    )
);

CREATE TABLE public.keel_provider_delivery_receipts (
    delivery_receipt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('woocommerce','shopify')),
    provider_delivery_id TEXT NOT NULL CHECK (length(btrim(provider_delivery_id)) BETWEEN 1 AND 255),
    event_type TEXT NOT NULL CHECK (length(btrim(event_type)) BETWEEN 1 AND 160),
    payload_sha256 CHAR(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    sanitized_metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(sanitized_metadata)='object' AND octet_length(sanitized_metadata::text) <= 8192
        AND sanitized_metadata - ARRAY['topic','provider_created_at','api_version','delivery_attempt'] = '{}'::jsonb
    ),
    authentication_method TEXT CHECK (authentication_method IS NULL OR authentication_method IN ('shopify_hmac_sha256','woocommerce_hmac_sha256')),
    signature_verified_at TIMESTAMPTZ,
    state TEXT NOT NULL DEFAULT 'received' CHECK (state IN
        ('received','authenticated','processing','reconciliation_required','processed','failed')),
    received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT fk_keel_delivery_tenant FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_delivery_source FOREIGN KEY (tenant_id,source_id)
        REFERENCES public.keel_provider_sources(tenant_id,source_id) ON DELETE RESTRICT,
    CONSTRAINT uq_keel_provider_delivery_identity UNIQUE (tenant_id,source_id,provider,provider_delivery_id),
    CONSTRAINT ck_keel_delivery_authentication CHECK (
        (state='received' AND signature_verified_at IS NULL AND authentication_method IS NULL)
        OR
        (state<>'received' AND signature_verified_at IS NOT NULL AND authentication_method IS NOT NULL)
    )
);
CREATE INDEX idx_keel_provider_deliveries_pending
    ON public.keel_provider_delivery_receipts(tenant_id,source_id,received_at)
    WHERE state IN ('authenticated','processing','reconciliation_required');

-- Runtime access is tenant-limited. Checkpoints and deliveries are written
-- through narrowly scoped command functions; provider source rows are
-- inserted/updated only by the verified registration service.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['keel_provider_sources','keel_provider_sync_checkpoints',
                              'keel_provider_delivery_receipts'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO ceopro_app USING (tenant_id=public.get_current_tenant())',
                       'isolation_'||t,t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
        EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app',t);
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.keel_provider_json_safe(p JSONB)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE PARALLEL SAFE
SET search_path=pg_catalog,public,pg_temp AS $$
    WITH RECURSIVE nodes(value) AS (
        SELECT coalesce(p,'{}'::jsonb)
        UNION ALL
        SELECT child.value FROM nodes n CROSS JOIN LATERAL (
            SELECT e.value FROM jsonb_each(CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END) e
            UNION ALL SELECT a.value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value)='array' THEN n.value ELSE '[]'::jsonb END) a
        ) child
    ), keys AS (
        SELECT k.key FROM nodes n CROSS JOIN LATERAL jsonb_object_keys(
            CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END) k(key)
    )
    SELECT NOT EXISTS(SELECT 1 FROM keys WHERE key ~* '(secret|password|authorization|cookie|access[_-]?token|refresh[_-]?token|api[_-]?key|credential)')
$$;
REVOKE ALL ON FUNCTION public.keel_provider_json_safe(JSONB) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.keel_provider_source_command(p_action TEXT,p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
    tid UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
    actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
    src UUID:=nullif(p->>'source_id','')::uuid;
    prov TEXT:=p->>'provider';
    store_id TEXT:=p->>'verified_store_id';
    store_domain TEXT:=p->>'verified_store_domain';
    provenance TEXT:=p->>'identity_provenance';
    evidence JSONB:=coalesce(p->'verification_evidence','{}'::jsonb);
    existing public.keel_provider_sources%ROWTYPE;
BEGIN
    IF tid IS NULL OR actor IS NULL OR public.get_current_tenant() IS DISTINCT FROM tid
       OR NOT public.keel_active_principal(actor,tid) THEN
        RAISE EXCEPTION 'active tenant principal required' USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM public.tenant_users tu WHERE tu.tenant_id=tid AND tu.user_id=actor
         AND lower(tu.role_key) IN ('owner','admin') AND tu.removed_at IS NULL
         AND tu.platform_suspended_at IS NULL) THEN
        RAISE EXCEPTION 'tenant owner or admin role required for provider lifecycle changes' USING ERRCODE='42501';
    END IF;
    IF NOT public.keel_provider_json_safe(evidence) THEN
        RAISE EXCEPTION 'sensitive verification evidence is not permitted' USING ERRCODE='22023';
    END IF;
    IF p_action='bind_verified' THEN
        IF prov NOT IN ('woocommerce','shopify') OR src IS NULL OR store_id IS NULL OR store_domain IS NULL
           OR provenance IS NULL OR p->>'verified' IS DISTINCT FROM 'true' THEN
            RAISE EXCEPTION 'verified provider identity required' USING ERRCODE='22023';
        END IF;
        PERFORM 1 FROM public.data_sources ds WHERE ds.tenant_id=tid AND ds.source_id=src
          AND ds.source_type='OWN_SYSTEM_CONNECTOR' AND ds.collector_key=prov AND ds.is_active IS TRUE FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'active tenant source required' USING ERRCODE='42501'; END IF;
        SELECT * INTO existing FROM public.keel_provider_sources
          WHERE tenant_id=tid AND provider=prov AND verified_store_id=store_id FOR UPDATE;
        IF FOUND THEN
            IF existing.source_id<>src THEN
                RAISE EXCEPTION 'verified provider store is already bound to another logical source' USING ERRCODE='23505';
            END IF;
            UPDATE public.keel_provider_sources SET connection_state='verified',
                verified_store_domain=store_domain,identity_provenance=provenance,
                verification_evidence=evidence,verified_at=clock_timestamp(),verified_by_user_id=actor,
                configuration_version=configuration_version+1,updated_at=clock_timestamp()
              WHERE tenant_id=tid AND source_id=src AND provider=prov;
            INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
            VALUES(tid,actor,'PROVIDER_SOURCE_RECONNECTED','keel_provider_sources',src,
                jsonb_build_object('provider',prov,'verified_store_id',store_id,'identity_provenance',provenance));
            RETURN jsonb_build_object('source_id',src,'reconnected',true);
        END IF;
        INSERT INTO public.keel_provider_sources(tenant_id,source_id,provider,verified_store_id,
            verified_store_domain,identity_provenance,verification_evidence,verified_at,verified_by_user_id)
        VALUES(tid,src,prov,store_id,store_domain,provenance,evidence,clock_timestamp(),actor);
        INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
        VALUES(tid,actor,'PROVIDER_SOURCE_BOUND','keel_provider_sources',src,
            jsonb_build_object('provider',prov,'verified_store_id',store_id,'identity_provenance',provenance));
        RETURN jsonb_build_object('source_id',src,'reconnected',false);
    ELSIF p_action='disable' THEN
        UPDATE public.keel_provider_sources SET connection_state='disabled',configuration_version=configuration_version+1,
            updated_at=clock_timestamp() WHERE tenant_id=tid AND source_id=src AND provider=prov;
        IF NOT FOUND THEN RAISE EXCEPTION 'verified provider source not found' USING ERRCODE='P0002'; END IF;
        INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
        VALUES(tid,actor,'PROVIDER_SOURCE_DISABLED','keel_provider_sources',src,jsonb_build_object('provider',prov));
        RETURN jsonb_build_object('source_id',src,'disabled',true);
    ELSIF p_action='mark_verification_required' THEN
        UPDATE public.keel_provider_sources SET connection_state='verification_required',
            credential_version=credential_version+1,updated_at=clock_timestamp()
          WHERE tenant_id=tid AND source_id=src AND provider=prov;
        IF NOT FOUND THEN RAISE EXCEPTION 'verified provider source not found' USING ERRCODE='P0002'; END IF;
        INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
        VALUES(tid,actor,'PROVIDER_SOURCE_VERIFICATION_REQUIRED','keel_provider_sources',src,jsonb_build_object('provider',prov));
        RETURN jsonb_build_object('source_id',src,'verification_required',true);
    END IF;
    RAISE EXCEPTION 'unsupported provider source command' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_source_command(TEXT,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_source_command(TEXT,JSONB) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_provider_source_fence_trigger()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
    IF OLD.is_active IS DISTINCT FROM NEW.is_active
       OR OLD.collector_config IS DISTINCT FROM NEW.collector_config
       OR OLD.connection_credentials_vault IS DISTINCT FROM NEW.connection_credentials_vault THEN
        UPDATE public.keel_provider_sources p SET
            connection_state=CASE WHEN NEW.is_active IS FALSE THEN 'disabled' ELSE 'verification_required' END,
            configuration_version=p.configuration_version+1,
            credential_version=p.credential_version+CASE
                WHEN OLD.connection_credentials_vault IS DISTINCT FROM NEW.connection_credentials_vault THEN 1 ELSE 0 END,
            updated_at=clock_timestamp()
         WHERE p.tenant_id=NEW.tenant_id AND p.source_id=NEW.source_id;
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_source_fence_trigger() FROM PUBLIC;
DROP TRIGGER IF EXISTS data_sources_keel_provider_fence ON public.data_sources;
CREATE TRIGGER data_sources_keel_provider_fence
    AFTER UPDATE OF is_active,collector_config,connection_credentials_vault ON public.data_sources
    FOR EACH ROW EXECUTE FUNCTION public.keel_provider_source_fence_trigger();

CREATE OR REPLACE FUNCTION public.keel_provider_checkpoint_advance(
    p_tenant UUID,p_source UUID,p_stream TEXT,p_continuation JSONB,
    p_receipt UUID,p_job UUID,p_lease_generation BIGINT,p_configuration_version BIGINT
) RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE next_version BIGINT; previous public.keel_provider_sync_checkpoints%ROWTYPE;
BEGIN
    IF public.get_current_tenant() IS DISTINCT FROM p_tenant THEN RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE='42501'; END IF;
    IF NOT public.keel_provider_json_safe(p_continuation)
       OR jsonb_typeof(p_continuation)<>'object'
       OR p_continuation-ARRAY['cursor','page','modified_since']<>'{}'::jsonb THEN
        RAISE EXCEPTION 'invalid or sensitive checkpoint data' USING ERRCODE='22023';
    END IF;
    PERFORM 1 FROM public.keel_operation_receipts r JOIN public.keel_provider_sources s
      ON s.tenant_id=r.tenant_id AND s.source_id=r.target_id
      JOIN public.ingestion_jobs j ON j.tenant_id=r.tenant_id AND j.job_id=r.ingestion_job_id
     WHERE r.tenant_id=p_tenant AND r.receipt_id=p_receipt AND r.operation_type='scheduled_connector_sync'
       AND r.target_kind='source' AND r.target_id=p_source AND r.state='provider_started'
       AND r.ingestion_job_id=p_job AND j.job_status='COMPLETED' AND j.source_id=p_source
       AND r.lease_generation=p_lease_generation AND r.lease_owner IS NOT NULL AND r.lease_expires_at>clock_timestamp()
       AND s.connection_state='verified' AND s.configuration_version=p_configuration_version
     FOR UPDATE OF r,s;
    IF NOT FOUND THEN RAISE EXCEPTION 'provider checkpoint rejected by source or receipt fence' USING ERRCODE='42501'; END IF;
    SELECT * INTO previous FROM public.keel_provider_sync_checkpoints
      WHERE tenant_id=p_tenant AND source_id=p_source AND stream_key=p_stream FOR UPDATE;
    IF FOUND AND previous.last_receipt_id=p_receipt AND previous.last_lease_generation=p_lease_generation THEN
        IF previous.continuation=p_continuation AND previous.configuration_version=p_configuration_version THEN
            RETURN previous.checkpoint_version;
        END IF;
        RAISE EXCEPTION 'same receipt cannot change a committed checkpoint' USING ERRCODE='23514';
    END IF;
    INSERT INTO public.keel_provider_sync_checkpoints(tenant_id,source_id,stream_key,continuation,
        checkpoint_version,configuration_version,last_successful_at,last_receipt_id,last_lease_generation)
    VALUES(p_tenant,p_source,p_stream,p_continuation,1,p_configuration_version,clock_timestamp(),p_receipt,p_lease_generation)
    ON CONFLICT(tenant_id,source_id,stream_key) DO UPDATE SET continuation=EXCLUDED.continuation,
        checkpoint_version=public.keel_provider_sync_checkpoints.checkpoint_version+1,
        configuration_version=EXCLUDED.configuration_version,last_successful_at=EXCLUDED.last_successful_at,
        last_receipt_id=EXCLUDED.last_receipt_id,last_lease_generation=EXCLUDED.last_lease_generation,
        updated_at=clock_timestamp()
    WHERE EXCLUDED.configuration_version>=public.keel_provider_sync_checkpoints.configuration_version
      AND (public.keel_provider_sync_checkpoints.last_successful_at IS NULL
        OR EXCLUDED.last_successful_at>=public.keel_provider_sync_checkpoints.last_successful_at)
    RETURNING checkpoint_version INTO next_version;
    IF next_version IS NULL THEN RAISE EXCEPTION 'checkpoint update is stale' USING ERRCODE='40001'; END IF;
    RETURN next_version;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_checkpoint_advance(UUID,UUID,TEXT,JSONB,UUID,UUID,BIGINT,BIGINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_checkpoint_advance(UUID,UUID,TEXT,JSONB,UUID,UUID,BIGINT,BIGINT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_provider_delivery_record(
    p_source UUID,p_provider TEXT,p_delivery_id TEXT,p_event_type TEXT,p_payload_sha256 TEXT,
    p_metadata JSONB,p_auth_method TEXT,p_authenticated BOOLEAN
) RETURNS TABLE(delivery_receipt_id UUID,was_duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); new_id UUID; inserted BOOLEAN;
        existing_hash TEXT; existing_type TEXT;
BEGIN
    IF tid IS NULL THEN RAISE EXCEPTION 'active tenant context required' USING ERRCODE='42501'; END IF;
    IF NOT p_authenticated OR p_auth_method NOT IN ('shopify_hmac_sha256','woocommerce_hmac_sha256')
      OR p_payload_sha256 !~ '^[0-9a-f]{64}$' OR NOT public.keel_provider_json_safe(p_metadata)
      OR jsonb_typeof(p_metadata)<>'object' OR octet_length(p_metadata::text)>8192 THEN
        RAISE EXCEPTION 'authenticated sanitized provider delivery required' USING ERRCODE='22023';
    END IF;
    PERFORM 1 FROM public.keel_provider_sources WHERE tenant_id=tid AND source_id=p_source
      AND provider=p_provider AND connection_state IN ('verified','disabled','verification_required') FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'provider delivery source attribution failed' USING ERRCODE='42501'; END IF;
    INSERT INTO public.keel_provider_delivery_receipts(tenant_id,source_id,provider,provider_delivery_id,
      event_type,payload_sha256,sanitized_metadata,authentication_method,signature_verified_at,state)
    VALUES(tid,p_source,p_provider,p_delivery_id,p_event_type,p_payload_sha256,p_metadata,p_auth_method,
      clock_timestamp(),'authenticated') ON CONFLICT(tenant_id,source_id,provider,provider_delivery_id) DO NOTHING
    RETURNING keel_provider_delivery_receipts.delivery_receipt_id INTO new_id;
    inserted:=new_id IS NOT NULL;
    IF NOT inserted THEN
      SELECT d.delivery_receipt_id,d.payload_sha256,d.event_type INTO new_id,existing_hash,existing_type
        FROM public.keel_provider_delivery_receipts d
       WHERE d.tenant_id=tid AND d.source_id=p_source AND d.provider=p_provider AND d.provider_delivery_id=p_delivery_id;
      IF existing_hash<>p_payload_sha256 OR existing_type<>p_event_type THEN
        RAISE EXCEPTION 'provider delivery identity was replayed with different content' USING ERRCODE='23505';
      END IF;
    END IF;
    RETURN QUERY SELECT new_id,NOT inserted;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_delivery_record(UUID,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_delivery_record(UUID,TEXT,TEXT,TEXT,TEXT,JSONB,TEXT,BOOLEAN) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_provider_delivery_transition(p_id UUID,p_state TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); changed INTEGER;
BEGIN
    IF tid IS NULL OR p_state NOT IN ('processing','reconciliation_required','processed','failed') THEN
        RAISE EXCEPTION 'invalid provider delivery transition' USING ERRCODE='42501';
    END IF;
    UPDATE public.keel_provider_delivery_receipts SET state=p_state,updated_at=clock_timestamp()
     WHERE tenant_id=tid AND delivery_receipt_id=p_id AND signature_verified_at IS NOT NULL
       AND (
          (state='authenticated' AND p_state IN ('processing','reconciliation_required','failed'))
          OR (state='processing' AND p_state IN ('reconciliation_required','processed','failed'))
          OR (state='reconciliation_required' AND p_state IN ('processing','processed','failed'))
       );
    GET DIAGNOSTICS changed=ROW_COUNT;
    RETURN changed=1;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_delivery_transition(UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_delivery_transition(UUID,TEXT) TO ceopro_app;

-- Existing source soft-disconnect remains the supported lifecycle operation.
-- Hard tenant/source deletion is intentionally restricted while evidence exists.
