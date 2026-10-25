-- Owner-only administration and immutable, versioned Custom Plan cost inputs.
-- The tables start empty. This migration supplies no commercial defaults.
CREATE TABLE IF NOT EXISTS public.billing_custom_cost_rates (
    cost_rate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data','ai')),
    provider VARCHAR(60) NOT NULL,
    operation VARCHAR(120) NOT NULL,
    unit VARCHAR(30) NOT NULL CHECK (unit IN ('request','record','page','input_token','output_token','cache_read_token','cache_write_token','image')),
    unit_cost_usd NUMERIC(20,12) NOT NULL CHECK (unit_cost_usd >= 0),
    source TEXT NOT NULL CHECK (length(btrim(source)) > 0),
    verified_at DATE NOT NULL,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    verified_by TEXT NOT NULL CHECK (length(btrim(verified_by)) > 0),
    verification_evidence TEXT NOT NULL CHECK (length(btrim(verification_evidence)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE INDEX IF NOT EXISTS idx_billing_custom_cost_rates_lookup
 ON public.billing_custom_cost_rates(budget_kind,provider,operation,unit,effective_from,effective_to);
ALTER TABLE public.billing_custom_cost_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_custom_cost_rates FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_custom_cost_rates FROM PUBLIC,ceopro_app;
DROP POLICY IF EXISTS billing_custom_cost_rates_active_read ON public.billing_custom_cost_rates;
CREATE POLICY billing_custom_cost_rates_owner_read ON public.billing_custom_cost_rates FOR SELECT TO ceopro_app
 USING(effective_from<=clock_timestamp() AND (effective_to IS NULL OR effective_to>clock_timestamp())
   AND EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w
      ON w.tenant_id=public.get_current_tenant() WHERE m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
      AND m.role_key='owner' AND m.status='active')
   AND NOT EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
      AND u.platform_disabled_at IS NOT NULL));
GRANT SELECT ON public.billing_custom_cost_rates TO ceopro_app;

-- Provider rates, cost bindings and margin policy are private financial data.
-- Only the active Platform Owner in its platform workspace may read them.
DROP POLICY IF EXISTS billing_custom_pricing_active_read ON public.billing_custom_pricing_policies;
DROP POLICY IF EXISTS billing_custom_cost_binding_active_read ON public.billing_custom_cost_bindings;
CREATE POLICY billing_custom_pricing_owner_read ON public.billing_custom_pricing_policies FOR SELECT TO ceopro_app
 USING(EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w
   ON w.tenant_id=public.get_current_tenant() WHERE m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
   AND m.role_key='owner' AND m.status='active')
   AND NOT EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
   AND u.platform_disabled_at IS NOT NULL));
CREATE POLICY billing_custom_cost_binding_owner_read ON public.billing_custom_cost_bindings FOR SELECT TO ceopro_app
 USING(EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w
   ON w.tenant_id=public.get_current_tenant() WHERE m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
   AND m.role_key='owner' AND m.status='active')
   AND NOT EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
   AND u.platform_disabled_at IS NOT NULL));

ALTER TABLE public.billing_custom_cost_bindings
 ADD COLUMN IF NOT EXISTS cost_rate_id UUID REFERENCES public.billing_custom_cost_rates(cost_rate_id) ON DELETE RESTRICT;
ALTER TABLE public.billing_custom_cost_bindings
 DROP CONSTRAINT IF EXISTS billing_custom_cost_bindings_budget_kind_provider_operation_unit_fkey;

CREATE OR REPLACE FUNCTION public.billing_custom_binding_effective_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_custom_cost_rates%ROWTYPE;
BEGIN
 SELECT * INTO r FROM public.billing_custom_cost_rates WHERE cost_rate_id=NEW.cost_rate_id;
 IF NOT FOUND OR r.budget_kind<>NEW.budget_kind OR r.provider<>NEW.provider OR r.operation<>NEW.operation OR r.unit<>NEW.unit
    OR NEW.effective_from<r.effective_from OR (r.effective_to IS NOT NULL AND
       (NEW.effective_to IS NULL OR NEW.effective_to>r.effective_to)) OR length(btrim(NEW.source))=0 THEN
   RAISE EXCEPTION 'binding must match its verified rate and effective interval' USING ERRCODE='23514';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('custom_binding:'||NEW.policy_version_id::text||':'||NEW.feature_code||':'||NEW.cost_category||':'||NEW.provider||':'||NEW.operation||':'||NEW.unit,0));
 IF EXISTS(SELECT 1 FROM public.billing_custom_cost_bindings b WHERE b.policy_version_id=NEW.policy_version_id
   AND b.feature_code=NEW.feature_code AND b.cost_category=NEW.cost_category AND b.provider=NEW.provider
   AND b.operation=NEW.operation AND b.unit=NEW.unit
   AND tstzrange(b.effective_from,b.effective_to,'[)') && tstzrange(NEW.effective_from,NEW.effective_to,'[)')) THEN
   RAISE EXCEPTION 'overlapping effective pricing bindings' USING ERRCODE='23P01';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS billing_custom_binding_effective_guard ON public.billing_custom_cost_bindings;
