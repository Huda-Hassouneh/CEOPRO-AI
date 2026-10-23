-- Migration 96: source-owned inventory evidence and explicit authority selection.
-- Owner approved O-SOURCE scope on 2026-10-21. Migrations 1-95 are immutable.
-- This migration stores observations and decisions only; it never mutates canonical stock.

CREATE TABLE public.keel_inventory_locations (
    tenant_id UUID NOT NULL,
    canonical_location_id UUID NOT NULL DEFAULT gen_random_uuid(),
    location_key TEXT NOT NULL CHECK (length(btrim(location_key)) BETWEEN 1 AND 160),
    display_name TEXT NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    created_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, canonical_location_id),
    CONSTRAINT uq_keel_inventory_location_key96 UNIQUE (tenant_id, location_key),
    CONSTRAINT fk_keel_inventory_location_tenant96 FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_location_actor96 FOREIGN KEY (created_by_user_id)
        REFERENCES public.users(user_id) ON DELETE RESTRICT
);

CREATE TABLE public.keel_provider_inventory_locations (
    tenant_id UUID NOT NULL,
    provider_location_identity_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider='shopify'),
    provider_location_id TEXT NOT NULL CHECK (provider_location_id ~ '^gid://shopify/Location/[0-9]+$'),
    first_verified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, provider_location_identity_id),
    CONSTRAINT uq_keel_provider_location_namespace96 UNIQUE (tenant_id,source_id,provider,provider_location_id),
    CONSTRAINT uq_keel_provider_location_source_id96 UNIQUE (tenant_id,source_id,provider,provider_location_identity_id),
    CONSTRAINT fk_keel_provider_location_source96 FOREIGN KEY (tenant_id,source_id,provider)
        REFERENCES public.keel_provider_sources(tenant_id,source_id,provider) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_location_tenant96 FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT
);

CREATE TABLE public.keel_provider_inventory_location_observations (
    tenant_id UUID NOT NULL,
    location_observation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL,
    provider_location_identity_id UUID NOT NULL,
    display_name TEXT NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    provider_active BOOLEAN,
    provider_revision TEXT CHECK (provider_revision IS NULL OR length(provider_revision)<=255),
    provider_updated_at TIMESTAMPTZ,
    observation_sha256 CHAR(64) NOT NULL CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,location_observation_id),
    CONSTRAINT uq_keel_provider_location_observation96 UNIQUE (tenant_id,source_id,provider_location_identity_id,observation_sha256),
    CONSTRAINT fk_keel_provider_location_observation_identity96 FOREIGN KEY (tenant_id,source_id,provider,provider_location_identity_id)
        REFERENCES public.keel_provider_inventory_locations(tenant_id,source_id,provider,provider_location_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_location_observation_tenant96 FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT
);

