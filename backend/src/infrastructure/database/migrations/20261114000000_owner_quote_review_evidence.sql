-- Extend the existing owner-only read capability; no financial state or grants change.
CREATE OR REPLACE FUNCTION public.billing_custom_quote_admin_detail(p_quote UUID)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_result JSONB;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
  OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m
    JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
    WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
   RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
 END IF;
 SELECT jsonb_build_object(
   'quote_id',q.quote_id,'tenant_id',q.tenant_id,'customer_user_id',q.customer_user_id,
   'business_name',c.business_name,'state',q.state,'row_version',q.row_version,
   'created_at',q.created_at,'updated_at',q.updated_at,'current_revision_id',q.current_revision_id,
   'revision_number',r.revision_number,'revision_state',r.state,'configuration',r.configuration,
   'feature_quantities',r.feature_quantities,'commercial_terms',r.commercial_terms,
   'economic_inputs',r.economic_inputs,'fx_evidence',r.fx_evidence,'pricing_snapshot',r.pricing_snapshot,
   'valid_until',r.valid_until,'approval_reference',r.approval_reference,'approved_at',r.approved_at,'accepted_at',r.accepted_at,
   'currentRevision',jsonb_build_object('revisionId',r.revision_id,'revisionNumber',r.revision_number,
     'state',r.state,'configuration',r.configuration,'featureQuantities',r.feature_quantities,
     'commercialTerms',r.commercial_terms,'economicInputs',r.economic_inputs,'fxEvidence',r.fx_evidence,
     'pricingSnapshot',r.pricing_snapshot,'validUntil',r.valid_until,'approvedAt',r.approved_at,'acceptedAt',r.accepted_at),
   'events',coalesce((SELECT jsonb_agg(jsonb_build_object('action',e.action,'created_at',e.created_at,'evidence',e.evidence)
     ORDER BY e.created_at,e.event_id) FROM public.billing_custom_quote_events e
     WHERE e.tenant_id=q.tenant_id AND e.quote_id=q.quote_id),'[]'::jsonb),
   'revisions',coalesce((SELECT jsonb_agg(jsonb_build_object('revision_number',h.revision_number,'state',h.state,
     'configuration',h.configuration,'feature_quantities',h.feature_quantities,'commercial_terms',h.commercial_terms,
     'pricing_snapshot',h.pricing_snapshot,'valid_until',h.valid_until,'approved_at',h.approved_at,'accepted_at',h.accepted_at)
     ORDER BY h.revision_number) FROM public.billing_custom_quote_revisions h
     WHERE h.tenant_id=q.tenant_id AND h.quote_id=q.quote_id),'[]'::jsonb),
   'checkout_attempts',coalesce((SELECT jsonb_agg(jsonb_build_object('attempt_id',a.attempt_id,'revision_id',a.revision_id,
     'state',a.state,'stripe_checkout_session_id',a.stripe_checkout_session_id,'stripe_subscription_id',a.stripe_subscription_id,
     'stripe_invoice_id',a.stripe_invoice_id,'provider_outcome',a.provider_outcome,'last_error_code',a.last_error_code,
     'created_at',a.created_at,'updated_at',a.updated_at) ORDER BY a.created_at,a.attempt_id)
     FROM public.billing_custom_quote_checkout_attempts a WHERE a.tenant_id=q.tenant_id AND a.quote_id=q.quote_id),'[]'::jsonb)
 ) INTO v_result
 FROM public.billing_custom_quotes q JOIN public.companies c ON c.tenant_id=q.tenant_id
 JOIN public.billing_custom_quote_revisions r ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id AND r.revision_id=q.current_revision_id
 WHERE q.quote_id=p_quote;
 RETURN v_result;
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_admin_detail(UUID) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_quote_admin_detail(UUID) TO ceopro_app;
END IF; END $$;
