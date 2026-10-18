-- Stable external sale-line identities. Never infer identity from sale amounts.
CREATE TABLE public.import_sale_identities (
  tenant_id uuid NOT NULL,
  source_system varchar(100) NOT NULL,
  sale_id varchar(200) NOT NULL,
  transaction_id uuid NOT NULL,
  payload_sha256 char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, source_system, sale_id),
  FOREIGN KEY (tenant_id, transaction_id) REFERENCES public.transactions(tenant_id, transaction_id) ON DELETE CASCADE
);
ALTER TABLE public.import_sale_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.import_sale_identities FORCE ROW LEVEL SECURITY;
CREATE POLICY import_sale_tenant ON public.import_sale_identities TO ceopro_app
  USING (tenant_id = public.get_current_tenant()) WITH CHECK (tenant_id = public.get_current_tenant());
-- Existing ingestion worker is the trusted cross-tenant background identity.
CREATE POLICY import_sale_worker ON public.import_sale_identities TO ceopro_ingestion_worker USING (EXISTS (SELECT 1 FROM public.companies c WHERE c.tenant_id = import_sale_identities.tenant_id AND c.deleted_at IS NULL AND c.business_type IS DISTINCT FROM 'platform')); 
REVOKE ALL ON public.import_sale_identities FROM PUBLIC;
GRANT SELECT ON public.import_sale_identities TO ceopro_app;
GRANT SELECT, INSERT ON public.import_sale_identities TO ceopro_ingestion_worker;
