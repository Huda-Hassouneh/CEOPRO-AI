-- Preserve Python's existing, explicitly authorized whole-company deletion.
-- Ordinary request/evidence/product deletion remains forbidden by immutability.
ALTER TABLE public.keel_pricing_request_results
 DROP CONSTRAINT keel_pricing_request_results_tenant_id_actor_id_fkey,
 ADD CONSTRAINT keel_pricing_request_results_tenant_id_actor_id_fkey
 FOREIGN KEY(tenant_id,actor_id) REFERENCES public.tenant_users(tenant_id,user_id) ON DELETE CASCADE,
 DROP CONSTRAINT keel_pricing_request_results_tenant_id_product_id_fkey,
 ADD CONSTRAINT keel_pricing_request_results_tenant_id_product_id_fkey
 FOREIGN KEY(tenant_id,product_id) REFERENCES public.products(tenant_id,product_id) ON DELETE CASCADE,
 DROP CONSTRAINT keel_pricing_request_results_evidence_id_fkey,
 ADD CONSTRAINT keel_pricing_request_results_evidence_id_fkey
 FOREIGN KEY(evidence_id) REFERENCES public.evidence_records(evidence_id) ON DELETE CASCADE;
CREATE OR REPLACE FUNCTION public.keel_pricing_request_immutable() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM public.companies WHERE tenant_id=OLD.tenant_id) THEN
   RETURN OLD; -- FK cascade only after the parent company was deleted.
 END IF;
 RAISE EXCEPTION 'pricing request results are immutable' USING ERRCODE='55000';
END $$;
