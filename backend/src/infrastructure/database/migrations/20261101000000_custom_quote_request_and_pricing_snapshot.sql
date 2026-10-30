-- Forward-only extension of the target's existing quote command and event vocabulary.
ALTER TABLE public.billing_custom_quote_events DROP CONSTRAINT IF EXISTS billing_custom_quote_events_action_check;
ALTER TABLE public.billing_custom_quote_events ADD CONSTRAINT billing_custom_quote_events_action_check CHECK (action IN
 ('draft_created','revision_created','submitted','approved','accepted','rejected','expired','pricing_calculated',
  'checkout_prepared','checkout_identity_updated','contract_activated'));

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

    IF p_action IN ('create_draft','create_revision','submit','approve','admin_list','admin_reject') THEN
        IF v_platform_role IS DISTINCT FROM 'owner'
           OR NOT EXISTS (SELECT 1 FROM public.keel_platform_workspace WHERE tenant_id=v_context_tenant) THEN
            RAISE EXCEPTION 'Platform Owner permission required' USING ERRCODE='42501';
        END IF;
    ELSIF p_action='request' THEN
        IF v_tenant IS NULL OR v_tenant IS DISTINCT FROM v_context_tenant OR v_customer IS DISTINCT FROM v_actor THEN
            RAISE EXCEPTION 'request must belong to the authenticated customer' USING ERRCODE='42501';
        END IF;
        SELECT role_key INTO v_role FROM public.tenant_users
         WHERE tenant_id=v_tenant AND user_id=v_actor AND removed_at IS NULL
           AND platform_suspended_at IS NULL;
        IF v_role IS NULL OR v_role NOT IN ('owner','admin','accountant') THEN
            RAISE EXCEPTION 'billing role required' USING ERRCODE='42501';
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

    IF p_action IN ('create_draft','create_revision','request')
       AND NOT public.keel_custom_quote_json_secret_free(p) THEN
        RAISE EXCEPTION 'quote snapshot contains a secret-like field' USING ERRCODE='22023';
    END IF;

    IF p_action='admin_list' THEN
        IF nullif(p->>'state','') IS NOT NULL
           AND p->>'state' NOT IN ('draft','submitted','approved','accepted','rejected','expired') THEN
            RAISE EXCEPTION 'invalid quote state filter' USING ERRCODE='22023';
        END IF;
        v_expected := coalesce(nullif(p->>'limit','')::integer,50);
        IF v_expected NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'invalid quote list limit' USING ERRCODE='22023'; END IF;
        SELECT coalesce(jsonb_agg(rows.quote_row ORDER BY rows.updated_at DESC,rows.quote_id DESC),'[]'::jsonb)
          INTO v_result
          FROM (
            SELECT q.updated_at,q.quote_id,
                   jsonb_build_object(
                     'quoteId',q.quote_id,'tenantId',q.tenant_id,'businessName',c.business_name,
                     'customerUserId',q.customer_user_id,'state',q.state,'rowVersion',q.row_version,
                     'createdAt',q.created_at,'updatedAt',q.updated_at,
                     'currentRevision',CASE WHEN r.revision_id IS NULL THEN NULL ELSE jsonb_build_object(
                       'revisionId',r.revision_id,'revisionNumber',r.revision_number,'state',r.state,
                       'configuration',r.configuration,'featureQuantities',r.feature_quantities,
                       'commercialTerms',r.commercial_terms,'economicInputs',r.economic_inputs,
                       'fxEvidence',r.fx_evidence,'validUntil',r.valid_until,
                       'approvalReference',r.approval_reference,'approvedAt',r.approved_at,
                       'acceptedAt',r.accepted_at) END,
                     'events',coalesce((SELECT jsonb_agg(jsonb_build_object(
                         'action',e.action,'createdAt',e.created_at,'evidence',e.evidence)
                         ORDER BY e.created_at,e.event_id)
                       FROM public.billing_custom_quote_events e WHERE e.tenant_id=q.tenant_id AND e.quote_id=q.quote_id),'[]'::jsonb)
                   ) AS quote_row
              FROM public.billing_custom_quotes q
              JOIN public.companies c ON c.tenant_id=q.tenant_id
              LEFT JOIN public.billing_custom_quote_revisions r
                ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id AND r.revision_id=q.current_revision_id
             WHERE (nullif(p->>'state','') IS NULL OR q.state=p->>'state')
               AND (nullif(p->>'quote_id','') IS NULL OR q.quote_id=nullif(p->>'quote_id','')::uuid)
             ORDER BY q.updated_at DESC,q.quote_id DESC LIMIT v_expected
          ) rows;
        RETURN jsonb_build_object('quotes',v_result);
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
        IF v_quote.state NOT IN ('draft','submitted') OR v_quote.current_revision_id IS NULL THEN
            RAISE EXCEPTION 'only draft or submitted requests can be revised' USING ERRCODE='55000';
        END IF;
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

    ELSIF p_action='request' THEN
        IF v_tenant IS NULL OR NOT EXISTS (SELECT 1 FROM public.companies WHERE tenant_id=v_tenant AND deleted_at IS NULL) THEN
            RAISE EXCEPTION 'active quote tenant required' USING ERRCODE='22023';
        END IF;
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
        INSERT INTO public.billing_custom_quotes(tenant_id,customer_user_id,state,idempotency_key,request_fingerprint,created_by_user_id)
        VALUES(v_tenant,v_actor,'submitted',v_key,v_fingerprint,v_actor) RETURNING * INTO v_quote;
        INSERT INTO public.billing_custom_quote_revisions(tenant_id,quote_id,revision_number,request_key,
            request_fingerprint,configuration,feature_quantities,commercial_terms,economic_inputs,fx_evidence,created_by_user_id)
        VALUES(v_tenant,v_quote.quote_id,1,'initial',v_fingerprint,
            coalesce(p->'configuration','{}'::jsonb),coalesce(p->'feature_quantities','{}'::jsonb),
            '{}'::jsonb,'{}'::jsonb,'{}'::jsonb,v_actor)
        RETURNING * INTO v_revision;
        UPDATE public.billing_custom_quotes SET current_revision_id=v_revision.revision_id WHERE quote_id=v_quote.quote_id;
        INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
        VALUES(v_tenant,v_quote.quote_id,v_revision.revision_id,v_actor,'submitted',v_key,
               jsonb_build_object('source','customer_request','revision_number',1,'price_calculated',false));
        RETURN jsonb_build_object('quote_id',v_quote.quote_id,'revision_id',v_revision.revision_id,'state','submitted','idempotent',false,'price_calculated',false,'access_activated',false);

    ELSIF p_action IN ('submit','approve','accept','reject','admin_reject') THEN
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
            IF (p_action='admin_reject' AND v_quote.state<>'submitted')
               OR (p_action='reject' AND v_quote.state NOT IN ('approved','submitted'))
               OR v_revision.state NOT IN ('approved','draft') THEN
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