CREATE TRIGGER billing_custom_binding_effective_guard BEFORE INSERT ON public.billing_custom_cost_bindings
 FOR EACH ROW EXECUTE FUNCTION public.billing_custom_binding_effective_guard();
REVOKE ALL ON FUNCTION public.billing_custom_binding_effective_guard() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.billing_custom_pricing_immutable_rate_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'verified pricing rates cannot be deleted' USING ERRCODE='55000'; END IF;
 IF OLD.effective_to IS NULL AND NEW.effective_to IS NOT NULL
    AND (to_jsonb(NEW)-'effective_to')=(to_jsonb(OLD)-'effective_to') AND NEW.effective_to>OLD.effective_from THEN
   RETURN NEW;
 END IF;
 RAISE EXCEPTION 'verified pricing rates are immutable; create a new effective version' USING ERRCODE='55000';
END $$;
DROP TRIGGER IF EXISTS billing_custom_pricing_immutable_rate_guard ON public.billing_custom_cost_rates;
CREATE TRIGGER billing_custom_pricing_immutable_rate_guard BEFORE UPDATE OR DELETE ON public.billing_custom_cost_rates
 FOR EACH ROW EXECUTE FUNCTION public.billing_custom_pricing_immutable_rate_guard();
REVOKE ALL ON FUNCTION public.billing_custom_pricing_immutable_rate_guard() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.billing_custom_pricing_admin_command(p_action TEXT,p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_policy UUID; v_rate UUID; v_binding UUID; v_row RECORD; v_count INTEGER; v_result JSONB;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
    OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
                  WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
    OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
   RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501';
 END IF;
 IF p_action='policy_list' THEN
   SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.version_number DESC),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_pricing_policies p;
   RETURN jsonb_build_object('policies',v_result);
 ELSIF p_action='rate_list' THEN
   SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.provider,r.operation,r.unit,r.effective_from),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_cost_rates r;
   RETURN jsonb_build_object('cost_rates',v_result);
 ELSIF p_action='binding_list' THEN
   v_policy:=(p->>'policy_version_id')::uuid;
   SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.feature_code,b.cost_category,b.effective_from),'[]'::jsonb) INTO v_result
    FROM public.billing_custom_cost_bindings b WHERE b.policy_version_id=v_policy;
   RETURN jsonb_build_object('bindings',v_result);
 ELSIF p_action='policy_create' THEN
   INSERT INTO public.billing_custom_pricing_policies(quote_currency,target_gross_margin,enforce_vendor_cost_ratio_floor,
     max_vendor_cost_revenue_ratio,fixed_platform_fee_usd,upward_rounding_increment_usd,
     monthly_shared_infrastructure_cost_usd,active_paying_tenant_count,approved_by,approval_evidence)
   VALUES('USD',nullif(p->>'target_gross_margin','')::numeric,nullif(p->>'enforce_vendor_cost_ratio_floor','')::boolean,
     nullif(p->>'max_vendor_cost_revenue_ratio','')::numeric,nullif(p->>'fixed_platform_fee_usd','')::numeric,
     nullif(p->>'upward_rounding_increment_usd','')::numeric,nullif(p->>'monthly_shared_infrastructure_cost_usd','')::numeric,
     nullif(p->>'active_paying_tenant_count','')::bigint,v_actor::text,nullif(btrim(p->>'approval_evidence'),''))
   RETURNING policy_version_id INTO v_policy;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_policy_draft_created','pricing_policy',jsonb_build_object('policy_version_id',v_policy),v_actor::text,
      coalesce(nullif(p->>'approval_evidence',''),'Draft policy setup'));
   RETURN jsonb_build_object('policy_version_id',v_policy,'status','draft');
 ELSIF p_action='rate_create' THEN
   PERFORM pg_advisory_xact_lock(hashtextextended('custom_cost_rate:'||(p->>'budget_kind')||':'||lower(btrim(p->>'provider'))||':'||lower(btrim(p->>'operation'))||':'||(p->>'unit'),0));
   INSERT INTO public.billing_custom_cost_rates(budget_kind,provider,operation,unit,unit_cost_usd,source,verified_at,
      effective_from,effective_to,verified_by,verification_evidence)
   VALUES(p->>'budget_kind',lower(btrim(p->>'provider')),lower(btrim(p->>'operation')),p->>'unit',
      (p->>'unit_cost_usd')::numeric,nullif(btrim(p->>'source'),''),(p->>'verified_at')::date,
      (p->>'effective_from')::timestamptz,nullif(p->>'effective_to','')::timestamptz,v_actor::text,
      nullif(btrim(p->>'verification_evidence'),'')) RETURNING cost_rate_id INTO v_rate;
   IF EXISTS(SELECT 1 FROM public.billing_custom_cost_rates r WHERE r.cost_rate_id<>v_rate
      AND (r.budget_kind,r.provider,r.operation,r.unit)=(p->>'budget_kind',lower(btrim(p->>'provider')),
       lower(btrim(p->>'operation')),p->>'unit')
      AND tstzrange(r.effective_from,r.effective_to,'[)') && tstzrange((p->>'effective_from')::timestamptz,
       nullif(p->>'effective_to','')::timestamptz,'[)')) THEN
     RAISE EXCEPTION 'overlapping provider rate effective dates' USING ERRCODE='23P01';
   END IF;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_rate_created','pricing_cost_rate',jsonb_build_object('cost_rate_id',v_rate,
      'provider',p->>'provider','operation',p->>'operation','unit',p->>'unit'),v_actor::text,p->>'verification_evidence');
   RETURN jsonb_build_object('cost_rate_id',v_rate,'status','verified');
 ELSIF p_action='rate_close' THEN
   v_rate:=(p->>'cost_rate_id')::uuid;
   UPDATE public.billing_custom_cost_rates SET effective_to=(p->>'effective_to')::timestamptz
    WHERE cost_rate_id=v_rate AND effective_to IS NULL
      AND (p->>'effective_to')::timestamptz>effective_from
      AND (p->>'effective_to')::timestamptz IS NOT NULL;
   IF NOT FOUND THEN RAISE EXCEPTION 'current rate or valid close date required' USING ERRCODE='55000'; END IF;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_rate_closed','pricing_cost_rate',jsonb_build_object('cost_rate_id',v_rate,
      'effective_to',p->>'effective_to'),v_actor::text,coalesce(nullif(p->>'reason',''),'Rate version closed'));
   RETURN jsonb_build_object('cost_rate_id',v_rate,'status','closed');
 ELSIF p_action='binding_create' THEN
   v_policy:=(p->>'policy_version_id')::uuid; v_rate:=(p->>'cost_rate_id')::uuid;
   IF NOT EXISTS(SELECT 1 FROM public.billing_custom_pricing_policies WHERE policy_version_id=v_policy AND status='draft') THEN
      RAISE EXCEPTION 'bindings require a draft pricing policy' USING ERRCODE='55000'; END IF;
   IF NOT EXISTS(SELECT 1 FROM public.billing_custom_cost_rates WHERE cost_rate_id=v_rate
      AND effective_from <= clock_timestamp() AND (effective_to IS NULL OR effective_to>clock_timestamp())) THEN
      RAISE EXCEPTION 'effective verified cost rate required' USING ERRCODE='22023'; END IF;
   SELECT * INTO v_row FROM public.billing_custom_cost_rates WHERE cost_rate_id=v_rate;
   INSERT INTO public.billing_custom_cost_bindings(policy_version_id,feature_code,cost_category,budget_kind,provider,
     operation,unit,usage_basis,units_per_feature_unit,operational_multiplier,variability_reserve,required_for_price,
     usage_assumption,effective_from,effective_to,source,created_by,cost_rate_id)
   VALUES(v_policy,p->>'feature_code',p->>'cost_category',v_row.budget_kind,v_row.provider,v_row.operation,v_row.unit,
     p->>'usage_basis',(p->>'units_per_feature_unit')::numeric,nullif(p->>'operational_multiplier','')::numeric,
     nullif(p->>'variability_reserve','')::numeric,coalesce((p->>'required_for_price')::boolean,true),
     coalesce(p->'usage_assumption','{}'::jsonb),greatest((p->>'effective_from')::timestamptz,v_row.effective_from),
     CASE WHEN p->>'effective_to' IS NULL OR p->>'effective_to'='' THEN v_row.effective_to ELSE (p->>'effective_to')::timestamptz END,
     nullif(btrim(p->>'source'),''),v_actor::text,v_rate) RETURNING binding_id INTO v_binding;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_binding_created','pricing_binding',jsonb_build_object('binding_id',v_binding,
      'policy_version_id',v_policy,'cost_rate_id',v_rate,'feature_code',p->>'feature_code'),v_actor::text,p->>'source');
   RETURN jsonb_build_object('binding_id',v_binding,'status','draft');
 ELSIF p_action='policy_activate' THEN
   v_policy:=(p->>'policy_version_id')::uuid;
   SELECT * INTO v_row FROM public.billing_custom_pricing_policies WHERE policy_version_id=v_policy FOR UPDATE;
   IF NOT FOUND OR v_row.status<>'draft' THEN RAISE EXCEPTION 'draft policy required' USING ERRCODE='55000'; END IF;
   SELECT count(*) INTO v_count FROM public.billing_custom_cost_bindings b LEFT JOIN public.billing_custom_cost_rates r ON r.cost_rate_id=b.cost_rate_id
    WHERE b.policy_version_id=v_policy AND b.required_for_price AND (r.cost_rate_id IS NULL OR r.verified_at>CURRENT_DATE
      OR r.effective_from>clock_timestamp() OR (r.effective_to IS NOT NULL AND r.effective_to<=clock_timestamp()));
   IF v_count>0 THEN RAISE EXCEPTION 'all required bindings need effective verified rates' USING ERRCODE='22023'; END IF;
   IF EXISTS(SELECT 1 FROM public.billing_custom_cost_bindings b WHERE b.policy_version_id=v_policy AND b.required_for_price
      GROUP BY b.feature_code,b.cost_category HAVING count(*)=0) THEN RAISE EXCEPTION 'invalid policy bindings' USING ERRCODE='22023'; END IF;
   UPDATE public.billing_custom_pricing_policies SET status='retired',effective_to=clock_timestamp()
    WHERE status='active' AND effective_to IS NULL;
   UPDATE public.billing_custom_pricing_policies SET status='active',effective_from=coalesce(effective_from,clock_timestamp()),
     approved_by=v_actor::text,approval_evidence=nullif(btrim(p->>'approval_evidence'), '') WHERE policy_version_id=v_policy;
   INSERT INTO public.entitlement_audit_log(tenant_id,action,subject,new_value,approved_by,reason)
    VALUES(v_tenant,'custom_pricing_policy_activated','pricing_policy',jsonb_build_object('policy_version_id',v_policy,
      'version',v_row.version_number),v_actor::text,p->>'approval_evidence');
   RETURN jsonb_build_object('policy_version_id',v_policy,'status','active');
 END IF;
 RAISE EXCEPTION 'unsupported pricing administration command' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_pricing_admin_command(TEXT,JSONB) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_pricing_admin_command(TEXT,JSONB) TO ceopro_app; END IF; END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_quote_admin_detail(p_quote UUID)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid; v_result JSONB;
