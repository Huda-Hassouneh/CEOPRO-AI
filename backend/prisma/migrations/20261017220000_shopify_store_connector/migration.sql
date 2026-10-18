-- Extend the existing connector pipeline. No historical migrations or data are reset.
ALTER TABLE public.store_connections
 ADD COLUMN provider TEXT NOT NULL DEFAULT 'woocommerce' CHECK(provider IN ('woocommerce','shopify')),
 ADD COLUMN shop_domain TEXT,
 ADD COLUMN provider_shop_id TEXT,
 ADD COLUMN history_access TEXT NOT NULL DEFAULT 'all' CHECK(history_access IN ('all','recent')),
 ADD COLUMN sync_requested BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE public.store_connections ADD CONSTRAINT shopify_identity_shape CHECK
 (provider <> 'shopify' OR (shop_domain IS NULL OR shop_domain ~ '^[a-z0-9][a-z0-9-]*\.myshopify\.com$'));
CREATE UNIQUE INDEX store_shop_identity ON public.store_connections(tenant_id,provider,provider_shop_id) WHERE provider_shop_id IS NOT NULL;
CREATE UNIQUE INDEX store_shop_domain ON public.store_connections(tenant_id,shop_domain) WHERE shop_domain IS NOT NULL;
ALTER TABLE public.store_product_links ADD COLUMN parent_external_id TEXT;
CREATE TABLE public.store_oauth_states (
 tenant_id UUID NOT NULL,user_id UUID NOT NULL,state_hash TEXT NOT NULL,
 shop_domain TEXT NOT NULL,source_id UUID,sync_minutes INT NOT NULL CHECK(sync_minutes BETWEEN 15 AND 10080),
 expires_at TIMESTAMPTZ NOT NULL,consumed_at TIMESTAMPTZ,
 PRIMARY KEY(tenant_id,state_hash),
 FOREIGN KEY(tenant_id,user_id) REFERENCES public.tenant_users(tenant_id,user_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id)
);
CREATE TABLE public.store_inventory_locations (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,external_id TEXT NOT NULL,location_id TEXT NOT NULL,
 inventory_id UUID,observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,source_id,external_id,location_id),UNIQUE(tenant_id,inventory_id),
 FOREIGN KEY(tenant_id,source_id,external_id) REFERENCES public.store_product_links(tenant_id,source_id,external_id),
 FOREIGN KEY(tenant_id,inventory_id) REFERENCES public.inventory(tenant_id,inventory_id)
);
CREATE TABLE public.shopify_privacy_reports (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,event_id TEXT NOT NULL,
 report JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,source_id,event_id),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id)
);
CREATE TABLE public.store_order_exclusions (
 tenant_id UUID NOT NULL,source_id UUID NOT NULL,order_hash TEXT NOT NULL,
 PRIMARY KEY(tenant_id,source_id,order_hash),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.store_connections(tenant_id,source_id)
);
DO $$ DECLARE relation TEXT; BEGIN
 FOREACH relation IN ARRAY ARRAY['store_oauth_states','store_inventory_locations','shopify_privacy_reports','store_order_exclusions'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation);
  EXECUTE format('CREATE POLICY store_tenant ON public.%I TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',relation);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',relation);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO ceopro_app',relation);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION public.revoke_store_connection() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.collector_key IS DISTINCT FROM 'woocommerce_node' AND NEW.collector_key IS DISTINCT FROM 'shopify_node' THEN RETURN NEW; END IF;
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

-- Only this non-login, non-bypass role executes verified webhook lifecycle operations.
-- It has no members; application/runtime roles receive function EXECUTE only through
-- the existing restricted dispatcher connection, never financial-table grants.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_shopify_events') THEN
  CREATE ROLE ceopro_shopify_events NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
 END IF;
