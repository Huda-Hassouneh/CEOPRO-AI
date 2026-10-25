-- Versioned, fail-closed Custom Plan pricing configuration.
-- No commercial values are seeded. Owner-authorized configuration is required.
ALTER TABLE public.billing_custom_quote_revisions
    ADD COLUMN IF NOT EXISTS pricing_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(pricing_snapshot) = 'object');

CREATE TABLE IF NOT EXISTS public.billing_custom_pricing_policies (
    policy_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
    quote_currency CHAR(3) NOT NULL DEFAULT 'USD' CHECK (quote_currency = 'USD'),
    target_gross_margin NUMERIC(8,6),
    enforce_vendor_cost_ratio_floor BOOLEAN,
    max_vendor_cost_revenue_ratio NUMERIC(8,6),
    fixed_platform_fee_usd NUMERIC(18,6),
    upward_rounding_increment_usd NUMERIC(18,6),
    monthly_shared_infrastructure_cost_usd NUMERIC(18,6),
    active_paying_tenant_count BIGINT,
    custom_term_discount_percent NUMERIC(8,6) NOT NULL DEFAULT 0,
    effective_from TIMESTAMPTZ,
    effective_to TIMESTAMPTZ,
    approved_by TEXT,
    approval_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (target_gross_margin IS NULL OR target_gross_margin >= 0 AND target_gross_margin < 1),
    CHECK (max_vendor_cost_revenue_ratio IS NULL OR max_vendor_cost_revenue_ratio > 0 AND max_vendor_cost_revenue_ratio <= 1),
    CHECK (fixed_platform_fee_usd IS NULL OR fixed_platform_fee_usd >= 0),
    CHECK (upward_rounding_increment_usd IS NULL OR upward_rounding_increment_usd >= 0),
    CHECK (monthly_shared_infrastructure_cost_usd IS NULL OR monthly_shared_infrastructure_cost_usd >= 0),
    CHECK (active_paying_tenant_count IS NULL OR active_paying_tenant_count > 0),
    CHECK (custom_term_discount_percent = 0),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from),
    CHECK (status <> 'active' OR (effective_from IS NOT NULL AND approved_by IS NOT NULL
                                  AND approval_evidence IS NOT NULL AND length(btrim(approval_evidence)) > 0))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_custom_pricing_one_active
    ON public.billing_custom_pricing_policies ((status)) WHERE status = 'active';

-- Maps canonical feature allowances to the existing verified provider cost
-- schedule. Multipliers/reserves are intentionally nullable: NULL means not
-- configured; approved 1.0/zero remain explicit values.
CREATE TABLE IF NOT EXISTS public.billing_custom_cost_bindings (
    binding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_version_id UUID NOT NULL REFERENCES public.billing_custom_pricing_policies(policy_version_id) ON DELETE RESTRICT,
    feature_code TEXT NOT NULL REFERENCES public.usage_features(feature_code) ON DELETE RESTRICT,
    cost_category TEXT NOT NULL CHECK (cost_category IN ('vendor','infrastructure')),
    budget_kind VARCHAR(10) NOT NULL CHECK (budget_kind IN ('data','ai')),
    provider VARCHAR(60) NOT NULL,
    operation VARCHAR(120) NOT NULL,
    unit VARCHAR(30) NOT NULL,
    usage_basis TEXT NOT NULL CHECK (usage_basis IN ('enabled_feature','limit_value')),
    units_per_feature_unit NUMERIC(24,8) NOT NULL CHECK (units_per_feature_unit > 0),
    operational_multiplier NUMERIC(18,8),
    variability_reserve NUMERIC(18,8),
    required_for_price BOOLEAN NOT NULL DEFAULT TRUE,
    usage_assumption JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(usage_assumption) = 'object'),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    source TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (operational_multiplier IS NULL OR operational_multiplier > 0),
    CHECK (variability_reserve IS NULL OR variability_reserve >= 1),
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    FOREIGN KEY (budget_kind, provider, operation, unit)
        REFERENCES public.provider_cost_schedules(budget_kind, provider, operation, unit) ON DELETE RESTRICT,
    UNIQUE (policy_version_id, feature_code, cost_category, provider, operation, unit, effective_from)
);
CREATE INDEX IF NOT EXISTS idx_billing_custom_cost_bindings_effective
    ON public.billing_custom_cost_bindings(policy_version_id, feature_code, effective_from, effective_to);

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['billing_custom_pricing_policies','billing_custom_cost_bindings'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', t);
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ceopro_app') THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM ceopro_app', t);
    END IF;
  END LOOP;
