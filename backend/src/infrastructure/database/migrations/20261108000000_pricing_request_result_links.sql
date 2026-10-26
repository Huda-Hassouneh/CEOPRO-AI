-- Additive retry identity linked to the existing pricing evidence authority.
CREATE TABLE public.keel_pricing_request_results(
 tenant_id uuid NOT NULL,actor_id uuid NOT NULL,request_key text NOT NULL CHECK(length(request_key) BETWEEN 1 AND 200),
 product_id uuid NOT NULL,evidence_id uuid NOT NULL REFERENCES public.evidence_records(evidence_id),
 response jsonb NOT NULL CHECK(jsonb_typeof(response)='object'),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(tenant_id,actor_id,request_key),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES public.tenant_users(tenant_id,user_id),
 FOREIGN KEY(tenant_id,product_id) REFERENCES public.products(tenant_id,product_id)
);
ALTER TABLE public.keel_pricing_request_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_pricing_request_results FORCE ROW LEVEL SECURITY;
CREATE POLICY pricing_request_read ON public.keel_pricing_request_results FOR SELECT TO ceopro_app
 USING(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY pricing_request_insert ON public.keel_pricing_request_results FOR INSERT TO ceopro_app
 WITH CHECK(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid
 AND EXISTS(SELECT 1 FROM public.evidence_records e WHERE e.tenant_id=keel_pricing_request_results.tenant_id
 AND e.evidence_id=keel_pricing_request_results.evidence_id AND e.source_module='ai.pricing'
 AND e.source_record_ids->>'product_id'=keel_pricing_request_results.product_id::text));
REVOKE ALL ON public.keel_pricing_request_results FROM PUBLIC,ceopro_app;
GRANT SELECT,INSERT ON public.keel_pricing_request_results TO ceopro_app;
CREATE FUNCTION public.keel_pricing_request_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'pricing request results are immutable' USING ERRCODE='55000'; END $$;
CREATE TRIGGER pricing_request_immutable BEFORE UPDATE OR DELETE ON public.keel_pricing_request_results
 FOR EACH ROW EXECUTE FUNCTION public.keel_pricing_request_immutable();
