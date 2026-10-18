-- Additive, tenant-isolated provider state. No existing records are rewritten.
CREATE TABLE public.store_connections (
 tenant_id UUID NOT NULL, source_id UUID NOT NULL, actor_id UUID NOT NULL,
 version UUID NOT NULL DEFAULT gen_random_uuid(), credentials TEXT,
 status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','SYNCING','CONNECTED','ERROR','PAUSED','DISCONNECTED')),
 currency VARCHAR(3) NOT NULL, next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_success_at TIMESTAMPTZ, last_error TEXT,
 progress JSONB NOT NULL DEFAULT '{}', lease_token UUID, lease_until TIMESTAMPTZ,
 attempts INT NOT NULL DEFAULT 0 CHECK(attempts>=0), job_id UUID,
 PRIMARY KEY(tenant_id,source_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.data_sources(tenant_id,source_id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,actor_id) REFERENCES public.tenant_users(tenant_id,user_id),
 FOREIGN KEY(tenant_id,job_id) REFERENCES public.ingestion_jobs(tenant_id,job_id)
);
CREATE TABLE public.store_product_links (
 tenant_id UUID NOT NULL, source_id UUID NOT NULL, external_id TEXT NOT NULL,
 product_id UUID NOT NULL, owns_product BOOLEAN NOT NULL,
 PRIMARY KEY(tenant_id,source_id,external_id), UNIQUE(tenant_id,source_id,product_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,product_id) REFERENCES public.products(tenant_id,product_id)
);
CREATE TABLE public.store_sale_links (
 tenant_id UUID NOT NULL, source_id UUID NOT NULL, order_id TEXT NOT NULL, line_id TEXT NOT NULL,
 transaction_id UUID NOT NULL,
 PRIMARY KEY(tenant_id,source_id,order_id,line_id), UNIQUE(tenant_id,transaction_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,transaction_id) REFERENCES public.transactions(tenant_id,transaction_id)
);
DO $$ DECLARE relation TEXT; BEGIN
 FOREACH relation IN ARRAY ARRAY['store_connections','store_product_links','store_sale_links'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation);
  EXECUTE format('CREATE POLICY store_tenant ON public.%I TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',relation);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',relation);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO ceopro_app',relation);
 END LOOP;
END $$;
-- Reuse the existing restricted scheduler identity for discovery metadata only.
-- No credential/progress access and no canonical business-data write grants.
CREATE POLICY store_due_discovery ON public.store_connections FOR SELECT TO ceopro_market_dispatcher USING(true);
GRANT SELECT(tenant_id,source_id,actor_id,next_run_at,lease_until,status,attempts) ON public.store_connections TO ceopro_market_dispatcher;

CREATE INDEX store_next_run ON public.store_connections(next_run_at) WHERE status IN ('QUEUED','CONNECTED','ERROR','SYNCING');

CREATE FUNCTION public.revoke_store_connection() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.collector_key IS DISTINCT FROM 'woocommerce_node' THEN RETURN NEW; END IF;
 IF NOT NEW.is_active OR NEW.collector_config->>'ceopro_connection_status'='disconnected' THEN
  UPDATE public.ingestion_jobs j SET job_status='FAILED',error_log='STORE_DISCONNECTED',ended_at=now()
   FROM public.store_connections c WHERE c.tenant_id=NEW.tenant_id AND c.source_id=NEW.source_id
    AND j.tenant_id=c.tenant_id AND j.job_id=c.job_id AND j.job_status IN ('PROCESSING','QUEUED');
 END IF;
 IF NEW.collector_config->>'ceopro_connection_status'='disconnected' THEN
  UPDATE public.store_connections SET credentials=NULL,status='DISCONNECTED',version=gen_random_uuid(),lease_token=NULL,lease_until=NULL,job_id=NULL,progress='{}'
   WHERE tenant_id=NEW.tenant_id AND source_id=NEW.source_id;
 ELSIF NOT NEW.is_active THEN
  UPDATE public.store_connections SET status='PAUSED',version=gen_random_uuid(),lease_token=NULL,lease_until=NULL,job_id=NULL,progress='{}'
   WHERE tenant_id=NEW.tenant_id AND source_id=NEW.source_id AND status<>'DISCONNECTED';
 ELSIF NEW.is_active AND NOT OLD.is_active THEN
  UPDATE public.store_connections SET status='QUEUED',next_run_at=now(),attempts=0
   WHERE tenant_id=NEW.tenant_id AND source_id=NEW.source_id AND credentials IS NOT NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.revoke_store_connection() FROM PUBLIC;
CREATE TRIGGER store_source_lifecycle AFTER UPDATE OF is_active,collector_config ON public.data_sources
 FOR EACH ROW EXECUTE FUNCTION public.revoke_store_connection();