BEGIN
 IF v_actor IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
  OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
   WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner')
  OR EXISTS(SELECT 1 FROM public.users u WHERE u.user_id=v_actor AND u.platform_disabled_at IS NOT NULL) THEN
  RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501'; END IF;
 SELECT jsonb_build_object('quoteId',q.quote_id,'tenantId',q.tenant_id,'customerUserId',q.customer_user_id,
   'state',q.state,'rowVersion',q.row_version,'currentRevision',jsonb_build_object('revisionId',r.revision_id,
    'revisionNumber',r.revision_number,'state',r.state,'configuration',r.configuration,
    'featureQuantities',r.feature_quantities,'commercialTerms',r.commercial_terms,
    'economicInputs',r.economic_inputs,'fxEvidence',r.fx_evidence,'pricingSnapshot',r.pricing_snapshot,
    'validUntil',r.valid_until,'approvalReference',r.approval_reference,'approvedAt',r.approved_at))
   INTO v_result FROM public.billing_custom_quotes q JOIN public.billing_custom_quote_revisions r
    ON r.tenant_id=q.tenant_id AND r.quote_id=q.quote_id AND r.revision_id=q.current_revision_id
   WHERE q.quote_id=p_quote;
 RETURN v_result;
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_admin_detail(UUID) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_quote_admin_detail(UUID) TO ceopro_app; END IF; END $$;

