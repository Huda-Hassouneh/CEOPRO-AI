-- Phase 3/4 provider-scoped record identities and reviewed associations.
-- Owner approved this scope on 2026-10-21. Migrations 1-94 are immutable.
-- Raw provider payloads, customer PII, credentials, and accounting data are not stored.

CREATE UNIQUE INDEX IF NOT EXISTS uq_keel_provider_source_tenant_source_provider95
    ON public.keel_provider_sources(tenant_id,source_id,provider);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_jobs_tenant_source_job95
    ON public.ingestion_jobs(tenant_id,source_id,job_id);

CREATE TABLE public.keel_provider_record_identities (
    provider_record_identity_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('shopify','woocommerce')),
    entity_type TEXT NOT NULL CHECK(entity_type IN ('product','variant','order','order_line_item')),
    provider_record_id TEXT NOT NULL CHECK(length(btrim(provider_record_id)) BETWEEN 1 AND 255),
    parent_identity_id UUID,
    related_product_identity_id UUID,
    related_variant_identity_id UUID,
    related_product_provider_id TEXT,
    related_variant_provider_id TEXT,
    latest_ingestion_job_id UUID,
    provider_revision TEXT CHECK(provider_revision IS NULL OR length(provider_revision)<=255),
    provider_updated_at TIMESTAMPTZ,
    current_revision_sha256 CHAR(64) NOT NULL CHECK(current_revision_sha256 ~ '^[0-9a-f]{64}$'),
    mapping_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK(mapping_status IN ('pending_review','associated','conflict','unavailable')),
    canonical_target_kind TEXT CHECK(canonical_target_kind IS NULL OR canonical_target_kind IN ('product','transaction','invoice')),
    canonical_product_id UUID,
    canonical_transaction_id UUID,
    canonical_invoice_id UUID,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(provider_record_identity_id),
    CONSTRAINT uq_keel_provider_record_namespace95 UNIQUE(tenant_id,source_id,provider,entity_type,provider_record_id),
    CONSTRAINT uq_keel_provider_record_source_id95 UNIQUE(tenant_id,source_id,provider,provider_record_identity_id),
    CONSTRAINT fk_keel_provider_record_source95 FOREIGN KEY(tenant_id,source_id,provider)
        REFERENCES public.keel_provider_sources(tenant_id,source_id,provider) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_tenant95 FOREIGN KEY(tenant_id)
        REFERENCES public.companies(tenant_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_parent95 FOREIGN KEY(tenant_id,source_id,provider,parent_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_product_ref95 FOREIGN KEY(tenant_id,source_id,provider,related_product_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_variant_ref95 FOREIGN KEY(tenant_id,source_id,provider,related_variant_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_job95 FOREIGN KEY(tenant_id,source_id,latest_ingestion_job_id)
        REFERENCES public.ingestion_jobs(tenant_id,source_id,job_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_canonical_product95 FOREIGN KEY(tenant_id,canonical_product_id)
        REFERENCES public.products(tenant_id,product_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_canonical_transaction95 FOREIGN KEY(tenant_id,canonical_transaction_id)
        REFERENCES public.transactions(tenant_id,transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_record_canonical_invoice95 FOREIGN KEY(tenant_id,canonical_invoice_id)
        REFERENCES public.invoices(tenant_id,invoice_id) ON DELETE RESTRICT,
    CONSTRAINT ck_keel_provider_record_parent_shape95 CHECK (
        (entity_type IN ('product','order') AND parent_identity_id IS NULL
          AND related_product_identity_id IS NULL AND related_variant_identity_id IS NULL)
        OR (entity_type='variant' AND parent_identity_id IS NOT NULL
          AND related_product_identity_id IS NULL AND related_variant_identity_id IS NULL)
        OR (entity_type='order_line_item' AND parent_identity_id IS NOT NULL)
    ),
    CONSTRAINT ck_keel_provider_record_related_id_shape95 CHECK (
        (related_product_provider_id IS NULL OR (provider='shopify' AND related_product_provider_id ~ '^gid://shopify/Product/[0-9]+$')
          OR (provider='woocommerce' AND related_product_provider_id ~ '^[1-9][0-9]{0,17}$'))
        AND (related_variant_provider_id IS NULL OR (provider='shopify' AND related_variant_provider_id ~ '^gid://shopify/ProductVariant/[0-9]+$')
          OR (provider='woocommerce' AND related_variant_provider_id ~ '^[1-9][0-9]{0,17}$'))
        AND (entity_type='order_line_item' OR (related_product_provider_id IS NULL AND related_variant_provider_id IS NULL))
    ),
    CONSTRAINT ck_keel_provider_record_target_shape95 CHECK (
        (canonical_target_kind IS NULL AND canonical_product_id IS NULL AND canonical_transaction_id IS NULL AND canonical_invoice_id IS NULL)
        OR (canonical_target_kind='product' AND canonical_product_id IS NOT NULL AND canonical_transaction_id IS NULL AND canonical_invoice_id IS NULL
             AND entity_type IN ('product','variant','order_line_item'))
        OR (canonical_target_kind='transaction' AND canonical_product_id IS NULL AND canonical_transaction_id IS NOT NULL AND canonical_invoice_id IS NULL
             AND entity_type='order')
        OR (canonical_target_kind='invoice' AND canonical_product_id IS NULL AND canonical_transaction_id IS NULL AND canonical_invoice_id IS NOT NULL
             AND entity_type='order')
    ),
    CONSTRAINT ck_keel_provider_record_associated95 CHECK (mapping_status<>'associated' OR canonical_target_kind IS NOT NULL),
    CONSTRAINT ck_keel_provider_record_provider_id_shape95 CHECK (
        (provider='shopify' AND (
            (entity_type='product' AND provider_record_id ~ '^gid://shopify/Product/[0-9]+$') OR
            (entity_type='variant' AND provider_record_id ~ '^gid://shopify/ProductVariant/[0-9]+$') OR
            (entity_type='order' AND provider_record_id ~ '^gid://shopify/Order/[0-9]+$') OR
            (entity_type='order_line_item' AND provider_record_id ~ '^gid://shopify/LineItem/[0-9]+$')
        )) OR (provider='woocommerce' AND provider_record_id ~ '^[1-9][0-9]{0,17}$')
    )
);
CREATE INDEX idx_keel_provider_record_review95
    ON public.keel_provider_record_identities(tenant_id,source_id,mapping_status,entity_type,last_seen_at DESC);
CREATE INDEX idx_keel_provider_record_parent95
    ON public.keel_provider_record_identities(tenant_id,source_id,parent_identity_id)
    WHERE parent_identity_id IS NOT NULL;

CREATE TABLE public.keel_provider_record_revisions (
    revision_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    provider TEXT NOT NULL,
    provider_record_identity_id UUID NOT NULL,
    provider_revision TEXT CHECK(provider_revision IS NULL OR length(provider_revision)<=255),
    provider_updated_at TIMESTAMPTZ,
    revision_sha256 CHAR(64) NOT NULL CHECK(revision_sha256 ~ '^[0-9a-f]{64}$'),
    ingestion_job_id UUID,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(revision_id),
    CONSTRAINT fk_keel_provider_revision_identity95 FOREIGN KEY(tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_revision_job95 FOREIGN KEY(tenant_id,source_id,ingestion_job_id)
        REFERENCES public.ingestion_jobs(tenant_id,source_id,job_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX uq_keel_provider_revision_identity95
    ON public.keel_provider_record_revisions(tenant_id,source_id,provider_record_identity_id,revision_sha256,
        coalesce(provider_revision,''),coalesce(provider_updated_at,'epoch'::timestamptz));
CREATE INDEX idx_keel_provider_revisions_timeline95
    ON public.keel_provider_record_revisions(tenant_id,source_id,provider_record_identity_id,observed_at DESC);

CREATE TABLE public.keel_provider_record_reviews (
    review_id UUID NOT NULL DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    provider TEXT NOT NULL,
    provider_record_identity_id UUID NOT NULL,
    reviewer_user_id UUID NOT NULL,
    decision TEXT NOT NULL CHECK(decision='associate'),
    target_kind TEXT NOT NULL CHECK(target_kind IN ('product','transaction','invoice')),
    canonical_product_id UUID,
    canonical_transaction_id UUID,
    canonical_invoice_id UUID,
    review_metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK(
        jsonb_typeof(review_metadata)='object' AND octet_length(review_metadata::text)<=4096
        AND review_metadata-ARRAY['reason_code','evidence_reference']='{}'::jsonb
    ),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(review_id),
    CONSTRAINT uq_keel_provider_record_single_approved_association95 UNIQUE(tenant_id,provider_record_identity_id),
    CONSTRAINT fk_keel_provider_review_identity95 FOREIGN KEY(tenant_id,source_id,provider,provider_record_identity_id)
        REFERENCES public.keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_review_actor95 FOREIGN KEY(reviewer_user_id)
        REFERENCES public.users(user_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_review_product95 FOREIGN KEY(tenant_id,canonical_product_id)
        REFERENCES public.products(tenant_id,product_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_review_transaction95 FOREIGN KEY(tenant_id,canonical_transaction_id)
        REFERENCES public.transactions(tenant_id,transaction_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_provider_review_invoice95 FOREIGN KEY(tenant_id,canonical_invoice_id)
        REFERENCES public.invoices(tenant_id,invoice_id) ON DELETE RESTRICT,
    CONSTRAINT ck_keel_provider_review_target95 CHECK(
        (target_kind='product' AND canonical_product_id IS NOT NULL AND canonical_transaction_id IS NULL AND canonical_invoice_id IS NULL)
        OR (target_kind='transaction' AND canonical_product_id IS NULL AND canonical_transaction_id IS NOT NULL AND canonical_invoice_id IS NULL)
        OR (target_kind='invoice' AND canonical_product_id IS NULL AND canonical_transaction_id IS NULL AND canonical_invoice_id IS NOT NULL)
    )
);
CREATE INDEX idx_keel_provider_reviews_audit95
    ON public.keel_provider_record_reviews(tenant_id,source_id,reviewed_at DESC);

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['keel_provider_record_identities','keel_provider_record_revisions','keel_provider_record_reviews'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO ceopro_app USING (tenant_id=public.get_current_tenant())','isolation_'||t,t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
        EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app',t);
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.keel_provider_identity_immutable_evidence()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'provider identity revision and review evidence is append-only' USING ERRCODE='55000';
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_identity_immutable_evidence() FROM PUBLIC;
CREATE TRIGGER keel_provider_revisions_no_mutation95 BEFORE UPDATE OR DELETE ON public.keel_provider_record_revisions
    FOR EACH ROW EXECUTE FUNCTION public.keel_provider_identity_immutable_evidence();
CREATE TRIGGER keel_provider_reviews_no_mutation95 BEFORE UPDATE OR DELETE ON public.keel_provider_record_reviews
    FOR EACH ROW EXECUTE FUNCTION public.keel_provider_identity_immutable_evidence();

CREATE OR REPLACE FUNCTION public.keel_provider_identity_observe(
    p_source_id UUID,p_entity_type TEXT,p_provider_record_id TEXT,p_parent_provider_record_id TEXT,
    p_related_product_provider_record_id TEXT,p_related_variant_provider_record_id TEXT,
    p_provider_revision TEXT,p_provider_updated_at TIMESTAMPTZ,p_revision_sha256 TEXT,p_ingestion_job_id UUID
) RETURNS TABLE(provider_record_identity_id UUID,mapping_status TEXT,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
    tid UUID:=public.get_current_tenant(); prov TEXT; source_state TEXT; source_active BOOLEAN;
    parent_id UUID; product_id UUID; variant_id UUID; ident UUID; inserted BOOLEAN:=FALSE;
    current_record public.keel_provider_record_identities%ROWTYPE; revision_inserted BOOLEAN:=FALSE;
    relationship_conflict BOOLEAN:=FALSE; line_relationship_conflict BOOLEAN:=FALSE; is_duplicate BOOLEAN:=FALSE;
BEGIN
    IF tid IS NULL OR p_source_id IS NULL OR p_entity_type NOT IN ('product','variant','order','order_line_item')
       OR p_provider_record_id IS NULL OR length(p_provider_record_id)>255
       OR p_provider_revision IS NOT NULL AND length(p_provider_revision)>255
       OR p_revision_sha256 IS NULL OR p_revision_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'provider identity observation is invalid' USING ERRCODE='22023';
    END IF;
    SELECT s.provider,s.connection_state,ds.is_active INTO prov,source_state,source_active
      FROM public.keel_provider_sources s JOIN public.data_sources ds
        ON ds.tenant_id=s.tenant_id AND ds.source_id=s.source_id
     WHERE s.tenant_id=tid AND s.source_id=p_source_id FOR SHARE OF s,ds;
    IF NOT FOUND OR source_state<>'verified' OR source_active IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'verified active tenant provider source is required' USING ERRCODE='42501';
    END IF;
    IF prov='shopify' AND NOT (
        (p_entity_type='product' AND p_provider_record_id ~ '^gid://shopify/Product/[0-9]+$') OR
        (p_entity_type='variant' AND p_provider_record_id ~ '^gid://shopify/ProductVariant/[0-9]+$') OR
        (p_entity_type='order' AND p_provider_record_id ~ '^gid://shopify/Order/[0-9]+$') OR
        (p_entity_type='order_line_item' AND p_provider_record_id ~ '^gid://shopify/LineItem/[0-9]+$')) THEN
        RAISE EXCEPTION 'Shopify provider record ID does not match its entity type' USING ERRCODE='22023';
    ELSIF prov='woocommerce' AND p_provider_record_id !~ '^[1-9][0-9]{0,17}$' THEN
        RAISE EXCEPTION 'WooCommerce provider record ID must be a positive provider ID' USING ERRCODE='22023';
    END IF;
    IF p_entity_type='variant' THEN
        IF p_parent_provider_record_id IS NULL THEN RAISE EXCEPTION 'variant parent product identity is required' USING ERRCODE='22023'; END IF;
        SELECT i.provider_record_identity_id INTO parent_id FROM public.keel_provider_record_identities i
         WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type='product'
           AND i.provider_record_id=p_parent_provider_record_id FOR SHARE;
    ELSIF p_entity_type='order_line_item' THEN
        IF p_parent_provider_record_id IS NULL THEN RAISE EXCEPTION 'line item parent order identity is required' USING ERRCODE='22023'; END IF;
        SELECT i.provider_record_identity_id INTO parent_id FROM public.keel_provider_record_identities i
         WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type='order'
           AND i.provider_record_id=p_parent_provider_record_id FOR SHARE;
    END IF;
    IF p_parent_provider_record_id IS NOT NULL AND parent_id IS NULL THEN
        RAISE EXCEPTION 'provider parent identity must be observed first in the same source' USING ERRCODE='23503';
    END IF;
    IF p_related_product_provider_record_id IS NOT NULL THEN
        SELECT i.provider_record_identity_id INTO product_id FROM public.keel_provider_record_identities i
         WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type='product'
           AND i.provider_record_id=p_related_product_provider_record_id FOR SHARE;
        -- Unknown related products remain source-scoped raw references for review; they do not block the order-line identity.
    END IF;
    IF p_related_variant_provider_record_id IS NOT NULL THEN
        SELECT i.provider_record_identity_id,i.parent_identity_id INTO variant_id,product_id
          FROM public.keel_provider_record_identities i
         WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type='variant'
           AND i.provider_record_id=p_related_variant_provider_record_id FOR SHARE;
        -- Unknown related variants remain source-scoped raw references for review.
        IF variant_id IS NOT NULL AND p_related_product_provider_record_id IS NOT NULL AND product_id IS DISTINCT FROM (
            SELECT i.provider_record_identity_id FROM public.keel_provider_record_identities i
             WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type='product'
               AND i.provider_record_id=p_related_product_provider_record_id) THEN
            line_relationship_conflict:=TRUE;
            product_id:=NULL; variant_id:=NULL;
        END IF;
    END IF;
    IF p_entity_type IN ('product','order') AND (p_parent_provider_record_id IS NOT NULL OR p_related_product_provider_record_id IS NOT NULL OR p_related_variant_provider_record_id IS NOT NULL) THEN
        RAISE EXCEPTION 'top-level provider identity cannot carry parent/product references' USING ERRCODE='22023';
    ELSIF p_entity_type='variant' AND (p_related_product_provider_record_id IS NOT NULL OR p_related_variant_provider_record_id IS NOT NULL) THEN
        RAISE EXCEPTION 'variant parent is expressed by its product identity' USING ERRCODE='22023';
    END IF;
    IF p_ingestion_job_id IS NOT NULL AND NOT EXISTS(
        SELECT 1 FROM public.ingestion_jobs j WHERE j.tenant_id=tid AND j.source_id=p_source_id AND j.job_id=p_ingestion_job_id
          AND j.job_status IN ('PROCESSING','COMPLETED')) THEN
        RAISE EXCEPTION 'provider identity staging job must belong to this active source' USING ERRCODE='42501';
    END IF;

    INSERT INTO public.keel_provider_record_identities(tenant_id,source_id,provider,entity_type,provider_record_id,
        parent_identity_id,related_product_identity_id,related_variant_identity_id,related_product_provider_id,related_variant_provider_id,latest_ingestion_job_id,
        provider_revision,provider_updated_at,current_revision_sha256,mapping_status)
    VALUES(tid,p_source_id,prov,p_entity_type,p_provider_record_id,parent_id,
        CASE WHEN p_entity_type='variant' THEN NULL ELSE product_id END,
        CASE WHEN p_related_variant_provider_record_id IS NULL THEN NULL ELSE variant_id END,
        p_related_product_provider_record_id,p_related_variant_provider_record_id,p_ingestion_job_id,
        p_provider_revision,p_provider_updated_at,p_revision_sha256,
        CASE WHEN line_relationship_conflict THEN 'conflict' ELSE 'pending_review' END)
    ON CONFLICT(tenant_id,source_id,provider,entity_type,provider_record_id) DO NOTHING
    RETURNING public.keel_provider_record_identities.provider_record_identity_id INTO ident;
    inserted:=ident IS NOT NULL;
    IF NOT inserted THEN
        SELECT * INTO current_record FROM public.keel_provider_record_identities i
         WHERE i.tenant_id=tid AND i.source_id=p_source_id AND i.provider=prov AND i.entity_type=p_entity_type
           AND i.provider_record_id=p_provider_record_id FOR UPDATE;
        ident:=current_record.provider_record_identity_id;
        relationship_conflict:=current_record.parent_identity_id IS DISTINCT FROM parent_id
            OR current_record.related_product_provider_id IS DISTINCT FROM p_related_product_provider_record_id
            OR current_record.related_variant_provider_id IS DISTINCT FROM p_related_variant_provider_record_id
            OR (current_record.related_product_identity_id IS NOT NULL AND product_id IS NOT NULL
                AND current_record.related_product_identity_id IS DISTINCT FROM product_id)
            OR (current_record.related_variant_identity_id IS NOT NULL AND variant_id IS NOT NULL
                AND current_record.related_variant_identity_id IS DISTINCT FROM variant_id);
    END IF;
    INSERT INTO public.keel_provider_record_revisions(tenant_id,source_id,provider,provider_record_identity_id,
        provider_revision,provider_updated_at,revision_sha256,ingestion_job_id)
    VALUES(tid,p_source_id,prov,ident,p_provider_revision,p_provider_updated_at,p_revision_sha256,p_ingestion_job_id)
    ON CONFLICT DO NOTHING RETURNING TRUE INTO revision_inserted;
    revision_inserted:=coalesce(revision_inserted,FALSE);
    IF inserted THEN
        UPDATE public.keel_provider_record_identities AS identity_row SET latest_ingestion_job_id=p_ingestion_job_id,
            last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
        RETURN QUERY SELECT ident,(SELECT i.mapping_status FROM public.keel_provider_record_identities i WHERE i.tenant_id=tid AND i.provider_record_identity_id=ident),FALSE; RETURN;
    END IF;
    is_duplicate:=NOT revision_inserted;
    IF relationship_conflict OR line_relationship_conflict THEN
        UPDATE public.keel_provider_record_identities AS identity_row SET mapping_status='conflict',last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
    ELSIF current_record.provider_revision IS NULL AND current_record.provider_updated_at IS NULL
       AND p_provider_revision IS NULL AND p_provider_updated_at IS NULL THEN
        -- Without a provider revision marker we cannot prove that a repeated
        -- payload is unchanged. Preserve identity and any reviewed target,
        -- but hold the record for review instead of assuming an exact replay.
        UPDATE public.keel_provider_record_identities AS identity_row SET mapping_status='conflict',last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
    ELSIF current_record.current_revision_sha256=p_revision_sha256
       AND current_record.provider_revision IS NOT DISTINCT FROM p_provider_revision
       AND current_record.provider_updated_at IS NOT DISTINCT FROM p_provider_updated_at THEN
        UPDATE public.keel_provider_record_identities AS identity_row SET last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
        is_duplicate:=TRUE;
    ELSIF current_record.provider_updated_at IS NOT NULL AND p_provider_updated_at IS NOT NULL
       AND p_provider_updated_at>current_record.provider_updated_at THEN
        UPDATE public.keel_provider_record_identities AS identity_row SET related_product_identity_id=coalesce(identity_row.related_product_identity_id,product_id),
            related_variant_identity_id=coalesce(identity_row.related_variant_identity_id,variant_id),provider_revision=p_provider_revision,
            provider_updated_at=p_provider_updated_at,current_revision_sha256=p_revision_sha256,
            latest_ingestion_job_id=p_ingestion_job_id,last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
    ELSIF current_record.provider_updated_at IS NOT NULL AND p_provider_updated_at IS NOT NULL
       AND p_provider_updated_at<current_record.provider_updated_at THEN
        UPDATE public.keel_provider_record_identities AS identity_row SET last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
    ELSE
        UPDATE public.keel_provider_record_identities AS identity_row SET mapping_status='conflict',last_seen_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=ident;
    END IF;
    RETURN QUERY SELECT ident,(SELECT i.mapping_status FROM public.keel_provider_record_identities i
        WHERE i.tenant_id=tid AND i.provider_record_identity_id=ident),is_duplicate;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_identity_observe(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_identity_observe(UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,UUID) TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_provider_record_associate(
    p_identity_id UUID,p_target_kind TEXT,p_target_id UUID,p_metadata JSONB
) RETURNS TABLE(review_id UUID,duplicate BOOLEAN)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE tid UUID:=public.get_current_tenant(); actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
        record_row public.keel_provider_record_identities%ROWTYPE; existing public.keel_provider_record_reviews%ROWTYPE;
        target_product UUID; target_transaction UUID; target_invoice UUID; result_id UUID;
BEGIN
    IF tid IS NULL OR actor IS NULL OR public.get_current_tenant() IS DISTINCT FROM tid
       OR NOT public.keel_active_principal(actor,tid) THEN
        RAISE EXCEPTION 'active tenant reviewer required' USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM public.tenant_users tu WHERE tu.tenant_id=tid AND tu.user_id=actor
        AND lower(tu.role_key) IN ('owner','admin') AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL) THEN
        RAISE EXCEPTION 'tenant owner or admin review role required' USING ERRCODE='42501';
    END IF;
    IF p_target_kind NOT IN ('product','transaction','invoice') OR p_target_id IS NULL
       OR coalesce(p_metadata,'{}'::jsonb)-ARRAY['reason_code','evidence_reference']<>'{}'::jsonb
       OR NOT public.keel_provider_json_safe(coalesce(p_metadata,'{}'::jsonb))
       OR jsonb_typeof(coalesce(p_metadata,'{}'::jsonb))<>'object'
       OR octet_length(coalesce(p_metadata,'{}'::jsonb)::text)>4096 THEN
        RAISE EXCEPTION 'review association request is invalid or contains non-approved metadata' USING ERRCODE='22023';
    END IF;
    SELECT * INTO record_row FROM public.keel_provider_record_identities i
     WHERE i.tenant_id=tid AND i.provider_record_identity_id=p_identity_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'provider identity not found' USING ERRCODE='P0002'; END IF;
    IF p_target_kind='product' AND record_row.entity_type IN ('product','variant','order_line_item') THEN
        SELECT p.product_id INTO target_product FROM public.products p WHERE p.tenant_id=tid AND p.product_id=p_target_id AND p.deleted_at IS NULL FOR SHARE;
    ELSIF p_target_kind='transaction' AND record_row.entity_type='order' THEN
        SELECT t.transaction_id INTO target_transaction FROM public.transactions t WHERE t.tenant_id=tid AND t.transaction_id=p_target_id FOR SHARE;
    ELSIF p_target_kind='invoice' AND record_row.entity_type='order' THEN
        SELECT i.invoice_id INTO target_invoice FROM public.invoices i WHERE i.tenant_id=tid AND i.invoice_id=p_target_id FOR SHARE;
    ELSE
        RAISE EXCEPTION 'canonical target kind is not valid for this provider record type' USING ERRCODE='22023';
    END IF;
    IF (p_target_kind='product' AND target_product IS NULL) OR (p_target_kind='transaction' AND target_transaction IS NULL)
       OR (p_target_kind='invoice' AND target_invoice IS NULL) THEN
        RAISE EXCEPTION 'canonical review target is not available in this tenant' USING ERRCODE='23503';
    END IF;
    SELECT * INTO existing FROM public.keel_provider_record_reviews r
     WHERE r.tenant_id=tid AND r.provider_record_identity_id=p_identity_id;
    IF FOUND THEN
        IF existing.target_kind=p_target_kind AND existing.canonical_product_id IS NOT DISTINCT FROM target_product
           AND existing.canonical_transaction_id IS NOT DISTINCT FROM target_transaction
           AND existing.canonical_invoice_id IS NOT DISTINCT FROM target_invoice THEN
            RETURN QUERY SELECT existing.review_id,TRUE; RETURN;
        END IF;
        RAISE EXCEPTION 'a reviewed provider identity association cannot be replaced' USING ERRCODE='23505';
    END IF;
    INSERT INTO public.keel_provider_record_reviews(tenant_id,source_id,provider,provider_record_identity_id,
        reviewer_user_id,decision,target_kind,canonical_product_id,canonical_transaction_id,canonical_invoice_id,review_metadata)
    VALUES(tid,record_row.source_id,record_row.provider,p_identity_id,actor,'associate',p_target_kind,target_product,target_transaction,target_invoice,
        coalesce(p_metadata,'{}'::jsonb)) RETURNING public.keel_provider_record_reviews.review_id INTO result_id;
    UPDATE public.keel_provider_record_identities AS identity_row SET mapping_status='associated',canonical_target_kind=p_target_kind,
        canonical_product_id=target_product,canonical_transaction_id=target_transaction,canonical_invoice_id=target_invoice,updated_at=clock_timestamp()
      WHERE identity_row.tenant_id=tid AND identity_row.provider_record_identity_id=p_identity_id;
    INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
    VALUES(tid,actor,'PROVIDER_RECORD_ASSOCIATED','keel_provider_record_identities',p_identity_id,
        jsonb_build_object('provider',record_row.provider,'entity_type',record_row.entity_type,
            'provider_record_id',record_row.provider_record_id,'target_kind',p_target_kind,'target_id',p_target_id,
            'review_id',result_id,'decision','associate'));
    RETURN QUERY SELECT result_id,FALSE;
END $$;
REVOKE ALL ON FUNCTION public.keel_provider_record_associate(UUID,TEXT,UUID,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_provider_record_associate(UUID,TEXT,UUID,JSONB) TO ceopro_app;

-- No public API is registered. Review is an internal persistence primitive;
-- canonical writes and automated associations remain disabled.
