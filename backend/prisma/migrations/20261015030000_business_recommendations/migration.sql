CREATE TABLE public.business_recommendation_runs (
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 user_id uuid NOT NULL,request_id uuid NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','completed','failed')),
 response jsonb,created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT(now()+interval '5 minutes'),
 PRIMARY KEY(tenant_id,user_id,request_id)
);
CREATE UNIQUE INDEX uq_business_recommendation_pending ON public.business_recommendation_runs(tenant_id) WHERE status='pending';
CREATE TABLE public.business_recommendations (
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
 recommendation_id uuid NOT NULL DEFAULT gen_random_uuid(),logical_key uuid NOT NULL,episode_id uuid NOT NULL DEFAULT gen_random_uuid(),
 product_id uuid,rule_id text NOT NULL,category text NOT NULL,priority text NOT NULL CHECK(priority IN ('high','medium','low')),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','dismissed','resolved')),
 body jsonb NOT NULL,source_fingerprint char(64) NOT NULL,evidence_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),last_seen_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,recommendation_id),UNIQUE(tenant_id,logical_key),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES public.evidence_records(tenant_id,evidence_id) ON DELETE RESTRICT
);
CREATE INDEX idx_business_recommendation_feed ON public.business_recommendations(tenant_id,state,updated_at DESC);
ALTER TABLE public.business_recommendation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_recommendation_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.business_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_recommendations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.business_recommendation_runs,public.business_recommendations FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.business_recommendation_runs,public.business_recommendations TO ceopro_app;
CREATE POLICY business_recommendations_tenant ON public.business_recommendations TO ceopro_app
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE POLICY business_recommendation_runs_tenant ON public.business_recommendation_runs TO ceopro_app
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
