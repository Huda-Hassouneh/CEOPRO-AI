-- Phase 2C durable quote lifecycle. This migration adds quote/revision/event and
-- checkout identity only. It creates no offer outbox and changes no billing,
-- subscription, entitlement, payment, usage or Credit authority.
-- Migrations 1-92 are immutable; no historical quote or customer backfill.

CREATE TABLE IF NOT EXISTS public.billing_custom_quotes (
    quote_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    customer_user_id UUID,
    current_revision_id UUID,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft','submitted','approved','accepted','rejected','expired')),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    created_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    CONSTRAINT uq_billing_custom_quotes_tenant_quote UNIQUE (tenant_id, quote_id),
    CONSTRAINT uq_billing_custom_quotes_idempotency UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_billing_custom_quote_customer_tenant
        FOREIGN KEY (tenant_id, customer_user_id)
        REFERENCES public.tenant_users(tenant_id, user_id) ON DELETE SET NULL (customer_user_id)
);

CREATE TABLE IF NOT EXISTS public.billing_custom_quote_revisions (
    revision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    quote_id UUID NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    request_key TEXT NOT NULL CHECK (length(request_key) BETWEEN 1 AND 200),
    request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(configuration) = 'object'),
    feature_quantities JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(feature_quantities) = 'object'),
    commercial_terms JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(commercial_terms) = 'object'),
    economic_inputs JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(economic_inputs) = 'object'),
    fx_evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(fx_evidence) = 'object'),
    valid_until TIMESTAMPTZ,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft','approved','accepted','rejected','expired')),
    approval_reference TEXT,
    approved_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    accepted_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    accepted_at TIMESTAMPTZ,
    rejected_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    rejected_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    created_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_billing_custom_quote_revision_identity UNIQUE (tenant_id, quote_id, revision_id),
    CONSTRAINT uq_billing_custom_quote_revision_number UNIQUE (tenant_id, quote_id, revision_number),
    CONSTRAINT uq_billing_custom_quote_revision_request UNIQUE (tenant_id, quote_id, request_key),
    CONSTRAINT fk_billing_custom_quote_revision_quote
        FOREIGN KEY (tenant_id, quote_id)
        REFERENCES public.billing_custom_quotes(tenant_id, quote_id) ON DELETE CASCADE,
    CONSTRAINT ck_billing_custom_quote_approval_state CHECK (
        (state NOT IN ('approved','accepted') OR
         (approval_reference IS NOT NULL AND length(btrim(approval_reference)) > 0
          AND approved_at IS NOT NULL AND finalized_at IS NOT NULL))
        AND (state <> 'accepted' OR accepted_at IS NOT NULL)
        AND (state <> 'rejected' OR rejected_at IS NOT NULL)
    )
);

ALTER TABLE public.billing_custom_quotes
    DROP CONSTRAINT IF EXISTS fk_billing_custom_quote_current_revision;