-- Allow precisely one transition from an empty quote pricing snapshot to a
-- server-calculated snapshot on the current draft revision. All other terms
-- remain immutable; calculation changes require a new quote revision.
CREATE OR REPLACE FUNCTION public.billing_custom_quote_revision_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN
   IF pg_trigger_depth()>1 THEN RETURN OLD; END IF;
   RAISE EXCEPTION 'custom quote revisions cannot be deleted' USING ERRCODE='42501';
 END IF;
 IF (NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id AND NEW.created_by_user_id IS NOT NULL)
    OR (NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id AND NEW.approved_by_user_id IS NOT NULL AND NOT(OLD.approved_by_user_id IS NULL AND NEW.state='approved'))
    OR (NEW.accepted_by_user_id IS DISTINCT FROM OLD.accepted_by_user_id AND NEW.accepted_by_user_id IS NOT NULL AND NOT(OLD.accepted_by_user_id IS NULL AND NEW.state='accepted'))
    OR (NEW.rejected_by_user_id IS DISTINCT FROM OLD.rejected_by_user_id AND NEW.rejected_by_user_id IS NOT NULL AND NOT(OLD.rejected_by_user_id IS NULL AND NEW.state='rejected')) THEN
   RAISE EXCEPTION 'quote actors are immutable' USING ERRCODE='42501';
 END IF;
 IF NEW.pricing_snapshot IS DISTINCT FROM OLD.pricing_snapshot THEN
   IF OLD.pricing_snapshot<>'{}'::jsonb OR NEW.pricing_snapshot->>'pricingStatus'<>'calculated' OR NEW.state<>'draft'
      OR NOT EXISTS(SELECT 1 FROM public.billing_custom_quote_revisions r WHERE r.revision_id=NEW.revision_id AND r.state='draft') THEN
      RAISE EXCEPTION 'pricing snapshot may be attached once to a draft revision' USING ERRCODE='42501';
   END IF;
 END IF;
 IF NEW.pricing_snapshot IS DISTINCT FROM OLD.pricing_snapshot THEN
   IF (to_jsonb(NEW)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
        'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at','pricing_snapshot','commercial_terms','economic_inputs'])
     <> (to_jsonb(OLD)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
        'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at','pricing_snapshot','commercial_terms','economic_inputs']) THEN
     RAISE EXCEPTION 'custom quote revision snapshots are immutable; create a new revision' USING ERRCODE='42501';
   END IF;
   IF NEW.commercial_terms->>'currency'<>'USD'
      OR NEW.commercial_terms->>'monthlyPriceUsd' IS DISTINCT FROM NEW.pricing_snapshot #>> '{calculation,recommendedPrice}'
      OR NEW.commercial_terms->>'billingPeriodMonths'<>'1'
      OR NEW.economic_inputs IS DISTINCT FROM NEW.pricing_snapshot THEN
     RAISE EXCEPTION 'commercial terms must be derived from calculated pricing snapshot' USING ERRCODE='55000';
   END IF;
 ELSE
   IF (to_jsonb(NEW)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
        'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at'])
     <> (to_jsonb(OLD)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at',
        'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at'])
      AND NOT (
        OLD.state='draft' AND NEW.state='approved'
        AND NEW.approved_at IS NOT NULL
        AND NEW.valid_until=NEW.approved_at + interval '336 hours'
        AND (to_jsonb(NEW)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at','valid_until',
             'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at'])
          = (to_jsonb(OLD)-ARRAY['state','approval_reference','created_by_user_id','approved_by_user_id','approved_at','valid_until',
             'accepted_by_user_id','accepted_at','rejected_by_user_id','rejected_at','finalized_at'])
      ) THEN
     RAISE EXCEPTION 'custom quote revision snapshots are immutable; create a new revision' USING ERRCODE='42501';
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_quote_pricing_command(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_quote UUID:=(p->>'quote_id')::uuid; v_snapshot JSONB:=p->'pricing_snapshot'; v_revision UUID; v_policy UUID;
BEGIN
 IF v_actor IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant)
  OR NOT EXISTS(SELECT 1 FROM public.keel_platform_members m JOIN public.keel_platform_workspace w ON w.tenant_id=v_tenant
   WHERE m.user_id=v_actor AND m.status='active' AND m.role_key='owner') THEN
  RAISE EXCEPTION 'active Platform Owner context required' USING ERRCODE='42501'; END IF;
 IF coalesce(v_snapshot->>'pricingStatus','')<>'calculated' OR coalesce(v_snapshot->>'calculationHash','') !~ '^[0-9a-f]{64}$'
   THEN RAISE EXCEPTION 'authoritative calculated snapshot required' USING ERRCODE='22023'; END IF;
 IF coalesce(v_snapshot #>> '{calculation,recommendedPrice}','') !~ '^[0-9]+(\.[0-9]{1,2})?$' THEN
   RAISE EXCEPTION 'positive, cent-precision Custom checkout price required' USING ERRCODE='22023'; END IF;
 IF (v_snapshot #>> '{calculation,recommendedPrice}')::numeric<=0 THEN
   RAISE EXCEPTION 'positive, cent-precision Custom checkout price required' USING ERRCODE='22023'; END IF;
 v_policy:=(v_snapshot->>'pricingPolicyVersionId')::uuid;
 IF NOT EXISTS(SELECT 1 FROM public.billing_custom_pricing_policies p WHERE p.policy_version_id=v_policy AND p.status='active'
   AND p.effective_from<=clock_timestamp() AND (p.effective_to IS NULL OR p.effective_to>clock_timestamp())) THEN
   RAISE EXCEPTION 'pricing policy is no longer effective' USING ERRCODE='55000'; END IF;
 PERFORM 1 FROM public.billing_custom_quotes q WHERE q.quote_id=v_quote AND q.state='submitted' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'submitted quote required' USING ERRCODE='55000'; END IF;
 SELECT current_revision_id INTO v_revision FROM public.billing_custom_quotes WHERE quote_id=v_quote;
 UPDATE public.billing_custom_quote_revisions SET pricing_snapshot=v_snapshot,
  commercial_terms=jsonb_build_object('currency','USD','monthlyPriceUsd',v_snapshot #>> '{calculation,recommendedPrice}',
                                      'billingPeriodMonths',1),
  economic_inputs=v_snapshot
  WHERE revision_id=v_revision AND state='draft' AND pricing_snapshot='{}'::jsonb;
 IF NOT FOUND THEN RAISE EXCEPTION 'revision already priced or no longer current; create a new revision' USING ERRCODE='55000'; END IF;
 INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,evidence)
  SELECT tenant_id,quote_id,v_revision,v_actor,'pricing_calculated',jsonb_build_object('policy_version_id',v_policy,'calculation_hash',v_snapshot->>'calculationHash')
  FROM public.billing_custom_quotes WHERE quote_id=v_quote;
 RETURN jsonb_build_object('quote_id',v_quote,'revision_id',v_revision,'pricing_status','calculated');
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_quote_pricing_command(JSONB) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_quote_pricing_command(JSONB) TO ceopro_app; END IF; END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_quote_approval_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.state='approved' AND OLD.state IS DISTINCT FROM 'approved' THEN
  IF coalesce(NEW.pricing_snapshot->>'pricingStatus','')<>'calculated'
    OR coalesce(NEW.pricing_snapshot->>'pricingPolicyVersionId','')=''
    OR coalesce(NEW.pricing_snapshot->>'calculationHash','') !~ '^[0-9a-f]{64}$'
    OR NEW.commercial_terms->>'currency'<>'USD'
    OR coalesce(NEW.commercial_terms->>'monthlyPriceUsd','') !~ '^[0-9]+(\.[0-9]{1,2})?$'
    OR NEW.commercial_terms->>'billingPeriodMonths'<>'1'
    OR NEW.pricing_snapshot #>> '{calculation,recommendedPrice}' IS DISTINCT FROM NEW.commercial_terms->>'monthlyPriceUsd'
    OR NEW.approval_reference IS NULL OR NEW.approved_by_user_id IS NULL THEN
    RAISE EXCEPTION 'verified price snapshot and explicit USD monthly terms required' USING ERRCODE='55000'; END IF;
   IF (NEW.commercial_terms->>'monthlyPriceUsd')::numeric<=0 THEN
    RAISE EXCEPTION 'verified price snapshot and explicit USD monthly terms required' USING ERRCODE='55000'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.billing_custom_pricing_policies p
     WHERE p.policy_version_id=(NEW.pricing_snapshot->>'pricingPolicyVersionId')::uuid AND p.status='active'
       AND p.effective_from<=clock_timestamp() AND (p.effective_to IS NULL OR p.effective_to>clock_timestamp())) THEN
    RAISE EXCEPTION 'pricing policy is stale; calculate a new revision' USING ERRCODE='55000'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(NEW.pricing_snapshot->'rates','[]'::jsonb)) item
    WHERE NOT EXISTS(SELECT 1 FROM public.billing_custom_cost_rates r
      WHERE r.cost_rate_id=(item.value->>'providerScheduleId')::uuid
       AND r.unit_cost_usd::text=item.value->>'unitCostUsd' AND r.source=item.value->>'source'
       AND r.verified_at=(item.value->>'providerVerifiedAt')::date
       AND r.effective_from<=clock_timestamp() AND (r.effective_to IS NULL OR r.effective_to>clock_timestamp()))
     AND NOT EXISTS(SELECT 1 FROM public.provider_cost_schedules r
      WHERE r.schedule_id=(item.value->>'providerScheduleId')::uuid
       AND r.unit_cost_usd::text=item.value->>'unitCostUsd' AND r.source=item.value->>'source'
       AND r.verified_at=(item.value->>'providerVerifiedAt')::date
       AND r.updated_at=(item.value->>'providerUpdatedAt')::timestamptz)) THEN
    RAISE EXCEPTION 'one or more snapshot rates are no longer current or verified' USING ERRCODE='55000'; END IF;
  NEW.approved_at:=coalesce(NEW.approved_at,clock_timestamp());
  NEW.valid_until:=NEW.approved_at+interval '14 days';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_checkout_prepare(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_quote UUID:=(p->>'quote_id')::uuid; v_key TEXT:=p->>'idempotency_key'; v_fingerprint TEXT:=p->>'request_fingerprint';
 v_quote_row public.billing_custom_quotes%ROWTYPE; v_revision public.billing_custom_quote_revisions%ROWTYPE;
 v_attempt public.billing_custom_quote_checkout_attempts%ROWTYPE; v_role TEXT; v_open_attempt_count INTEGER;
BEGIN
 IF v_actor IS NULL OR v_tenant IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant) THEN
  RAISE EXCEPTION 'active tenant context required' USING ERRCODE='42501'; END IF;
 SELECT role_key INTO v_role FROM public.tenant_users WHERE tenant_id=v_tenant AND user_id=v_actor
  AND removed_at IS NULL AND platform_suspended_at IS NULL;
 IF v_role NOT IN ('owner','admin','accountant') THEN RAISE EXCEPTION 'billing role required' USING ERRCODE='42501'; END IF;
 IF v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 200 OR coalesce(v_fingerprint,'') !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'valid idempotency identity required' USING ERRCODE='22023'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('custom_checkout:'||v_tenant::text||':'||v_key,0));
 SELECT * INTO v_quote_row FROM public.billing_custom_quotes WHERE tenant_id=v_tenant AND quote_id=v_quote FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'quote not found' USING ERRCODE='P0002'; END IF;
 SELECT * INTO v_revision FROM public.billing_custom_quote_revisions WHERE tenant_id=v_tenant AND quote_id=v_quote
  AND revision_id=v_quote_row.current_revision_id FOR UPDATE;
 IF v_quote_row.state<>'accepted' OR v_revision.state<>'accepted' OR v_revision.valid_until IS NULL
  OR v_revision.valid_until<=clock_timestamp() OR v_revision.pricing_snapshot->>'pricingStatus'<>'calculated'
  OR v_revision.commercial_terms->>'currency'<>'USD' THEN
  RAISE EXCEPTION 'accepted, current, priced and unexpired quote required' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM public.billing_subscriptions WHERE tenant_id=v_tenant
    AND status IN ('active','trialing','past_due','pending','payment_failed','paused')) THEN
  RAISE EXCEPTION 'a current subscription already exists' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM public.tenant_plan_assignments WHERE tenant_id=v_tenant AND source='contract'
    AND status IN ('active','trialing','past_due','pending','payment_failed','paused')) THEN
  RAISE EXCEPTION 'an active manual contract must be resolved before Custom Checkout' USING ERRCODE='55000'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('custom_checkout_revision:'||v_tenant::text||':'||v_revision.revision_id::text,0));
 SELECT count(*) INTO v_open_attempt_count FROM public.billing_custom_quote_checkout_attempts WHERE tenant_id=v_tenant
   AND revision_id=v_revision.revision_id AND state IN ('prepared','session_created','outcome_unknown','reconciliation_required');
 IF v_open_attempt_count>1 THEN RAISE EXCEPTION 'multiple active Checkout attempts require operator reconciliation' USING ERRCODE='55000'; END IF;
 SELECT * INTO v_attempt FROM public.billing_custom_quote_checkout_attempts WHERE tenant_id=v_tenant
   AND revision_id=v_revision.revision_id AND state IN ('prepared','session_created','outcome_unknown','reconciliation_required') FOR UPDATE;
 IF FOUND THEN
  RETURN jsonb_build_object('attempt_id',v_attempt.attempt_id,'state',v_attempt.state,'idempotent',true,
    'tenant_id',v_tenant,'quote_id',v_quote,'revision_id',v_revision.revision_id,
    'commercial_terms',v_revision.commercial_terms,'configuration',v_revision.configuration,'feature_quantities',v_revision.feature_quantities);
 END IF;
 SELECT * INTO v_attempt FROM public.billing_custom_quote_checkout_attempts WHERE tenant_id=v_tenant AND idempotency_key=v_key FOR UPDATE;
 IF FOUND THEN
  IF v_attempt.request_fingerprint<>v_fingerprint OR v_attempt.quote_id<>v_quote OR v_attempt.revision_id<>v_revision.revision_id THEN
   RAISE EXCEPTION 'checkout idempotency conflict' USING ERRCODE='23505'; END IF;
  RETURN jsonb_build_object('attempt_id',v_attempt.attempt_id,'state',v_attempt.state,'idempotent',true,
    'tenant_id',v_tenant,'quote_id',v_quote,'revision_id',v_revision.revision_id,
    'commercial_terms',v_revision.commercial_terms,'configuration',v_revision.configuration,'feature_quantities',v_revision.feature_quantities);
 END IF;
 INSERT INTO public.billing_custom_quote_checkout_attempts(tenant_id,quote_id,revision_id,idempotency_key,request_fingerprint,created_by_user_id)
 VALUES(v_tenant,v_quote,v_revision.revision_id,v_key,v_fingerprint,v_actor) RETURNING * INTO v_attempt;
 INSERT INTO public.billing_custom_quote_events(tenant_id,quote_id,revision_id,actor_user_id,action,idempotency_key,evidence)
 VALUES(v_tenant,v_quote,v_revision.revision_id,v_actor,'checkout_prepared',v_key,jsonb_build_object('attempt_id',v_attempt.attempt_id,'provider_called',false));
 RETURN jsonb_build_object('attempt_id',v_attempt.attempt_id,'state','prepared','idempotent',false,
   'tenant_id',v_tenant,'quote_id',v_quote,'revision_id',v_revision.revision_id,
   'commercial_terms',v_revision.commercial_terms,'configuration',v_revision.configuration,'feature_quantities',v_revision.feature_quantities);