END $$;

CREATE POLICY billing_custom_pricing_active_read ON public.billing_custom_pricing_policies FOR SELECT TO ceopro_app USING (status = 'active' AND effective_from <= clock_timestamp() AND (effective_to IS NULL OR effective_to > clock_timestamp()));
CREATE POLICY billing_custom_cost_binding_active_read ON public.billing_custom_cost_bindings FOR SELECT TO ceopro_app USING (EXISTS (SELECT 1 FROM public.billing_custom_pricing_policies p WHERE p.policy_version_id = billing_custom_cost_bindings.policy_version_id AND p.status = 'active' AND p.effective_from <= clock_timestamp() AND (p.effective_to IS NULL OR p.effective_to > clock_timestamp())));
GRANT SELECT ON public.billing_custom_pricing_policies, public.billing_custom_cost_bindings TO ceopro_app;
CREATE OR REPLACE FUNCTION public.billing_custom_quote_approval_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF NEW.state='approved' AND OLD.state IS DISTINCT FROM 'approved' THEN
    IF coalesce(NEW.pricing_snapshot->>'pricingStatus','') <> 'calculated'
       OR coalesce(NEW.pricing_snapshot->>'pricingPolicyVersionId','') = ''
       OR coalesce(NEW.pricing_snapshot->>'calculationHash','') !~ '^[0-9a-f]{64}$'
       OR coalesce(NEW.commercial_terms->>'currency','') <> 'USD'
       OR coalesce(NEW.commercial_terms->>'monthlyPriceUsd','') !~ '^[0-9]+(\.[0-9]{1,2})?$'
       OR coalesce(NEW.commercial_terms->>'billingPeriodMonths','') !~ '^[1-9][0-9]*$'
       OR coalesce(NEW.pricing_snapshot #>> '{calculation,recommendedPrice}','')::numeric <> coalesce(NEW.commercial_terms->>'monthlyPriceUsd','0')::numeric
       OR NEW.approval_reference IS NULL OR NEW.approved_by_user_id IS NULL THEN
      RAISE EXCEPTION 'verified pricing snapshot and explicit USD terms are required for approval' USING ERRCODE='55000';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.billing_custom_pricing_policies p
      WHERE p.policy_version_id=(NEW.pricing_snapshot->>'pricingPolicyVersionId')::uuid
        AND p.status='active' AND p.effective_from<=clock_timestamp()
        AND (p.effective_to IS NULL OR p.effective_to>clock_timestamp())) THEN
      RAISE EXCEPTION 'pricing snapshot policy is stale; create and calculate a new quote revision' USING ERRCODE='55000';
    END IF;
    NEW.approved_at := coalesce(NEW.approved_at, clock_timestamp());
    NEW.valid_until := NEW.approved_at + interval '336 hours';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS billing_custom_quote_approval_guard ON public.billing_custom_quote_revisions;
CREATE TRIGGER billing_custom_quote_approval_guard
    BEFORE UPDATE OF state ON public.billing_custom_quote_revisions
    FOR EACH ROW EXECUTE FUNCTION public.billing_custom_quote_approval_guard();
REVOKE ALL ON FUNCTION public.billing_custom_quote_approval_guard() FROM PUBLIC;

-- Preserve read-only tenant access to the new immutable pricing evidence.
GRANT SELECT (pricing_snapshot) ON public.billing_custom_quote_revisions TO ceopro_app;






