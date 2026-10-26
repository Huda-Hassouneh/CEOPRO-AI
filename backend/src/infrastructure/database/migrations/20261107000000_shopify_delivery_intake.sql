-- Restricted, signed Shopify intake. Existing receipt and connector authorities are reused.
-- No provider payload/PII is retained; irreversible erasure remains policy-gated.
CREATE OR REPLACE FUNCTION public.keel_shopify_webhook_source(p_source uuid,p_domain text)
RETURNS TABLE(tenant_id uuid,shop_id text,shop_domain text)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
 SELECT s.tenant_id,s.verified_store_id,s.verified_store_domain
 FROM public.keel_provider_sources s JOIN public.data_sources d
 ON d.tenant_id=s.tenant_id AND d.source_id=s.source_id
 WHERE s.source_id=p_source AND s.provider='shopify' AND s.verified_store_domain=p_domain
 AND s.connection_state IN ('verified','disabled','verification_required');
$$;
REVOKE ALL ON FUNCTION public.keel_shopify_webhook_source(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_shopify_webhook_source(uuid,text) TO ceopro_app;

CREATE TABLE public.keel_provider_privacy_requests(
 tenant_id uuid NOT NULL,source_id uuid NOT NULL,delivery_receipt_id uuid PRIMARY KEY
 REFERENCES public.keel_provider_delivery_receipts(delivery_receipt_id) ON DELETE RESTRICT,
 topic text NOT NULL CHECK(topic IN ('customers/data_request','customers/redact','shop/redact')),
 status text NOT NULL DEFAULT 'policy_review_required' CHECK(status='policy_review_required'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(tenant_id,source_id) REFERENCES public.keel_provider_sources(tenant_id,source_id) ON DELETE RESTRICT
);
ALTER TABLE public.keel_provider_privacy_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_provider_privacy_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_privacy_read ON public.keel_provider_privacy_requests FOR SELECT TO ceopro_app
 USING(tenant_id=public.get_current_tenant());
REVOKE ALL ON public.keel_provider_privacy_requests FROM PUBLIC,ceopro_app;
GRANT SELECT ON public.keel_provider_privacy_requests TO ceopro_app;

CREATE OR REPLACE FUNCTION public.keel_shopify_delivery_intake(p_receipt uuid)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.keel_provider_delivery_receipts%ROWTYPE; result text;
BEGIN
 SELECT * INTO r FROM public.keel_provider_delivery_receipts
 WHERE delivery_receipt_id=p_receipt AND tenant_id=public.get_current_tenant()
 AND provider='shopify' AND signature_verified_at IS NOT NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'verified tenant receipt required' USING ERRCODE='42501'; END IF;
 IF r.state<>'authenticated' THEN RETURN r.state; END IF;
 IF r.event_type IN ('customers/data_request','customers/redact','shop/redact') THEN
   INSERT INTO public.keel_provider_privacy_requests(tenant_id,source_id,delivery_receipt_id,topic)
   VALUES(r.tenant_id,r.source_id,r.delivery_receipt_id,r.event_type);
 END IF;
 IF r.event_type IN ('app/uninstalled','customers/redact','shop/redact') THEN
   -- Wait for any existing fenced writer, then revoke future execution/reconnect.
   UPDATE public.data_sources SET is_active=false WHERE tenant_id=r.tenant_id AND source_id=r.source_id;
   UPDATE public.keel_provider_sources SET connection_state='disabled',
    configuration_version=configuration_version+1,updated_at=clock_timestamp()
   WHERE tenant_id=r.tenant_id AND source_id=r.source_id;
 END IF;
 result:=CASE WHEN r.event_type='app/uninstalled' THEN 'processed' ELSE 'reconciliation_required' END;
 UPDATE public.keel_provider_delivery_receipts SET state=result,updated_at=clock_timestamp()
 WHERE delivery_receipt_id=r.delivery_receipt_id;
 INSERT INTO public.audit_logs(tenant_id,user_id,action_type,target_table,record_id,changed_data_json)
 VALUES(r.tenant_id,NULL,'SHOPIFY_DELIVERY_RECORDED','keel_provider_delivery_receipts',r.delivery_receipt_id,
 jsonb_build_object('topic',r.event_type,'state',result,'privacy_completed',false));
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.keel_shopify_delivery_intake(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_shopify_delivery_intake(uuid) TO ceopro_app;

CREATE FUNCTION public.keel_provider_privacy_reimport_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.keel_provider_privacy_requests p WHERE p.tenant_id=NEW.tenant_id
 AND p.source_id=NEW.source_id AND p.topic IN ('customers/redact','shop/redact')) THEN
  IF (TG_TABLE_NAME='data_sources' AND (to_jsonb(NEW)->>'is_active')::boolean IS TRUE)
   OR (TG_TABLE_NAME='keel_provider_sources' AND to_jsonb(NEW)->>'connection_state'='verified') THEN
   RAISE EXCEPTION 'Shopify privacy review must be resolved before reimport' USING ERRCODE='42501';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER provider_privacy_reimport_guard BEFORE UPDATE ON public.keel_provider_sources
 FOR EACH ROW EXECUTE FUNCTION public.keel_provider_privacy_reimport_guard();
CREATE TRIGGER source_privacy_reimport_guard BEFORE UPDATE ON public.data_sources
 FOR EACH ROW EXECUTE FUNCTION public.keel_provider_privacy_reimport_guard();