END $$;

CREATE OR REPLACE FUNCTION public.billing_custom_checkout_record_session(p JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE v_actor UUID:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 v_tenant UUID:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 v_attempt UUID:=(p->>'attempt_id')::uuid; v_session TEXT:=p->>'session_id'; v_row public.billing_custom_quote_checkout_attempts%ROWTYPE;
BEGIN
 IF v_actor IS NULL OR NOT public.keel_active_principal(v_actor,v_tenant) THEN RAISE EXCEPTION 'active tenant context required' USING ERRCODE='42501'; END IF;
 IF coalesce(v_session,'') !~ '^cs_(test|live)_[A-Za-z0-9]+$' THEN RAISE EXCEPTION 'valid Checkout session identity required' USING ERRCODE='22023'; END IF;
 SELECT * INTO v_row FROM public.billing_custom_quote_checkout_attempts WHERE attempt_id=v_attempt AND tenant_id=v_tenant FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.billing_custom_quotes q JOIN public.billing_custom_quote_revisions r
   ON r.revision_id=q.current_revision_id WHERE q.quote_id=v_row.quote_id AND q.tenant_id=v_tenant
   AND q.state='accepted' AND r.state='accepted' AND r.valid_until>clock_timestamp()) THEN
   RAISE EXCEPTION 'active accepted quote attempt required' USING ERRCODE='55000'; END IF;
 IF v_row.stripe_checkout_session_id IS NOT NULL AND v_row.stripe_checkout_session_id<>v_session THEN
  RAISE EXCEPTION 'Checkout session identity conflict' USING ERRCODE='23505'; END IF;
 UPDATE public.billing_custom_quote_checkout_attempts SET stripe_checkout_session_id=v_session,state='session_created',updated_at=clock_timestamp()
  WHERE attempt_id=v_attempt AND state IN ('prepared','session_created');
 IF NOT FOUND THEN RAISE EXCEPTION 'checkout attempt is not retryable' USING ERRCODE='55000'; END IF;
 RETURN jsonb_build_object('attempt_id',v_attempt,'session_id',v_session,'state','session_created');
END $$;

REVOKE ALL ON FUNCTION public.billing_custom_checkout_prepare(JSONB),public.billing_custom_checkout_record_session(JSONB) FROM PUBLIC;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
 GRANT EXECUTE ON FUNCTION public.billing_custom_checkout_prepare(JSONB),public.billing_custom_checkout_record_session(JSONB) TO ceopro_app; END IF; END $$;
