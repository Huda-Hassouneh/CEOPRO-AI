-- Forward-only pricing request/reservation ledger. Runtime remains NOBYPASSRLS.
CREATE TABLE public.pricing_requests (
  tenant_id uuid NOT NULL, user_id uuid NOT NULL, request_id uuid NOT NULL,
  product_id uuid NOT NULL, usage_record_id uuid NOT NULL,
  status text NOT NULL CHECK(status IN ('pending','completed','failed')),
  charged boolean NOT NULL DEFAULT false,
  response jsonb, failure_code text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now()+interval '10 minutes'),
  completed_at timestamptz,
  PRIMARY KEY(tenant_id,user_id,request_id),
  -- Keep creator/product identifiers as audit metadata. Deleting a member or
  -- product must not cascade away a pending reservation before its refund.
  FOREIGN KEY(tenant_id) REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
  FOREIGN KEY(usage_record_id) REFERENCES public.subscription_usage(id) ON DELETE CASCADE,
  CHECK ((status='completed' AND response IS NOT NULL) OR (status<>'completed' AND response IS NULL)),
  CHECK (NOT charged OR status='completed')
);
CREATE INDEX idx_pricing_history ON public.pricing_requests(tenant_id,product_id,created_at DESC);
CREATE INDEX idx_pricing_expiry ON public.pricing_requests(tenant_id,expires_at) WHERE status='pending';
-- Different members cannot run competing generations for the same product.
CREATE UNIQUE INDEX uq_pricing_pending_product ON public.pricing_requests(tenant_id,product_id) WHERE status='pending';
ALTER TABLE public.pricing_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pricing_requests FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.pricing_requests FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.pricing_requests TO ceopro_app;
CREATE POLICY pricing_requests_tenant ON public.pricing_requests TO ceopro_app
  USING(tenant_id=public.get_current_tenant())
  WITH CHECK(tenant_id=public.get_current_tenant() AND EXISTS (
    SELECT 1 FROM public.subscription_usage usage
    JOIN public.subscriptions subscription ON subscription.id=usage.subscription_id
    JOIN public.features feature ON feature.feature_id=usage.feature_id
    WHERE usage.id=pricing_requests.usage_record_id
      AND subscription.tenant_id=pricing_requests.tenant_id AND feature.feature_code='ai_pricing'
  ));