END $$;
GRANT USAGE ON SCHEMA public TO ceopro_shopify_events;
CREATE TABLE public.shopify_webhook_deliveries (
 shop_hash TEXT NOT NULL,event_id TEXT NOT NULL,topic TEXT NOT NULL,received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(shop_hash,event_id,topic)
);
ALTER TABLE public.shopify_webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shopify_webhook_deliveries FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.shopify_webhook_deliveries FROM PUBLIC;
DO $$ DECLARE relation TEXT; BEGIN
 FOREACH relation IN ARRAY ARRAY['store_connections','data_sources','ingestion_jobs','import_staging_rows',
 'store_sale_links','store_order_item_links','store_order_links','store_inventory_locations','store_product_links',
 'store_inventory_links','store_oauth_states','store_order_exclusions','shopify_webhook_deliveries','shopify_privacy_reports','invoices','invoice_items','transactions','inventory','products'] LOOP
  EXECUTE format('CREATE POLICY shopify_events_internal ON public.%I TO ceopro_shopify_events USING(true) WITH CHECK(true)',relation);
 END LOOP;
END $$;
GRANT SELECT ON public.store_connections,public.data_sources,public.ingestion_jobs,public.store_sale_links,
 public.store_order_item_links,public.store_order_links,public.store_inventory_locations,public.store_product_links,
 public.store_inventory_links,public.products,public.invoices,public.invoice_items,public.inventory,public.transactions TO ceopro_shopify_events;
GRANT UPDATE(status,credentials,version,lease_token,lease_until,job_id,progress,next_run_at,attempts,sync_requested,last_error,shop_domain,provider_shop_id) ON public.store_connections TO ceopro_shopify_events;
GRANT UPDATE(metadata,updated_at) ON public.products TO ceopro_shopify_events;
GRANT UPDATE(is_active,collector_config,source_url,source_name) ON public.data_sources TO ceopro_shopify_events;
GRANT UPDATE(job_status,error_log,ended_at) ON public.ingestion_jobs TO ceopro_shopify_events;
GRANT SELECT,INSERT,DELETE ON public.shopify_webhook_deliveries TO ceopro_shopify_events;
GRANT SELECT,INSERT ON public.store_order_exclusions TO ceopro_shopify_events;
GRANT INSERT,DELETE ON public.shopify_privacy_reports TO ceopro_shopify_events;
GRANT DELETE ON public.import_staging_rows,public.store_sale_links,public.store_order_item_links,public.store_order_links,
 public.store_inventory_locations,public.store_inventory_links,public.store_product_links,public.store_oauth_states,
 public.invoices,public.invoice_items,public.transactions,public.inventory TO ceopro_shopify_events;