CREATE TABLE public.keel_inventory_location_decisions (
    tenant_id UUID NOT NULL,
    location_decision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL,
    provider_location_identity_id UUID NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('associate','revoke')),
    decision_sequence BIGINT NOT NULL CHECK (decision_sequence>0),
    canonical_location_id UUID,
    prior_decision_id UUID,
    actor_user_id UUID NOT NULL,
    evidence_code TEXT CHECK (evidence_code IS NULL OR length(btrim(evidence_code)) BETWEEN 1 AND 80),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,location_decision_id),
    CONSTRAINT ck_keel_inventory_location_decision_shape96 CHECK (
        (decision='associate' AND canonical_location_id IS NOT NULL) OR
        (decision='revoke' AND canonical_location_id IS NULL)
    ),
    CONSTRAINT fk_keel_inventory_location_decision_provider96 FOREIGN KEY (tenant_id,source_id,provider,provider_location_identity_id)
        REFERENCES public.keel_provider_inventory_locations(tenant_id,source_id,provider,provider_location_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_location_decision_canonical96 FOREIGN KEY (tenant_id,canonical_location_id)
        REFERENCES public.keel_inventory_locations(tenant_id,canonical_location_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_location_decision_prior96 FOREIGN KEY (tenant_id,prior_decision_id)
        REFERENCES public.keel_inventory_location_decisions(tenant_id,location_decision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_location_decision_actor96 FOREIGN KEY (actor_user_id)
        REFERENCES public.users(user_id) ON DELETE RESTRICT
);

CREATE TABLE public.keel_inventory_observations (
    tenant_id UUID NOT NULL,
    inventory_observation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('shopify','woocommerce')),
    provider_inventory_record_id TEXT NOT NULL CHECK (length(btrim(provider_inventory_record_id)) BETWEEN 1 AND 255),
    provider_product_record_id TEXT NOT NULL CHECK (length(btrim(provider_product_record_id)) BETWEEN 1 AND 255),
    provider_record_identity_id UUID,
    provider_location_identity_id UUID,
    canonical_product_id UUID,
    canonical_location_id UUID,
    quantity_semantics TEXT NOT NULL CHECK (quantity_semantics IN ('available','on_hand','woocommerce_stock_quantity')),
    quantity NUMERIC NOT NULL,
    provider_revision TEXT CHECK (provider_revision IS NULL OR length(provider_revision)<=255),
    provider_updated_at TIMESTAMPTZ,
    ingestion_job_id UUID,
    receipt_id UUID,
    observation_sha256 CHAR(64) NOT NULL CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    reconciliation_status TEXT NOT NULL CHECK (reconciliation_status IN
        ('valid','unmatched_product','unmatched_location','conflict','awaiting_authority','identity_unverified')),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,inventory_observation_id),
    CONSTRAINT uq_keel_inventory_observation96 UNIQUE (tenant_id,source_id,provider,observation_sha256),
    CONSTRAINT ck_keel_inventory_observation_location96 CHECK (
        (provider='shopify' AND quantity_semantics IN ('available','on_hand')) OR
        (provider='woocommerce' AND quantity_semantics='woocommerce_stock_quantity' AND provider_location_identity_id IS NULL AND canonical_location_id IS NULL)
    ),
    CONSTRAINT ck_keel_inventory_observation_mapping96 CHECK (
        (canonical_product_id IS NULL) OR (provider_record_identity_id IS NOT NULL AND reconciliation_status IN ('valid','unmatched_location','awaiting_authority','conflict'))
    ),
    CONSTRAINT fk_keel_inventory_observation_source96 FOREIGN KEY (tenant_id,source_id,provider)
        REFERENCES public.keel_provider_sources(tenant_id,source_id,provider) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_tenant96 FOREIGN KEY (tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_record96 FOREIGN KEY (tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_location96 FOREIGN KEY (tenant_id,source_id,provider,provider_location_identity_id)
        REFERENCES public.keel_provider_inventory_locations(tenant_id,source_id,provider,provider_location_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_product96 FOREIGN KEY (tenant_id,canonical_product_id)
        REFERENCES public.products(tenant_id,product_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_canonical_location96 FOREIGN KEY (tenant_id,canonical_location_id)
        REFERENCES public.keel_inventory_locations(tenant_id,canonical_location_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_job96 FOREIGN KEY (tenant_id,source_id,ingestion_job_id)
        REFERENCES public.ingestion_jobs(tenant_id,source_id,job_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_observation_receipt96 FOREIGN KEY (tenant_id,receipt_id)
        REFERENCES public.keel_operation_receipts(tenant_id,receipt_id) ON DELETE RESTRICT
);
CREATE INDEX idx_keel_inventory_observations_product96
    ON public.keel_inventory_observations(tenant_id,canonical_product_id,quantity_semantics,observed_at DESC);
CREATE INDEX idx_keel_inventory_observations_source96
    ON public.keel_inventory_observations(tenant_id,source_id,provider,observed_at DESC);
CREATE INDEX idx_keel_inventory_observations_review96
    ON public.keel_inventory_observations(tenant_id,reconciliation_status,observed_at DESC)
    WHERE reconciliation_status<>'valid';

CREATE TABLE public.keel_inventory_authority_decisions (
    tenant_id UUID NOT NULL,
    authority_decision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    canonical_product_id UUID NOT NULL,
    canonical_location_id UUID,
    quantity_semantics TEXT NOT NULL CHECK (quantity_semantics IN ('available','on_hand','woocommerce_stock_quantity','stock_quantity')),
    decision TEXT NOT NULL CHECK (decision IN ('select','revoke')),
    decision_sequence BIGINT NOT NULL CHECK (decision_sequence>0),
    authority_kind TEXT NOT NULL CHECK (authority_kind IN ('provider','manual')),
    source_id UUID,
    provider TEXT,
    provider_record_identity_id UUID,
    provider_location_identity_id UUID,
    prior_decision_id UUID,
    actor_user_id UUID NOT NULL,
    evidence_code TEXT CHECK (evidence_code IS NULL OR length(btrim(evidence_code)) BETWEEN 1 AND 80),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id,authority_decision_id),
    CONSTRAINT ck_keel_inventory_authority_shape96 CHECK (
        (decision='select' AND authority_kind='manual' AND source_id IS NULL AND provider IS NULL AND provider_record_identity_id IS NULL AND provider_location_identity_id IS NULL) OR
        (decision='select' AND authority_kind='provider' AND source_id IS NOT NULL AND provider IS NOT NULL AND provider_record_identity_id IS NOT NULL
          AND ((provider_location_identity_id IS NULL AND canonical_location_id IS NULL) OR (provider_location_identity_id IS NOT NULL AND canonical_location_id IS NOT NULL))) OR
        (decision='revoke' AND source_id IS NULL AND provider IS NULL AND provider_record_identity_id IS NULL AND provider_location_identity_id IS NULL)
    ),
    CONSTRAINT fk_keel_inventory_authority_product96 FOREIGN KEY (tenant_id,canonical_product_id)
        REFERENCES public.products(tenant_id,product_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_location96 FOREIGN KEY (tenant_id,canonical_location_id)
        REFERENCES public.keel_inventory_locations(tenant_id,canonical_location_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_source96 FOREIGN KEY (tenant_id,source_id,provider)
        REFERENCES public.keel_provider_sources(tenant_id,source_id,provider) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_record96 FOREIGN KEY (tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_provider_location96 FOREIGN KEY (tenant_id,source_id,provider,provider_location_identity_id)
        REFERENCES public.keel_provider_inventory_locations(tenant_id,source_id,provider,provider_location_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_prior96 FOREIGN KEY (tenant_id,prior_decision_id)
        REFERENCES public.keel_inventory_authority_decisions(tenant_id,authority_decision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_inventory_authority_actor96 FOREIGN KEY (actor_user_id)
        REFERENCES public.users(user_id) ON DELETE RESTRICT
);
CREATE INDEX idx_keel_inventory_authority_history96
    ON public.keel_inventory_authority_decisions(tenant_id,canonical_product_id,quantity_semantics,decided_at DESC);

-- Evidence and decisions cannot be erased by direct UPDATE/DELETE. Tenant/source/product
-- and provider identity foreign keys are RESTRICT, matching the approved deletion guard.
CREATE OR REPLACE FUNCTION public.keel_inventory_evidence_immutable96()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'inventory provenance and authority evidence is append-only' USING ERRCODE='55000';
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_evidence_immutable96() FROM PUBLIC;
CREATE TRIGGER keel_inventory_location_observation_immutable96 BEFORE UPDATE OR DELETE ON public.keel_provider_inventory_location_observations
    FOR EACH ROW EXECUTE FUNCTION public.keel_inventory_evidence_immutable96();
CREATE TRIGGER keel_inventory_location_decision_immutable96 BEFORE UPDATE OR DELETE ON public.keel_inventory_location_decisions
    FOR EACH ROW EXECUTE FUNCTION public.keel_inventory_evidence_immutable96();
CREATE TRIGGER keel_inventory_observation_immutable96 BEFORE UPDATE OR DELETE ON public.keel_inventory_observations
    FOR EACH ROW EXECUTE FUNCTION public.keel_inventory_evidence_immutable96();
CREATE TRIGGER keel_inventory_authority_immutable96 BEFORE UPDATE OR DELETE ON public.keel_inventory_authority_decisions
    FOR EACH ROW EXECUTE FUNCTION public.keel_inventory_evidence_immutable96();

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['keel_inventory_locations','keel_provider_inventory_locations',
      'keel_provider_inventory_location_observations','keel_inventory_location_decisions',
      'keel_inventory_observations','keel_inventory_authority_decisions'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO ceopro_app USING (tenant_id=public.get_current_tenant())','isolation_'||t,t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
        EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app',t);
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.keel_inventory_location_observe96(
    p_source UUID,p_provider_location_id TEXT,p_display_name TEXT,p_provider_active BOOLEAN,
    p_provider_revision TEXT,p_provider_updated_at TIMESTAMPTZ,p_observation_sha256 TEXT
) RETURNS TABLE(provider_location_identity_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); loc UUID; inserted BOOLEAN:=FALSE; observation_inserted BOOLEAN:=FALSE;
        prior_observation public.keel_provider_inventory_location_observations%ROWTYPE;
BEGIN
    IF tid IS NULL OR p_source IS NULL OR p_provider_location_id !~ '^gid://shopify/Location/[0-9]+$'
       OR p_display_name IS NULL OR length(p_display_name) NOT BETWEEN 1 AND 200
       OR p_observation_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'provider location observation is invalid' USING ERRCODE='22023';
    END IF;
    PERFORM 1 FROM public.keel_provider_sources ps JOIN public.data_sources ds
      ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id
     WHERE ps.tenant_id=tid AND ps.source_id=p_source AND ps.provider='shopify'
       AND ps.connection_state='verified' AND ds.is_active IS TRUE FOR SHARE OF ps,ds;
    IF NOT FOUND THEN RAISE EXCEPTION 'verified active Shopify source required' USING ERRCODE='42501'; END IF;
    INSERT INTO public.keel_provider_inventory_locations AS stored_location(tenant_id,source_id,provider,provider_location_id)
      VALUES(tid,p_source,'shopify',p_provider_location_id)
      ON CONFLICT(tenant_id,source_id,provider,provider_location_id) DO NOTHING
      RETURNING stored_location.provider_location_identity_id INTO loc;
    inserted:=loc IS NOT NULL;
    IF NOT inserted THEN SELECT l.provider_location_identity_id INTO loc FROM public.keel_provider_inventory_locations l
      WHERE l.tenant_id=tid AND l.source_id=p_source AND l.provider='shopify' AND l.provider_location_id=p_provider_location_id FOR SHARE; END IF;
    INSERT INTO public.keel_provider_inventory_location_observations(tenant_id,source_id,provider,provider_location_identity_id,
       display_name,provider_active,provider_revision,provider_updated_at,observation_sha256)
    VALUES(tid,p_source,'shopify',loc,p_display_name,p_provider_active,p_provider_revision,p_provider_updated_at,p_observation_sha256)
    ON CONFLICT ON CONSTRAINT uq_keel_provider_location_observation96 DO NOTHING RETURNING TRUE INTO observation_inserted;
    IF NOT coalesce(observation_inserted,FALSE) THEN
      SELECT * INTO prior_observation FROM public.keel_provider_inventory_location_observations o
       WHERE o.tenant_id=tid AND o.source_id=p_source AND o.provider_location_identity_id=loc
         AND o.observation_sha256=p_observation_sha256;
      IF prior_observation.display_name IS DISTINCT FROM p_display_name
         OR prior_observation.provider_active IS DISTINCT FROM p_provider_active
         OR prior_observation.provider_revision IS DISTINCT FROM p_provider_revision
         OR prior_observation.provider_updated_at IS DISTINCT FROM p_provider_updated_at THEN
        RAISE EXCEPTION 'location observation identity conflicts with existing evidence' USING ERRCODE='23505';
      END IF;
    END IF;
    RETURN QUERY SELECT loc,NOT coalesce(observation_inserted,FALSE);
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_location_observe96(UUID,TEXT,TEXT,BOOLEAN,TEXT,TIMESTAMPTZ,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_inventory_location_observe96(UUID,TEXT,TEXT,BOOLEAN,TEXT,TIMESTAMPTZ,TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_inventory_location_decide96(
    p_source UUID,p_provider_location_identity UUID,p_decision TEXT,p_canonical_location UUID,p_evidence_code TEXT
) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        prov TEXT; prior UUID; prior_sequence BIGINT:=0; result UUID;
BEGIN
    IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid)
       OR NOT EXISTS(SELECT 1 FROM public.tenant_users tu WHERE tu.tenant_id=tid AND tu.user_id=actor
          AND lower(tu.role_key) IN ('owner','admin') AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL) THEN
        RAISE EXCEPTION 'active tenant owner or admin required for location association' USING ERRCODE='42501';
    END IF;
    IF p_decision NOT IN ('associate','revoke') OR (p_decision='associate')<>(p_canonical_location IS NOT NULL)
       OR p_evidence_code IS NOT NULL AND length(btrim(p_evidence_code)) NOT BETWEEN 1 AND 80 THEN
        RAISE EXCEPTION 'location decision is invalid' USING ERRCODE='22023';
    END IF;
    SELECT l.provider INTO prov FROM public.keel_provider_inventory_locations l
      WHERE l.tenant_id=tid AND l.source_id=p_source AND l.provider_location_identity_id=p_provider_location_identity FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'provider location not found in tenant source' USING ERRCODE='23503'; END IF;
    IF p_canonical_location IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.keel_inventory_locations l
      WHERE l.tenant_id=tid AND l.canonical_location_id=p_canonical_location) THEN
        RAISE EXCEPTION 'canonical location not found in tenant' USING ERRCODE='23503';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(tid::text||':'||p_source::text||':'||p_provider_location_identity::text,96));
    SELECT d.location_decision_id,d.decision_sequence INTO prior,prior_sequence FROM public.keel_inventory_location_decisions d
      WHERE d.tenant_id=tid AND d.source_id=p_source AND d.provider_location_identity_id=p_provider_location_identity
      ORDER BY d.decision_sequence DESC LIMIT 1;
    prior_sequence:=coalesce(prior_sequence,0);
    IF FOUND THEN
      IF EXISTS(SELECT 1 FROM public.keel_inventory_location_decisions d WHERE d.tenant_id=tid AND d.location_decision_id=prior
          AND d.decision=p_decision AND d.canonical_location_id IS NOT DISTINCT FROM p_canonical_location AND d.actor_user_id=actor) THEN
        RETURN prior;
      END IF;
    END IF;
    INSERT INTO public.keel_inventory_location_decisions(tenant_id,source_id,provider,provider_location_identity_id,
      decision,decision_sequence,canonical_location_id,prior_decision_id,actor_user_id,evidence_code)
      VALUES(tid,p_source,prov,p_provider_location_identity,p_decision,prior_sequence+1,p_canonical_location,prior,actor,p_evidence_code)
      RETURNING location_decision_id INTO result;
    INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
      VALUES(tid,actor,'INVENTORY_LOCATION_'||upper(p_decision),'keel_provider_inventory_locations',p_provider_location_identity,
        jsonb_build_object('decision_id',result,'canonical_location_id',p_canonical_location,'prior_decision_id',prior,'evidence_code',p_evidence_code));
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_location_decide96(UUID,UUID,TEXT,UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_inventory_location_decide96(UUID,UUID,TEXT,UUID,TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_inventory_observation_record96(
    p_source UUID,p_inventory_record_id TEXT,p_product_record_id TEXT,p_provider_record_identity UUID,
    p_provider_location_identity UUID,p_quantity_semantics TEXT,p_quantity NUMERIC,p_provider_revision TEXT,
    p_provider_updated_at TIMESTAMPTZ,p_ingestion_job UUID,p_receipt UUID,p_observation_sha256 TEXT
) RETURNS TABLE(inventory_observation_id UUID,reconciliation_status TEXT,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); prov TEXT; state TEXT; product_map UUID; entity TEXT;
        location_provider TEXT; canonical_loc UUID; loc_decision UUID; status TEXT:='unmatched_product'; result UUID; inserted BOOLEAN:=FALSE;
        prior_observation public.keel_inventory_observations%ROWTYPE;
BEGIN
    IF tid IS NULL OR p_source IS NULL OR p_inventory_record_id IS NULL OR length(btrim(p_inventory_record_id)) NOT BETWEEN 1 AND 255
       OR p_product_record_id IS NULL OR length(btrim(p_product_record_id)) NOT BETWEEN 1 AND 255
       OR p_quantity IS NULL OR p_quantity_semantics NOT IN ('available','on_hand','woocommerce_stock_quantity')
       OR p_quantity::text IN ('NaN','Infinity','-Infinity')
       OR p_observation_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'inventory observation is invalid' USING ERRCODE='22023';
    END IF;
    SELECT ps.provider,ps.connection_state INTO prov,state FROM public.keel_provider_sources ps
      JOIN public.data_sources ds ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id
      WHERE ps.tenant_id=tid AND ps.source_id=p_source AND ds.is_active IS TRUE FOR SHARE OF ps,ds;
    IF NOT FOUND OR state<>'verified' THEN RAISE EXCEPTION 'verified active tenant provider source required' USING ERRCODE='42501'; END IF;
    IF (prov='shopify' AND p_quantity_semantics NOT IN ('available','on_hand')) OR
       (prov='woocommerce' AND (p_quantity_semantics<>'woocommerce_stock_quantity' OR p_provider_location_identity IS NOT NULL)) THEN
        RAISE EXCEPTION 'quantity semantics or location do not match provider contract' USING ERRCODE='22023';
    END IF;
    IF (prov='shopify' AND ((p_inventory_record_id !~ '^gid://shopify/InventoryLevel/[0-9]+' OR
         (p_product_record_id !~ '^gid://shopify/(Product|ProductVariant|InventoryItem)/[0-9]+$')))) OR
       (prov='woocommerce' AND (p_inventory_record_id !~ '^[1-9][0-9]{0,17}$' OR p_product_record_id !~ '^[1-9][0-9]{0,17}$')) THEN
        RAISE EXCEPTION 'provider inventory identity does not match its source contract' USING ERRCODE='22023';
    END IF;
    IF p_provider_record_identity IS NOT NULL THEN
      SELECT i.entity_type,i.canonical_product_id,i.mapping_status INTO entity,product_map,status
       FROM public.keel_provider_record_identities i
       WHERE i.tenant_id=tid AND i.source_id=p_source AND i.provider=prov AND i.provider_record_identity_id=p_provider_record_identity
         AND i.provider_record_id=p_product_record_id FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'provider product identity does not match verified tenant source' USING ERRCODE='23503'; END IF;
      IF entity NOT IN ('product','variant') THEN RAISE EXCEPTION 'inventory must refer to a provider product or variant' USING ERRCODE='22023'; END IF;
      IF status='associated' AND product_map IS NOT NULL THEN status:='awaiting_authority';
      ELSIF status='conflict' OR status='unavailable' THEN status:='conflict';
      ELSE product_map:=NULL; status:='unmatched_product'; END IF;
    END IF;
    IF p_provider_location_identity IS NOT NULL THEN
      SELECT l.provider INTO location_provider FROM public.keel_provider_inventory_locations l
       WHERE l.tenant_id=tid AND l.source_id=p_source AND l.provider=prov AND l.provider_location_identity_id=p_provider_location_identity FOR SHARE;
      IF NOT FOUND THEN RAISE EXCEPTION 'provider location does not match verified tenant source' USING ERRCODE='23503'; END IF;
      SELECT d.location_decision_id,d.canonical_location_id INTO loc_decision,canonical_loc
       FROM public.keel_inventory_location_decisions d WHERE d.tenant_id=tid AND d.source_id=p_source
         AND d.provider_location_identity_id=p_provider_location_identity ORDER BY d.decision_sequence DESC LIMIT 1;
      IF canonical_loc IS NULL THEN
        IF status IN ('awaiting_authority','unmatched_product') THEN status:='unmatched_location'; END IF;
      END IF;
    ELSIF prov='shopify' THEN
      status:='unmatched_location';
    END IF;
    IF p_ingestion_job IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.ingestion_jobs j WHERE j.tenant_id=tid AND j.source_id=p_source
       AND j.job_id=p_ingestion_job AND j.job_status IN ('PROCESSING','COMPLETED')) THEN
      RAISE EXCEPTION 'inventory ingestion job does not belong to verified source' USING ERRCODE='23503';
    END IF;
    IF p_receipt IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.keel_operation_receipts r WHERE r.tenant_id=tid
       AND r.receipt_id=p_receipt AND r.operation_type='scheduled_connector_sync'
       AND r.target_kind='source' AND r.target_id=p_source) THEN
      RAISE EXCEPTION 'inventory execution receipt does not belong to verified source sync' USING ERRCODE='23503';
    END IF;
    IF EXISTS(SELECT 1 FROM public.keel_inventory_observations old
      WHERE old.tenant_id=tid AND old.source_id=p_source AND old.provider=prov
        AND old.provider_inventory_record_id=p_inventory_record_id
        AND old.provider_location_identity_id IS NOT DISTINCT FROM p_provider_location_identity
        AND old.quantity_semantics=p_quantity_semantics
        AND old.provider_revision IS NOT DISTINCT FROM p_provider_revision
        AND old.provider_updated_at IS NOT DISTINCT FROM p_provider_updated_at
        AND old.quantity IS DISTINCT FROM p_quantity) THEN
      status:='conflict';
    END IF;
    IF p_receipt IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.keel_operation_receipts r WHERE r.tenant_id=tid AND r.receipt_id=p_receipt) THEN
      RAISE EXCEPTION 'inventory receipt does not belong to tenant' USING ERRCODE='23503';
    END IF;
    INSERT INTO public.keel_inventory_observations AS stored_observation(tenant_id,source_id,provider,provider_inventory_record_id,provider_product_record_id,
      provider_record_identity_id,provider_location_identity_id,canonical_product_id,canonical_location_id,quantity_semantics,quantity,
      provider_revision,provider_updated_at,ingestion_job_id,receipt_id,observation_sha256,reconciliation_status)
    VALUES(tid,p_source,prov,p_inventory_record_id,p_product_record_id,p_provider_record_identity,p_provider_location_identity,
      product_map,canonical_loc,p_quantity_semantics,p_quantity,p_provider_revision,p_provider_updated_at,p_ingestion_job,p_receipt,
      p_observation_sha256,status)
    ON CONFLICT(tenant_id,source_id,provider,observation_sha256) DO NOTHING
    RETURNING stored_observation.inventory_observation_id INTO result;
    inserted:=result IS NOT NULL;
    IF NOT inserted THEN
       SELECT * INTO prior_observation FROM public.keel_inventory_observations o
        WHERE o.tenant_id=tid AND o.source_id=p_source AND o.provider=prov AND o.observation_sha256=p_observation_sha256;
       IF prior_observation.provider_inventory_record_id IS DISTINCT FROM p_inventory_record_id
          OR prior_observation.provider_product_record_id IS DISTINCT FROM p_product_record_id
          OR prior_observation.provider_record_identity_id IS DISTINCT FROM p_provider_record_identity
          OR prior_observation.provider_location_identity_id IS DISTINCT FROM p_provider_location_identity
          OR prior_observation.quantity_semantics IS DISTINCT FROM p_quantity_semantics
          OR prior_observation.quantity IS DISTINCT FROM p_quantity
          OR prior_observation.provider_revision IS DISTINCT FROM p_provider_revision
          OR prior_observation.provider_updated_at IS DISTINCT FROM p_provider_updated_at THEN
         RAISE EXCEPTION 'inventory observation identity conflicts with existing evidence' USING ERRCODE='23505';
       END IF;
       result:=prior_observation.inventory_observation_id;
       status:=prior_observation.reconciliation_status;
    END IF;
    RETURN QUERY SELECT result,status,NOT inserted;
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_observation_record96(UUID,TEXT,TEXT,UUID,UUID,TEXT,NUMERIC,TEXT,TIMESTAMPTZ,UUID,UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_inventory_observation_record96(UUID,TEXT,TEXT,UUID,UUID,TEXT,NUMERIC,TEXT,TIMESTAMPTZ,UUID,UUID,TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_inventory_location_register96(p_location_key TEXT,p_display_name TEXT)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid; result UUID;
BEGIN
    IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid)
       OR NOT EXISTS(SELECT 1 FROM public.tenant_users tu WHERE tu.tenant_id=tid AND tu.user_id=actor
         AND lower(tu.role_key) IN ('owner','admin') AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL) THEN
      RAISE EXCEPTION 'active tenant owner or admin required' USING ERRCODE='42501';
    END IF;
    IF p_location_key IS NULL OR length(btrim(p_location_key)) NOT BETWEEN 1 AND 160 OR p_display_name IS NULL OR length(btrim(p_display_name)) NOT BETWEEN 1 AND 200 THEN
      RAISE EXCEPTION 'canonical location identity is invalid' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.keel_inventory_locations(tenant_id,location_key,display_name,created_by_user_id)
      VALUES(tid,btrim(p_location_key),btrim(p_display_name),actor) RETURNING canonical_location_id INTO result;
    INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
      VALUES(tid,actor,'INVENTORY_LOCATION_CREATED','keel_inventory_locations',result,jsonb_build_object('location_key',btrim(p_location_key)));
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_location_register96(TEXT,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_inventory_location_register96(TEXT,TEXT) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_inventory_authority_decide96(
    p_product UUID,p_location UUID,p_quantity_semantics TEXT,p_decision TEXT,p_authority_kind TEXT,
    p_source UUID,p_provider TEXT,p_provider_record_identity UUID,p_provider_location_identity UUID,p_evidence_code TEXT
) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        prev UUID; prior_sequence BIGINT:=0; result UUID; map_product UUID; map_kind TEXT; map_state TEXT; loc UUID;
BEGIN
    IF tid IS NULL OR actor IS NULL OR NOT public.keel_active_principal(actor,tid)
       OR NOT EXISTS(SELECT 1 FROM public.tenant_users tu WHERE tu.tenant_id=tid AND tu.user_id=actor
         AND lower(tu.role_key) IN ('owner','admin') AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL) THEN
      RAISE EXCEPTION 'active tenant owner or admin required for inventory authority' USING ERRCODE='42501';
    END IF;
    IF p_product IS NULL OR p_decision NOT IN ('select','revoke') OR p_authority_kind NOT IN ('provider','manual')
       OR p_quantity_semantics NOT IN ('available','on_hand','woocommerce_stock_quantity','stock_quantity')
       OR p_evidence_code IS NOT NULL AND length(btrim(p_evidence_code)) NOT BETWEEN 1 AND 80 THEN
      RAISE EXCEPTION 'inventory authority decision is invalid' USING ERRCODE='22023';
    END IF;
    PERFORM 1 FROM public.products p WHERE p.tenant_id=tid AND p.product_id=p_product AND p.deleted_at IS NULL FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'canonical product is not available in tenant' USING ERRCODE='23503'; END IF;
    IF p_location IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.keel_inventory_locations l WHERE l.tenant_id=tid AND l.canonical_location_id=p_location) THEN
      RAISE EXCEPTION 'canonical location is not available in tenant' USING ERRCODE='23503';
    END IF;
    IF p_decision='select' AND p_authority_kind='provider' THEN
      IF p_quantity_semantics NOT IN ('available','on_hand','woocommerce_stock_quantity') THEN
        RAISE EXCEPTION 'provider quantity semantics must match an observed provider field' USING ERRCODE='22023';
      END IF;
      SELECT i.canonical_product_id,i.entity_type,i.mapping_status INTO map_product,map_kind,map_state
       FROM public.keel_provider_record_identities i WHERE i.tenant_id=tid AND i.source_id=p_source AND i.provider=p_provider
         AND i.provider_record_identity_id=p_provider_record_identity FOR SHARE;
      IF NOT FOUND OR map_state<>'associated' OR map_product IS DISTINCT FROM p_product OR map_kind NOT IN ('product','variant') THEN
        RAISE EXCEPTION 'provider product must have a reviewed association to this canonical product' USING ERRCODE='23514';
      END IF;
      IF p_provider_location_identity IS NOT NULL THEN
        SELECT d.canonical_location_id INTO loc FROM public.keel_inventory_location_decisions d
          WHERE d.tenant_id=tid AND d.source_id=p_source AND d.provider_location_identity_id=p_provider_location_identity
          ORDER BY d.decision_sequence DESC LIMIT 1;
        IF loc IS DISTINCT FROM p_location OR p_location IS NULL THEN RAISE EXCEPTION 'provider location must be explicitly associated with selected canonical location' USING ERRCODE='23514'; END IF;
      ELSIF p_location IS NOT NULL THEN RAISE EXCEPTION 'provider location identity is required for located authority' USING ERRCODE='23514';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM public.keel_provider_sources ps JOIN public.data_sources ds ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id
        WHERE ps.tenant_id=tid AND ps.source_id=p_source AND ps.provider=p_provider AND ps.connection_state='verified' AND ds.is_active IS TRUE) THEN
        RAISE EXCEPTION 'provider source must remain verified and active' USING ERRCODE='42501';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM public.keel_inventory_observations o WHERE o.tenant_id=tid AND o.source_id=p_source
        AND o.provider=p_provider AND o.provider_record_identity_id=p_provider_record_identity
        AND o.provider_location_identity_id IS NOT DISTINCT FROM p_provider_location_identity
        AND o.quantity_semantics=p_quantity_semantics) THEN
        RAISE EXCEPTION 'source has no inventory observation for the selected product, quantity field, and location' USING ERRCODE='23514';
      END IF;
    ELSIF p_decision='select' AND p_authority_kind='manual' THEN
      IF p_source IS NOT NULL OR p_provider IS NOT NULL OR p_provider_record_identity IS NOT NULL OR p_provider_location_identity IS NOT NULL
        OR p_quantity_semantics<>'stock_quantity' THEN RAISE EXCEPTION 'manual authority must refer to canonical stock quantity only' USING ERRCODE='22023'; END IF;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(tid::text||':'||p_product::text||':'||coalesce(p_location::text,'<none>')||':'||p_quantity_semantics,96));
    SELECT d.authority_decision_id,d.decision_sequence INTO prev,prior_sequence FROM public.keel_inventory_authority_decisions d
      WHERE d.tenant_id=tid AND d.canonical_product_id=p_product AND d.canonical_location_id IS NOT DISTINCT FROM p_location
        AND d.quantity_semantics=p_quantity_semantics ORDER BY d.decision_sequence DESC LIMIT 1;
    prior_sequence:=coalesce(prior_sequence,0);
    IF FOUND THEN
      IF EXISTS(SELECT 1 FROM public.keel_inventory_authority_decisions d WHERE d.tenant_id=tid AND d.authority_decision_id=prev
          AND d.decision=p_decision AND d.authority_kind=p_authority_kind
          AND d.source_id IS NOT DISTINCT FROM CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_source END
          AND d.provider_record_identity_id IS NOT DISTINCT FROM CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_provider_record_identity END
          AND d.provider_location_identity_id IS NOT DISTINCT FROM CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_provider_location_identity END
          AND d.evidence_code IS NOT DISTINCT FROM p_evidence_code
          AND d.actor_user_id=actor) THEN
        RETURN prev;
      END IF;
    END IF;
    INSERT INTO public.keel_inventory_authority_decisions(tenant_id,canonical_product_id,canonical_location_id,quantity_semantics,
      decision,decision_sequence,authority_kind,source_id,provider,provider_record_identity_id,provider_location_identity_id,prior_decision_id,actor_user_id,evidence_code)
    VALUES(tid,p_product,p_location,p_quantity_semantics,p_decision,prior_sequence+1,p_authority_kind,
      CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_source END,
      CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_provider END,
      CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_provider_record_identity END,
      CASE WHEN p_decision='select' AND p_authority_kind='provider' THEN p_provider_location_identity END,
      prev,actor,p_evidence_code) RETURNING authority_decision_id INTO result;
    INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
      VALUES(tid,actor,'INVENTORY_AUTHORITY_'||upper(p_decision),'keel_inventory_authority_decisions',result,
        jsonb_build_object('canonical_product_id',p_product,'canonical_location_id',p_location,'quantity_semantics',p_quantity_semantics,
          'authority_kind',CASE WHEN p_decision='select' THEN p_authority_kind ELSE NULL END,'source_id',CASE WHEN p_decision='select' THEN p_source ELSE NULL END,
          'provider_record_identity_id',CASE WHEN p_decision='select' THEN p_provider_record_identity ELSE NULL END,'prior_decision_id',prev,'evidence_code',p_evidence_code));
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.keel_inventory_authority_decide96(UUID,UUID,TEXT,TEXT,TEXT,UUID,TEXT,UUID,UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_inventory_authority_decide96(UUID,UUID,TEXT,TEXT,TEXT,UUID,TEXT,UUID,UUID,TEXT) TO ceopro_app;

-- No canonical inventory table or quantity is changed by this migration.