CREATE OR REPLACE FUNCTION public.billing_custom_pricing_policy_immutable_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'custom pricing policy versions cannot be deleted' USING ERRCODE='55000';
  END IF;
  IF OLD.status='draft' AND NEW.status IN ('draft','active') THEN
    IF NEW.version_number IS DISTINCT FROM OLD.version_number OR NEW.policy_version_id IS DISTINCT FROM OLD.policy_version_id THEN
      RAISE EXCEPTION 'custom pricing policy identity is immutable' USING ERRCODE='55000';
    END IF;
    IF NEW.status='active' AND (NEW.target_gross_margin IS NULL OR NEW.enforce_vendor_cost_ratio_floor IS NULL
       OR NEW.fixed_platform_fee_usd IS NULL OR NEW.upward_rounding_increment_usd IS NULL
       OR NEW.monthly_shared_infrastructure_cost_usd IS NULL
       OR (NEW.monthly_shared_infrastructure_cost_usd > 0 AND NEW.active_paying_tenant_count IS NULL)
       OR (NEW.enforce_vendor_cost_ratio_floor AND NEW.max_vendor_cost_revenue_ratio IS NULL)) THEN
      RAISE EXCEPTION 'all required custom pricing policy inputs must be explicitly configured' USING ERRCODE='22023';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status='active' AND NEW.status='retired'
     AND NEW.policy_version_id=OLD.policy_version_id AND NEW.version_number=OLD.version_number
     AND NEW.quote_currency=OLD.quote_currency AND NEW.target_gross_margin IS NOT DISTINCT FROM OLD.target_gross_margin
     AND NEW.enforce_vendor_cost_ratio_floor IS NOT DISTINCT FROM OLD.enforce_vendor_cost_ratio_floor
     AND NEW.max_vendor_cost_revenue_ratio IS NOT DISTINCT FROM OLD.max_vendor_cost_revenue_ratio
     AND NEW.fixed_platform_fee_usd IS NOT DISTINCT FROM OLD.fixed_platform_fee_usd
     AND NEW.upward_rounding_increment_usd IS NOT DISTINCT FROM OLD.upward_rounding_increment_usd
     AND NEW.monthly_shared_infrastructure_cost_usd IS NOT DISTINCT FROM OLD.monthly_shared_infrastructure_cost_usd
     AND NEW.active_paying_tenant_count IS NOT DISTINCT FROM OLD.active_paying_tenant_count
     AND NEW.custom_term_discount_percent=OLD.custom_term_discount_percent
     AND NEW.effective_from=OLD.effective_from AND NEW.approved_by=OLD.approved_by
     AND NEW.approval_evidence=OLD.approval_evidence AND NEW.created_at=OLD.created_at
     AND NEW.effective_to IS NOT NULL AND NEW.effective_to > OLD.effective_from THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'active or retired custom pricing policy versions are immutable; create a new version' USING ERRCODE='55000';
END $$;
DROP TRIGGER IF EXISTS billing_custom_pricing_policy_immutable_guard ON public.billing_custom_pricing_policies;
CREATE TRIGGER billing_custom_pricing_policy_immutable_guard
    BEFORE UPDATE OR DELETE ON public.billing_custom_pricing_policies
    FOR EACH ROW EXECUTE FUNCTION public.billing_custom_pricing_policy_immutable_guard();

CREATE OR REPLACE FUNCTION public.billing_custom_cost_binding_immutable_guard()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE policy_status TEXT;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'custom pricing cost bindings are immutable; create a new policy version' USING ERRCODE='55000';
  END IF;
  SELECT status INTO policy_status FROM public.billing_custom_pricing_policies
   WHERE policy_version_id=NEW.policy_version_id;
  IF policy_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'cost bindings can be added only to a draft pricing policy' USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS billing_custom_cost_binding_immutable_guard ON public.billing_custom_cost_bindings;
CREATE TRIGGER billing_custom_cost_binding_immutable_guard
    BEFORE INSERT OR UPDATE OR DELETE ON public.billing_custom_cost_bindings
    FOR EACH ROW EXECUTE FUNCTION public.billing_custom_cost_binding_immutable_guard();
REVOKE ALL ON FUNCTION public.billing_custom_pricing_policy_immutable_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.billing_custom_cost_binding_immutable_guard() FROM PUBLIC;