GRANT SELECT ON public.import_staging_rows,public.store_oauth_states,public.shopify_privacy_reports TO ceopro_shopify_events;
GRANT EXECUTE ON FUNCTION public.revoke_store_connection() TO ceopro_shopify_events;
CREATE FUNCTION public.process_shopify_event(p_shop TEXT,p_topic TEXT,p_event TEXT,p_orders TEXT[] DEFAULT '{}') RETURNS INT
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE c RECORD; n INT:=0; txids UUID[]; invoiceids UUID[]; stockids UUID[];
BEGIN
 IF p_shop !~ '^[a-z0-9][a-z0-9-]*\.myshopify\.com$' OR length(p_event)>200 OR p_event='' OR
 p_topic NOT IN ('app/uninstalled','products/create','products/update','products/delete','orders/create','orders/updated',
 'orders/paid','orders/cancelled','refunds/create','inventory_levels/update','customers/data_request','customers/redact','shop/redact')
 THEN RAISE EXCEPTION 'Invalid Shopify event'; END IF;
 IF cardinality(p_orders)>10000 OR EXISTS(SELECT 1 FROM unnest(p_orders) x WHERE x !~ CASE WHEN p_topic='products/delete' THEN '^gid://shopify/Product/[1-9][0-9]{0,19}$' ELSE '^gid://shopify/Order/[1-9][0-9]{0,19}$' END)
 THEN RAISE EXCEPTION 'Invalid Shopify order identifiers'; END IF;
 INSERT INTO public.shopify_webhook_deliveries(shop_hash,event_id,topic) VALUES(encode(public.digest(p_shop,'sha256'),'hex'),p_event,p_topic)
 ON CONFLICT DO NOTHING;
 IF NOT FOUND THEN RETURN 0; END IF;
 DELETE FROM public.shopify_webhook_deliveries WHERE received_at<now()-interval '30 days';
 FOR c IN SELECT tenant_id,source_id FROM public.store_connections WHERE provider='shopify' AND shop_domain=p_shop ORDER BY source_id LOOP
  PERFORM 1 FROM public.data_sources WHERE tenant_id=c.tenant_id AND source_id=c.source_id FOR UPDATE;
  PERFORM 1 FROM public.store_connections WHERE tenant_id=c.tenant_id AND source_id=c.source_id FOR UPDATE;
  n:=n+1;
  IF p_topic='products/delete' THEN
   UPDATE public.ingestion_jobs j SET job_status='FAILED',error_log='STORE_CATALOG_CHANGED',ended_at=now() FROM public.store_connections sc
    WHERE sc.tenant_id=c.tenant_id AND sc.source_id=c.source_id AND j.tenant_id=c.tenant_id AND j.job_id=sc.job_id AND j.job_status IN ('PROCESSING','QUEUED');
   UPDATE public.store_connections SET version=gen_random_uuid(),lease_token=NULL,lease_until=NULL,job_id=NULL,progress='{}',sync_requested=true,next_run_at=now(),
    status=CASE WHEN status='SYNCING' THEN 'QUEUED' ELSE status END WHERE tenant_id=c.tenant_id AND source_id=c.source_id;
   SELECT array_agg(i.inventory_id) INTO stockids FROM public.store_inventory_locations i JOIN public.store_product_links l USING(tenant_id,source_id,external_id)
    WHERE i.tenant_id=c.tenant_id AND i.source_id=c.source_id AND l.parent_external_id=ANY(p_orders);
   DELETE FROM public.store_inventory_locations i USING public.store_product_links l WHERE i.tenant_id=c.tenant_id AND i.source_id=c.source_id AND l.tenant_id=i.tenant_id AND l.source_id=i.source_id AND l.external_id=i.external_id AND l.parent_external_id=ANY(p_orders);
   DELETE FROM public.inventory WHERE tenant_id=c.tenant_id AND inventory_id=ANY(stockids);
   UPDATE public.products p SET metadata=coalesce(p.metadata,'{}'::jsonb)||jsonb_build_object('store_source_inactive',c.source_id::text),updated_at=now()
    FROM public.store_product_links l WHERE l.tenant_id=c.tenant_id AND l.source_id=c.source_id AND l.parent_external_id=ANY(p_orders) AND l.owns_product
    AND p.tenant_id=l.tenant_id AND p.product_id=l.product_id AND NOT EXISTS(SELECT 1 FROM public.store_product_links other WHERE other.tenant_id=l.tenant_id AND other.product_id=l.product_id AND other.source_id<>l.source_id);
   CONTINUE;
  END IF;
  IF p_topic='customers/data_request' THEN
   INSERT INTO public.shopify_privacy_reports(tenant_id,source_id,event_id,report)
   SELECT c.tenant_id,c.source_id,p_event,jsonb_build_object('customerIdentityStored',false,'orders',coalesce(jsonb_agg(jsonb_build_object(
    'orderId',l.order_id,'invoiceId',i.invoice_id,'currency',i.currency,'total',i.total_amount,'paymentStatus',i.payment_status)),'[]'::jsonb))
   FROM public.store_order_links l JOIN public.invoices i ON i.tenant_id=l.tenant_id AND i.invoice_id=l.invoice_id
   WHERE l.tenant_id=c.tenant_id AND l.source_id=c.source_id AND l.order_id=ANY(p_orders);
   CONTINUE;
  END IF;
  IF p_topic IN ('customers/redact','shop/redact') THEN
   IF p_topic='customers/redact' THEN
    INSERT INTO public.store_order_exclusions(tenant_id,source_id,order_hash)
     SELECT c.tenant_id,c.source_id,encode(public.digest(x,'sha256'),'hex') FROM unnest(p_orders) x ON CONFLICT DO NOTHING;
   END IF;
   UPDATE public.ingestion_jobs j SET job_status='FAILED',error_log='STORE_PRIVACY_RECONCILIATION',ended_at=now()
    FROM public.store_connections sc WHERE sc.tenant_id=c.tenant_id AND sc.source_id=c.source_id AND j.tenant_id=c.tenant_id AND j.job_id=sc.job_id AND j.job_status IN ('PROCESSING','QUEUED');
   UPDATE public.store_connections SET version=gen_random_uuid(),lease_token=NULL,lease_until=NULL,job_id=NULL,progress='{}',sync_requested=true,next_run_at=now(),
    status=CASE WHEN status='SYNCING' THEN 'QUEUED' ELSE status END WHERE tenant_id=c.tenant_id AND source_id=c.source_id;

   SELECT array_agg(transaction_id) INTO txids FROM public.store_sale_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND (p_topic='shop/redact' OR order_id=ANY(p_orders));
   SELECT array_agg(invoice_id) INTO invoiceids FROM public.store_order_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND (p_topic='shop/redact' OR order_id=ANY(p_orders));
   DELETE FROM public.store_sale_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND (p_topic='shop/redact' OR order_id=ANY(p_orders));
   DELETE FROM public.store_order_item_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND (p_topic='shop/redact' OR order_id=ANY(p_orders));
   DELETE FROM public.store_order_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND (p_topic='shop/redact' OR order_id=ANY(p_orders));
   DELETE FROM public.invoice_items WHERE tenant_id=c.tenant_id AND invoice_id=ANY(invoiceids);
   DELETE FROM public.invoices WHERE tenant_id=c.tenant_id AND invoice_id=ANY(invoiceids);
   DELETE FROM public.transactions WHERE tenant_id=c.tenant_id AND transaction_id=ANY(txids);
   DELETE FROM public.import_staging_rows r USING public.ingestion_jobs j WHERE r.tenant_id=c.tenant_id AND r.job_id=j.job_id AND j.tenant_id=c.tenant_id AND j.source_id=c.source_id;
   DELETE FROM public.shopify_privacy_reports WHERE tenant_id=c.tenant_id AND source_id=c.source_id;
   IF p_topic='customers/redact' THEN CONTINUE; END IF;
   SELECT array_agg(inventory_id) INTO stockids FROM public.store_inventory_locations WHERE tenant_id=c.tenant_id AND source_id=c.source_id;
   DELETE FROM public.store_inventory_locations WHERE tenant_id=c.tenant_id AND source_id=c.source_id;
   DELETE FROM public.inventory WHERE tenant_id=c.tenant_id AND inventory_id=ANY(stockids);
   DELETE FROM public.store_product_links WHERE tenant_id=c.tenant_id AND source_id=c.source_id;
   DELETE FROM public.store_oauth_states WHERE tenant_id=c.tenant_id AND (source_id=c.source_id OR shop_domain=p_shop);
  END IF;
  IF p_topic IN ('app/uninstalled','shop/redact') THEN
   UPDATE public.data_sources SET is_active=false,collector_config=jsonb_build_object('provider','shopify','ceopro_connection_status','disconnected'),
    source_url=CASE WHEN p_topic='shop/redact' THEN NULL ELSE source_url END,
    source_name=CASE WHEN p_topic='shop/redact' THEN 'Disconnected Shopify store' ELSE source_name END
    WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND collector_key='shopify_node';
   IF p_topic='shop/redact' THEN UPDATE public.store_connections SET shop_domain=NULL,provider_shop_id=NULL WHERE tenant_id=c.tenant_id AND source_id=c.source_id; END IF;
  ELSE
   UPDATE public.store_connections SET sync_requested=true,next_run_at=now(),attempts=0
    WHERE tenant_id=c.tenant_id AND source_id=c.source_id AND status NOT IN ('DISCONNECTED','PAUSED');
  END IF;
 END LOOP;
 RETURN n;
END $$;
ALTER FUNCTION public.process_shopify_event(TEXT,TEXT,TEXT,TEXT[]) OWNER TO ceopro_shopify_events;
REVOKE ALL ON FUNCTION public.process_shopify_event(TEXT,TEXT,TEXT,TEXT[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.process_shopify_event(TEXT,TEXT,TEXT,TEXT[]) TO ceopro_market_dispatcher;