ALTER TABLE public.billing_custom_quotes
    ADD CONSTRAINT fk_billing_custom_quote_current_revision
    FOREIGN KEY (tenant_id, quote_id, current_revision_id)
    REFERENCES public.billing_custom_quote_revisions(tenant_id, quote_id, revision_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS public.billing_custom_quote_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    quote_id UUID NOT NULL,
    revision_id UUID,
    actor_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL CHECK (action IN
        ('draft_created','revision_created','submitted','approved','accepted','rejected','expired',
         'checkout_prepared','checkout_identity_updated')),
    idempotency_key TEXT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT fk_billing_custom_quote_event_quote
        FOREIGN KEY (tenant_id, quote_id)
        REFERENCES public.billing_custom_quotes(tenant_id, quote_id) ON DELETE CASCADE,
    CONSTRAINT fk_billing_custom_quote_event_revision
        FOREIGN KEY (tenant_id, quote_id, revision_id)
        REFERENCES public.billing_custom_quote_revisions(tenant_id, quote_id, revision_id) ON DELETE CASCADE,
    CONSTRAINT uq_billing_custom_quote_event_idempotency
        UNIQUE (tenant_id, quote_id, action, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_billing_custom_quote_events_timeline
    ON public.billing_custom_quote_events (tenant_id, quote_id, created_at, event_id);

CREATE TABLE IF NOT EXISTS public.billing_custom_quote_checkout_attempts (
    attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    quote_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    request_fingerprint CHAR(64) NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    state TEXT NOT NULL DEFAULT 'prepared'
        CHECK (state IN ('prepared','session_created','outcome_unknown','reconciliation_required','failed','cancelled','settled')),
    stripe_checkout_session_id TEXT,
    stripe_subscription_id TEXT,
    stripe_invoice_id TEXT,
    provider_event_id TEXT,
    provider_outcome TEXT CHECK (provider_outcome IS NULL OR provider_outcome IN ('unknown','failed','cancelled','settled')),
    last_error_code TEXT,
    created_by_user_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_billing_custom_quote_attempt_tenant_identity UNIQUE (tenant_id, attempt_id),
    CONSTRAINT uq_billing_custom_quote_attempt_idempotency UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT uq_billing_custom_quote_attempt_session UNIQUE (stripe_checkout_session_id),
    CONSTRAINT uq_billing_custom_quote_attempt_subscription UNIQUE (stripe_subscription_id),
    CONSTRAINT uq_billing_custom_quote_attempt_invoice UNIQUE (stripe_invoice_id),
    CONSTRAINT uq_billing_custom_quote_attempt_provider_event UNIQUE (provider_event_id),
    CONSTRAINT fk_billing_custom_quote_attempt_revision
        FOREIGN KEY (tenant_id, quote_id, revision_id)
        REFERENCES public.billing_custom_quote_revisions(tenant_id, quote_id, revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_billing_custom_quote_attempt_quote
        FOREIGN KEY (tenant_id, quote_id)
        REFERENCES public.billing_custom_quotes(tenant_id, quote_id) ON DELETE CASCADE,
    CONSTRAINT ck_billing_custom_quote_attempt_identity_state CHECK (
        state NOT IN ('session_created','outcome_unknown','reconciliation_required','settled')
        OR stripe_checkout_session_id IS NOT NULL
    ),
    CONSTRAINT ck_billing_custom_quote_attempt_settlement CHECK (
        state <> 'settled' OR (stripe_invoice_id IS NOT NULL AND provider_event_id IS NOT NULL
                               AND provider_outcome = 'settled')
    ),
    CONSTRAINT ck_billing_custom_quote_attempt_stripe_ids CHECK (
        (stripe_checkout_session_id IS NULL OR stripe_checkout_session_id ~ '^cs_(test|live)_[A-Za-z0-9]+$')
        AND (stripe_subscription_id IS NULL OR stripe_subscription_id ~ '^sub_[A-Za-z0-9]+$')
        AND (stripe_invoice_id IS NULL OR stripe_invoice_id ~ '^in_[A-Za-z0-9]+$')
        AND (provider_event_id IS NULL OR provider_event_id ~ '^evt_[A-Za-z0-9]+$')
    )
);
CREATE INDEX IF NOT EXISTS idx_billing_custom_quote_attempt_quote
    ON public.billing_custom_quote_checkout_attempts (tenant_id, quote_id, created_at DESC);

-- Direct runtime access is read-only; every write is through the audited,
-- context-checking command function below. RLS remains defense in depth.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['billing_custom_quotes','billing_custom_quote_revisions',
        'billing_custom_quote_events','billing_custom_quote_checkout_attempts'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'billing_custom_quote_tenant_read', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO ceopro_app USING (tenant_id = public.get_current_tenant())',
                       'billing_custom_quote_tenant_read', t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', t);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
            EXECUTE format('REVOKE ALL ON public.%I FROM ceopro_app', t);
            EXECUTE format('GRANT SELECT ON public.%I TO ceopro_app', t);
        END IF;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_quote_event_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    -- Match approved tenant-deletion cascade and preserve evidence when only
    -- the individual actor is deleted.
    IF TG_OP = 'UPDATE' AND OLD.actor_user_id IS NOT NULL AND NEW.actor_user_id IS NULL
       AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id') THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'billing_custom_quote_events is append-only' USING ERRCODE='42501';
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_event_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS billing_custom_quote_events_guard ON public.billing_custom_quote_events;
CREATE TRIGGER billing_custom_quote_events_guard
    BEFORE UPDATE OR DELETE ON public.billing_custom_quote_events
    FOR EACH ROW EXECUTE FUNCTION public.billing_custom_quote_event_guard();
DROP TRIGGER IF EXISTS billing_custom_quote_events_guard_truncate ON public.billing_custom_quote_events;
CREATE TRIGGER billing_custom_quote_events_guard_truncate
    BEFORE TRUNCATE ON public.billing_custom_quote_events
    FOR EACH STATEMENT EXECUTE FUNCTION public.billing_custom_quote_event_guard();

CREATE OR REPLACE FUNCTION public.billing_custom_quote_revision_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'custom quote revisions cannot be deleted' USING ERRCODE='42501';
    END IF;
    IF (NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id AND NEW.created_by_user_id IS NOT NULL)
       OR (NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id AND NEW.approved_by_user_id IS NOT NULL
           AND NOT (OLD.approved_by_user_id IS NULL AND NEW.state='approved'))
       OR (NEW.accepted_by_user_id IS DISTINCT FROM OLD.accepted_by_user_id AND NEW.accepted_by_user_id IS NOT NULL
           AND NOT (OLD.accepted_by_user_id IS NULL AND NEW.state='accepted'))
       OR (NEW.rejected_by_user_id IS DISTINCT FROM OLD.rejected_by_user_id AND NEW.rejected_by_user_id IS NOT NULL
           AND NOT (OLD.rejected_by_user_id IS NULL AND NEW.state='rejected'))
       OR (to_jsonb(NEW) - ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
         'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at'])
       <> (to_jsonb(OLD) - ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
         'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at']) THEN
        RAISE EXCEPTION 'custom quote revision snapshots are immutable; create a new revision' USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_revision_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS billing_custom_quote_revisions_guard ON public.billing_custom_quote_revisions;
CREATE TRIGGER billing_custom_quote_revisions_guard
    BEFORE UPDATE OR DELETE ON public.billing_custom_quote_revisions
    FOR EACH ROW EXECUTE FUNCTION public.billing_custom_quote_revision_guard();

CREATE OR REPLACE FUNCTION public.keel_custom_quote_json_secret_free(p JSONB)
RETURNS BOOLEAN LANGUAGE SQL IMMUTABLE PARALLEL SAFE
SET search_path = pg_catalog, public, pg_temp AS $$
    WITH RECURSIVE nodes(value) AS (
        SELECT coalesce(p, '{}'::jsonb)
        UNION ALL
        SELECT child.value
          FROM nodes n
          CROSS JOIN LATERAL (
              SELECT e.value FROM jsonb_each(
                  CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END
              ) e
              UNION ALL
              SELECT a.value FROM jsonb_array_elements(
                  CASE WHEN jsonb_typeof(n.value)='array' THEN n.value ELSE '[]'::jsonb END
              ) a
          ) child
    ), keys AS (
        SELECT k.key FROM nodes n CROSS JOIN LATERAL jsonb_object_keys(
            CASE WHEN jsonb_typeof(n.value)='object' THEN n.value ELSE '{}'::jsonb END
        ) k(key)
    )
    SELECT NOT EXISTS (
        SELECT 1 FROM keys WHERE key ~* '(secret|token|password|credential|authorization|cookie|api[_-]?key|private[_-]?key)'
    );
$$;
REVOKE ALL ON FUNCTION public.keel_custom_quote_json_secret_free(JSONB) FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.billing_custom_quote_command(p_action TEXT, p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    v_actor UUID := nullif(current_setting('app.current_user_id', true), '')::uuid;
    v_context_tenant UUID := nullif(current_setting('app.current_tenant_id', true), '')::uuid;
    v_tenant UUID := nullif(p->>'tenant_id','')::uuid;
    v_quote_id UUID := nullif(p->>'quote_id','')::uuid;
    v_revision_id UUID;
    v_customer UUID := nullif(p->>'customer_user_id','')::uuid;
    v_quote public.billing_custom_quotes%ROWTYPE;
    v_revision public.billing_custom_quote_revisions%ROWTYPE;
    v_attempt public.billing_custom_quote_checkout_attempts%ROWTYPE;
    v_role TEXT;
    v_platform_role TEXT;
    v_key TEXT;
    v_fingerprint TEXT;
    v_expected INTEGER;
    v_next INTEGER;
    v_attempt_id UUID;
    v_result JSONB;
    v_event_type TEXT;
    v_event_payload JSONB;
    v_event_object JSONB;
    v_provider_event_id TEXT;
    v_provider_outcome TEXT;
    v_attempt_state TEXT;
    v_event_attempt_id TEXT;
    v_stripe_subscription_id TEXT;
BEGIN
    IF v_actor = '00000000-0000-0000-0000-000000000000'::uuid THEN
        IF p_action <> 'checkout_identity_update' OR v_context_tenant IS NULL
           OR public.get_current_tenant() IS DISTINCT FROM v_context_tenant THEN
            RAISE EXCEPTION 'service context is restricted to verified checkout reconciliation' USING ERRCODE='42501';
        END IF;
    ELSIF v_actor IS NULL OR v_context_tenant IS NULL
       OR NOT public.keel_active_principal(v_actor, v_context_tenant) THEN
        RAISE EXCEPTION 'active authenticated context required' USING ERRCODE='42501';
    END IF;

    SELECT role_key INTO v_platform_role FROM public.keel_platform_members
     WHERE user_id=v_actor AND status='active';
    IF v_platform_role IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.users WHERE user_id=v_actor AND platform_disabled_at IS NOT NULL
    ) THEN v_platform_role := NULL; END IF;

    IF p_action IN ('create_draft','create_revision','submit','approve') THEN
        IF v_platform_role IS DISTINCT FROM 'owner'
           OR NOT EXISTS (SELECT 1 FROM public.keel_platform_workspace WHERE tenant_id=v_context_tenant) THEN
            RAISE EXCEPTION 'Platform Owner permission required' USING ERRCODE='42501';
        END IF;
    ELSIF p_action='checkout_identity_update' THEN
        IF v_actor IS DISTINCT FROM '00000000-0000-0000-0000-000000000000'::uuid THEN
            RAISE EXCEPTION 'verified service context required for provider identity updates' USING ERRCODE='42501';
        END IF;
    ELSIF p_action IN ('accept','reject','checkout_prepare') THEN
        IF v_tenant IS DISTINCT FROM v_context_tenant OR v_tenant IS NULL THEN
            RAISE EXCEPTION 'quote is outside the authenticated tenant' USING ERRCODE='42501';
        END IF;
        SELECT role_key INTO v_role FROM public.tenant_users
         WHERE tenant_id=v_tenant AND user_id=v_actor AND removed_at IS NULL
           AND platform_suspended_at IS NULL;
        IF v_role NOT IN ('owner','admin','accountant') THEN
            RAISE EXCEPTION 'billing role required' USING ERRCODE='42501';
        END IF;
    ELSE
        RAISE EXCEPTION 'unsupported quote command' USING ERRCODE='22023';
    END IF;

    IF p_action IN ('create_draft','create_revision')
       AND NOT public.keel_custom_quote_json_secret_free(p) THEN
        RAISE EXCEPTION 'quote snapshot contains a secret-like field' USING ERRCODE='22023';
    END IF;

    IF p_action='create_draft' THEN
        IF v_tenant IS NULL OR NOT EXISTS (SELECT 1 FROM public.companies WHERE tenant_id=v_tenant AND deleted_at IS NULL) THEN
            RAISE EXCEPTION 'active quote tenant required' USING ERRCODE='22023';
        END IF;
        IF v_customer IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.tenant_users WHERE tenant_id=v_tenant AND user_id=v_customer
              AND removed_at IS NULL AND platform_suspended_at IS NULL
        ) THEN RAISE EXCEPTION 'customer must belong to quote tenant' USING ERRCODE='23503'; END IF;
        v_key := p->>'idempotency_key'; v_fingerprint := p->>'request_fingerprint';
        IF v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 200
           OR coalesce(v_fingerprint,'') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'valid idempotency identity required' USING ERRCODE='22023';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('custom_quote:'||v_tenant::text||':'||v_key,0));
        SELECT * INTO v_quote FROM public.billing_custom_quotes
         WHERE tenant_id=v_tenant AND idempotency_key=v_key FOR UPDATE;
        IF FOUND THEN
            IF v_quote.request_fingerprint <> v_fingerprint THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
            RETURN jsonb_build_object('quote_id',v_quote.quote_id,'state',v_quote.state,'idempotent',true);
        END IF;
        INSERT INTO public.billing_custom_quotes(tenant_id,customer_user_id,idempotency_key,request_fingerprint,created_by_user_id)
        VALUES(v_tenant,v_customer,v_key,v_fingerprint,v_actor) RETURNING * INTO v_quote;
        INSERT INTO public.billing_custom_quote_revisions(tenant_id,quote_id,revision_number,request_key,
            request_fingerprint,configuration,feature_quantities,commercial_terms,economic_inputs,fx_evidence,
            valid_until,created_by_user_id)
        VALUES(v_tenant,v_quote.quote_id,1,'initial',v_fingerprint,
            coalesce(p->'configuration','{}'::jsonb),coalesce(p->'feature_quantities','{}'::jsonb),
            coalesce(p->'commercial_terms','{}'::jsonb),coalesce(p->'economic_inputs','{}'::jsonb),
            coalesce(p->'fx_evidence','{}'::jsonb),nullif(p->>'valid_until','')::timestamptz,v_actor)
        RETURNING * INTO v_revision;
        UPDATE public.billing_custom_quotes SET current_revision_id=v_revision.revision_id WHERE quote_id=v_quote.quote_id;
        INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
        VALUES(v_tenant,v_quote.quote_id,v_revision.revision_id,v_actor,'draft_created',v_key,jsonb_build_object('revision_number',1));
        RETURN jsonb_build_object('quote_id',v_quote.quote_id,'revision_id',v_revision.revision_id,'state','draft','idempotent',false);

    ELSIF p_action='create_revision' THEN
        v_expected := (p->>'expected_revision')::integer;
        v_key := p->>'idempotency_key'; v_fingerprint := p->>'request_fingerprint';
        IF v_quote_id IS NULL OR v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 200
           OR coalesce(v_fingerprint,'') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'valid revision identity required' USING ERRCODE='22023';
        END IF;
        SELECT * INTO v_quote FROM public.billing_custom_quotes WHERE quote_id=v_quote_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'quote not found' USING ERRCODE='P0002'; END IF;
        v_tenant := v_quote.tenant_id;
        PERFORM pg_advisory_xact_lock(hashtextextended('custom_quote:'||v_tenant::text||':'||v_quote_id::text,0));
        SELECT * INTO v_revision FROM public.billing_custom_quote_revisions
         WHERE tenant_id=v_tenant AND quote_id=v_quote_id AND request_key=v_key;
        IF FOUND THEN
            IF v_revision.request_fingerprint <> v_fingerprint THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='23505'; END IF;
            RETURN jsonb_build_object('quote_id',v_quote_id,'revision_id',v_revision.revision_id,'revision_number',v_revision.revision_number,'idempotent',true);
        END IF;
        IF v_quote.state <> 'draft' OR v_quote.current_revision_id IS NULL THEN RAISE EXCEPTION 'only draft quotes can be revised' USING ERRCODE='55000'; END IF;
        SELECT * INTO v_revision FROM public.billing_custom_quote_revisions WHERE revision_id=v_quote.current_revision_id;
        IF v_expected IS DISTINCT FROM v_revision.revision_number THEN RAISE EXCEPTION 'stale quote revision' USING ERRCODE='40001'; END IF;
        v_next := v_expected + 1;
        INSERT INTO public.billing_custom_quote_revisions(tenant_id,quote_id,revision_number,request_key,request_fingerprint,
            configuration,feature_quantities,commercial_terms,economic_inputs,fx_evidence,valid_until,created_by_user_id)
        VALUES(v_tenant,v_quote_id,v_next,v_key,v_fingerprint,coalesce(p->'configuration','{}'::jsonb),
            coalesce(p->'feature_quantities','{}'::jsonb),coalesce(p->'commercial_terms','{}'::jsonb),
            coalesce(p->'economic_inputs','{}'::jsonb),coalesce(p->'fx_evidence','{}'::jsonb),
            nullif(p->>'valid_until','')::timestamptz,v_actor) RETURNING * INTO v_revision;
        UPDATE public.billing_custom_quotes SET current_revision_id=v_revision.revision_id,
            updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
        INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
        VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'revision_created',v_key,jsonb_build_object('revision_number',v_next));
        RETURN jsonb_build_object('quote_id',v_quote_id,'revision_id',v_revision.revision_id,'revision_number',v_next,'idempotent',false);

    ELSIF p_action IN ('submit','approve','accept','reject') THEN
        IF v_quote_id IS NULL THEN RAISE EXCEPTION 'quote identity required' USING ERRCODE='22023'; END IF;
        SELECT * INTO v_quote FROM public.billing_custom_quotes WHERE quote_id=v_quote_id FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'quote not found' USING ERRCODE='P0002'; END IF;
        v_tenant := v_quote.tenant_id;
        IF p_action IN ('accept','reject') AND v_tenant IS DISTINCT FROM v_context_tenant THEN
            RAISE EXCEPTION 'quote not found' USING ERRCODE='P0002';
        END IF;
        SELECT * INTO v_revision FROM public.billing_custom_quote_revisions
         WHERE tenant_id=v_tenant AND quote_id=v_quote_id AND revision_id=v_quote.current_revision_id FOR UPDATE;
        IF NOT FOUND OR (p->>'expected_revision')::integer IS DISTINCT FROM v_revision.revision_number THEN
            RAISE EXCEPTION 'stale quote revision' USING ERRCODE='40001';
        END IF;
        IF p_action='submit' THEN
            IF v_quote.state<>'draft' THEN RAISE EXCEPTION 'invalid quote transition' USING ERRCODE='55000'; END IF;
            UPDATE public.billing_custom_quotes SET state='submitted',updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
            INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
            VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'submitted',p->>'idempotency_key',jsonb_build_object('revision_number',v_revision.revision_number));
        ELSIF p_action='approve' THEN
            IF v_quote.state='approved' AND v_revision.state='approved' THEN RETURN jsonb_build_object('quote_id',v_quote_id,'state','approved','idempotent',true); END IF;
            IF v_quote.state<>'submitted' OR v_revision.state<>'draft' THEN RAISE EXCEPTION 'invalid quote transition' USING ERRCODE='55000'; END IF;
            v_key := nullif(btrim(p->>'approval_reference'),'');
            IF v_key IS NULL THEN RAISE EXCEPTION 'approval reference required' USING ERRCODE='22023'; END IF;
            IF v_revision.commercial_terms = '{}'::jsonb OR v_revision.economic_inputs = '{}'::jsonb THEN
                RAISE EXCEPTION 'explicit commercial terms and economic inputs are required for approval' USING ERRCODE='55000';
            END IF;
            UPDATE public.billing_custom_quote_revisions SET state='approved',approval_reference=v_key,
                approved_by_user_id=v_actor,approved_at=clock_timestamp(),finalized_at=clock_timestamp()
             WHERE revision_id=v_revision.revision_id;
            UPDATE public.billing_custom_quotes SET state='approved',updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
            INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
            VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'approved',coalesce(p->>'idempotency_key',v_key),
                   jsonb_build_object('approval_reference',v_key));
        ELSIF p_action='accept' THEN
            IF v_quote.state='accepted' AND v_revision.state='accepted' THEN RETURN jsonb_build_object('quote_id',v_quote_id,'state','accepted','idempotent',true,'access_activated',false); END IF;
            IF v_quote.state<>'approved' OR v_revision.state<>'approved' THEN RAISE EXCEPTION 'quote is not approved for acceptance' USING ERRCODE='55000'; END IF;
            IF v_revision.valid_until IS NOT NULL AND v_revision.valid_until<=clock_timestamp() THEN
                UPDATE public.billing_custom_quote_revisions SET state='expired',finalized_at=coalesce(finalized_at,clock_timestamp())
                 WHERE revision_id=v_revision.revision_id;
                UPDATE public.billing_custom_quotes SET state='expired',updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
                INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
                VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'expired',p->>'idempotency_key',
                       jsonb_build_object('revision_number',v_revision.revision_number,'access_activated',false));
                RETURN jsonb_build_object('quote_id',v_quote_id,'state','expired','idempotent',false,'access_activated',false);
            END IF;
            UPDATE public.billing_custom_quote_revisions SET state='accepted',accepted_by_user_id=v_actor,accepted_at=clock_timestamp()
             WHERE revision_id=v_revision.revision_id;
            UPDATE public.billing_custom_quotes SET state='accepted',updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
            INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
            VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'accepted',p->>'idempotency_key',jsonb_build_object('revision_number',v_revision.revision_number,'access_activated',false));
        ELSE
            IF v_quote.state='rejected' AND v_revision.state='rejected' THEN RETURN jsonb_build_object('quote_id',v_quote_id,'state','rejected','idempotent',true); END IF;
            IF v_quote.state NOT IN ('approved','submitted') OR v_revision.state NOT IN ('approved','draft') THEN
                RAISE EXCEPTION 'invalid quote transition' USING ERRCODE='55000';
            END IF;
            UPDATE public.billing_custom_quote_revisions SET state='rejected',rejected_by_user_id=v_actor,
                rejected_at=clock_timestamp(),finalized_at=coalesce(finalized_at,clock_timestamp()) WHERE revision_id=v_revision.revision_id;
            UPDATE public.billing_custom_quotes SET state='rejected',updated_at=clock_timestamp(),row_version=row_version+1 WHERE quote_id=v_quote_id;
            INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
            VALUES(v_tenant,v_quote_id,v_revision.revision_id,v_actor,'rejected',p->>'idempotency_key',jsonb_build_object('revision_number',v_revision.revision_number));
        END IF;
        SELECT state INTO v_role FROM public.billing_custom_quotes WHERE quote_id=v_quote_id;
        RETURN jsonb_build_object('quote_id',v_quote_id,'state',v_role,'idempotent',false,'access_activated',false);

    ELSIF p_action='checkout_prepare' THEN
        IF v_quote_id IS NULL THEN RAISE EXCEPTION 'quote identity required' USING ERRCODE='22023'; END IF;
        SELECT * INTO v_quote FROM public.billing_custom_quotes WHERE quote_id=v_quote_id FOR UPDATE;
        IF NOT FOUND OR v_quote.tenant_id<>v_context_tenant THEN RAISE EXCEPTION 'quote not found' USING ERRCODE='P0002'; END IF;
        IF v_quote.state<>'accepted' THEN RAISE EXCEPTION 'accepted quote required' USING ERRCODE='55000'; END IF;
        v_revision_id := v_quote.current_revision_id;
        v_key := p->>'idempotency_key'; v_fingerprint := p->>'request_fingerprint';
        IF v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 200
           OR coalesce(v_fingerprint,'') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'valid checkout identity required' USING ERRCODE='22023';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended('custom_checkout:'||v_context_tenant::text||':'||v_key,0));
        SELECT * INTO v_attempt FROM public.billing_custom_quote_checkout_attempts WHERE tenant_id=v_context_tenant AND idempotency_key=v_key FOR UPDATE;
        IF FOUND THEN
            IF v_attempt.request_fingerprint<>v_fingerprint OR v_attempt.quote_id<>v_quote_id OR v_attempt.revision_id<>v_revision_id THEN
                RAISE EXCEPTION 'checkout idempotency conflict' USING ERRCODE='23505';
            END IF;
            RETURN jsonb_build_object('attempt_id',v_attempt.attempt_id,'state',v_attempt.state,'idempotent',true,'provider_called',false);
        END IF;
        INSERT INTO public.billing_custom_quote_checkout_attempts(tenant_id,quote_id,revision_id,idempotency_key,request_fingerprint,created_by_user_id)
        VALUES(v_context_tenant,v_quote_id,v_revision_id,v_key,v_fingerprint,v_actor) RETURNING * INTO v_attempt;
        INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
        VALUES(v_context_tenant,v_quote_id,v_revision_id,v_actor,'checkout_prepared',v_key,jsonb_build_object('attempt_id',v_attempt.attempt_id,'provider_called',false));
        RETURN jsonb_build_object('attempt_id',v_attempt.attempt_id,'state','prepared','idempotent',false,'provider_called',false);

    ELSIF p_action='checkout_identity_update' THEN
        v_attempt_id := nullif(p->>'attempt_id','')::uuid;
        v_provider_event_id := nullif(p->>'provider_event_id','');
        IF v_attempt_id IS NULL OR v_provider_event_id IS NULL THEN
            RAISE EXCEPTION 'verified checkout event identity required' USING ERRCODE='22023';
        END IF;
        SELECT * INTO v_attempt FROM public.billing_custom_quote_checkout_attempts WHERE attempt_id=v_attempt_id FOR UPDATE;
        IF NOT FOUND OR v_attempt.tenant_id IS DISTINCT FROM v_context_tenant THEN
            RAISE EXCEPTION 'checkout attempt not found' USING ERRCODE='P0002';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.billing_custom_quotes q WHERE q.tenant_id=v_attempt.tenant_id
                       AND q.quote_id=v_attempt.quote_id AND q.current_revision_id=v_attempt.revision_id AND q.state='accepted') THEN
            RAISE EXCEPTION 'checkout attempt is not bound to the accepted current revision' USING ERRCODE='55000';
        END IF;
        SELECT event_type,payload INTO v_event_type,v_event_payload FROM public.billing_webhook_events
         WHERE stripe_event_id=v_provider_event_id AND tenant_id=v_attempt.tenant_id AND processed_at IS NOT NULL;
        IF NOT FOUND THEN RAISE EXCEPTION 'provider event has not been verified and processed' USING ERRCODE='42501'; END IF;
        SELECT evidence INTO v_result FROM public.billing_custom_quote_events
         WHERE tenant_id=v_attempt.tenant_id AND quote_id=v_attempt.quote_id
           AND action='checkout_identity_updated' AND idempotency_key=v_provider_event_id;
        IF FOUND THEN
            IF v_result->>'attempt_id' IS DISTINCT FROM v_attempt_id::text THEN
                RAISE EXCEPTION 'provider event already belongs to another checkout attempt' USING ERRCODE='23505';
            END IF;
            RETURN jsonb_build_object('attempt_id',v_attempt_id,'state',v_attempt.state,'idempotent',true);
        END IF;
        v_event_object := v_event_payload #> '{data,object}';
        v_event_attempt_id := coalesce(v_event_object->'metadata'->>'quote_attempt_id',v_event_object->>'client_reference_id',
            v_event_object->'parent'->'subscription_details'->'metadata'->>'quote_attempt_id',
            v_event_object->'subscription_details'->'metadata'->>'quote_attempt_id');
        IF v_event_attempt_id IS DISTINCT FROM v_attempt_id::text THEN
            RAISE EXCEPTION 'verified provider event is not bound to this quote attempt' USING ERRCODE='42501';
        END IF;
        IF v_event_type='checkout.session.completed' THEN
            IF v_event_object->>'mode' IS DISTINCT FROM 'subscription'
               OR coalesce(v_event_object->>'subscription','') !~ '^sub_[A-Za-z0-9]+$'
               OR coalesce(v_event_object->>'id','') !~ '^cs_(test|live)_[A-Za-z0-9]+$' THEN
                RAISE EXCEPTION 'provider checkout identity is incomplete' USING ERRCODE='22023';
            END IF;
            IF v_attempt.stripe_checkout_session_id IS NOT NULL AND v_attempt.stripe_checkout_session_id IS DISTINCT FROM v_event_object->>'id' THEN
                RAISE EXCEPTION 'checkout session identity conflict' USING ERRCODE='23505';
            END IF;
            IF v_attempt.stripe_subscription_id IS NOT NULL AND v_attempt.stripe_subscription_id IS DISTINCT FROM v_event_object->>'subscription' THEN
                RAISE EXCEPTION 'checkout subscription identity conflict' USING ERRCODE='23505';
            END IF;
            v_attempt_state := 'session_created'; v_provider_outcome := NULL;
        ELSIF v_event_type IN ('invoice.paid','invoice.payment_succeeded','invoice.payment_failed') THEN
            v_stripe_subscription_id := coalesce(v_event_object->>'subscription',
                v_event_object->'parent'->'subscription_details'->>'subscription',
                v_event_object->'subscription_details'->'subscription'->>'id');
            IF coalesce(v_event_object->>'billing_reason','') <> 'subscription_create'
               OR coalesce(v_event_object->>'id','') !~ '^in_[A-Za-z0-9]+$'
               OR v_attempt.stripe_subscription_id IS DISTINCT FROM v_stripe_subscription_id THEN
                RAISE EXCEPTION 'invoice is not the bound initial subscription invoice' USING ERRCODE='42501';
            END IF;
            IF v_event_type IN ('invoice.paid','invoice.payment_succeeded') THEN
                IF NOT EXISTS (SELECT 1 FROM public.billing_payments bp WHERE bp.tenant_id=v_attempt.tenant_id
                               AND bp.stripe_invoice_id=v_event_object->>'id'
                               AND bp.stripe_subscription_id=v_attempt.stripe_subscription_id AND bp.status='succeeded') THEN
                    RAISE EXCEPTION 'invoice settlement is not confirmed by billing authority' USING ERRCODE='55000';
                END IF;
                v_attempt_state := 'settled'; v_provider_outcome := 'settled';
            ELSE
                IF NOT EXISTS (SELECT 1 FROM public.billing_payments bp WHERE bp.tenant_id=v_attempt.tenant_id
                               AND bp.stripe_invoice_id=v_event_object->>'id'
                               AND bp.stripe_subscription_id=v_attempt.stripe_subscription_id AND bp.status='failed') THEN
                    RAISE EXCEPTION 'invoice failure is not confirmed by billing authority' USING ERRCODE='55000';
                END IF;
                v_attempt_state := 'failed'; v_provider_outcome := 'failed';
            END IF;
        ELSIF v_event_type='checkout.session.expired' THEN
            IF coalesce(v_event_object->>'id','') !~ '^cs_(test|live)_[A-Za-z0-9]+$'
               OR (v_attempt.stripe_checkout_session_id IS NOT NULL AND v_attempt.stripe_checkout_session_id IS DISTINCT FROM v_event_object->>'id') THEN
                RAISE EXCEPTION 'checkout expiry identity mismatch' USING ERRCODE='42501';
            END IF;
            v_attempt_state := 'cancelled'; v_provider_outcome := 'cancelled';
        ELSE
            RAISE EXCEPTION 'unsupported verified provider event for quote identity' USING ERRCODE='22023';
        END IF;
        UPDATE public.billing_custom_quote_checkout_attempts SET
            stripe_checkout_session_id=coalesce(stripe_checkout_session_id,CASE WHEN v_event_type LIKE 'checkout.session.%' THEN nullif(v_event_object->>'id','') END),
            stripe_subscription_id=coalesce(stripe_subscription_id,v_stripe_subscription_id,CASE WHEN v_event_type LIKE 'checkout.session.%' THEN nullif(v_event_object->>'subscription','') END),
            stripe_invoice_id=CASE WHEN v_event_type LIKE 'invoice.%' THEN coalesce(stripe_invoice_id,nullif(v_event_object->>'id','')) ELSE stripe_invoice_id END,
            provider_event_id=v_provider_event_id,provider_outcome=v_provider_outcome,state=v_attempt_state,
            updated_at=clock_timestamp()
        WHERE attempt_id=v_attempt_id RETURNING * INTO v_attempt;
        INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
        VALUES(v_attempt.tenant_id,v_attempt.quote_id,v_attempt.revision_id,NULL,'checkout_identity_updated',v_provider_event_id,
               jsonb_build_object('attempt_id',v_attempt_id,'provider_event_id',v_provider_event_id,'state',v_attempt.state,
               'checkout_session_id',v_attempt.stripe_checkout_session_id,'subscription_id',v_attempt.stripe_subscription_id,
               'invoice_id',v_attempt.stripe_invoice_id,'provider_outcome',v_attempt.provider_outcome));
        RETURN jsonb_build_object('attempt_id',v_attempt_id,'state',v_attempt.state,'provider_outcome',v_attempt.provider_outcome,'idempotent',false);
    END IF;
    RAISE EXCEPTION 'unsupported quote command' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_command(TEXT,JSONB) FROM PUBLIC;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION public.billing_custom_quote_command(TEXT,JSONB) TO ceopro_app;
    END IF;
END $$;
