-- Membership ties immutable M96 observations (including duplicates) to a completed scan.
-- It never changes the quantity evidence or chooses a source on a customer's behalf.
CREATE TABLE public.keel_provider_stock_scan_members(
 tenant_id uuid NOT NULL,source_id uuid NOT NULL,ingestion_job_id uuid NOT NULL,
 inventory_observation_id uuid NOT NULL,receipt_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,ingestion_job_id,inventory_observation_id),
 FOREIGN KEY(tenant_id,source_id,ingestion_job_id) REFERENCES ingestion_jobs(tenant_id,source_id,job_id),
 FOREIGN KEY(tenant_id,inventory_observation_id) REFERENCES keel_inventory_observations(tenant_id,inventory_observation_id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES keel_operation_receipts(tenant_id,receipt_id));
CREATE TABLE public.keel_provider_stock_posts(
 tenant_id uuid NOT NULL,source_id uuid NOT NULL,inventory_observation_id uuid NOT NULL,
 canonical_product_id uuid NOT NULL,inventory_id uuid NOT NULL,actor_id uuid NOT NULL REFERENCES users(user_id),
 authority_decision_id uuid NOT NULL,canonical_hash char(64) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(tenant_id,inventory_observation_id),
 FOREIGN KEY(tenant_id,inventory_observation_id) REFERENCES keel_inventory_observations(tenant_id,inventory_observation_id),
 FOREIGN KEY(tenant_id,canonical_product_id) REFERENCES products(tenant_id,product_id),
 FOREIGN KEY(tenant_id,inventory_id) REFERENCES inventory(tenant_id,inventory_id),
 FOREIGN KEY(tenant_id,authority_decision_id) REFERENCES keel_inventory_authority_decisions(tenant_id,authority_decision_id));
CREATE INDEX provider_stock_posts_product ON public.keel_provider_stock_posts(tenant_id,canonical_product_id,created_at DESC);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['keel_provider_stock_scan_members','keel_provider_stock_posts'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY tenant_scope ON public.%I TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant())',t);
 EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,ceopro_app',t);
 EXECUTE format('GRANT SELECT,INSERT ON public.%I TO ceopro_app',t);
 END LOOP;
END $$;
CREATE FUNCTION public.keel_provider_stock_receipt_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF TG_OP<>'INSERT' OR NEW.tenant_id IS DISTINCT FROM public.get_current_tenant() OR NOT public.keel_active_principal(actor,NEW.tenant_id) THEN RAISE EXCEPTION 'immutable tenant stock evidence required' USING ERRCODE='42501'; END IF;
 IF TG_TABLE_NAME='keel_provider_stock_scan_members' THEN
  IF NOT EXISTS(SELECT 1 FROM public.keel_operation_receipts r JOIN public.keel_inventory_observations o ON o.tenant_id=r.tenant_id AND o.source_id=r.source_id WHERE r.tenant_id=NEW.tenant_id AND r.receipt_id=NEW.receipt_id AND r.source_id=NEW.source_id AND r.ingestion_job_id=NEW.ingestion_job_id AND r.actor_user_id=actor AND r.principal_kind='service' AND r.operation_type='scheduled_connector_sync' AND r.state='provider_started' AND r.lease_expires_at>clock_timestamp() AND o.inventory_observation_id=NEW.inventory_observation_id) THEN RAISE EXCEPTION 'live fenced inventory scan required' USING ERRCODE='42501'; END IF;
 ELSE
  IF NEW.actor_id IS DISTINCT FROM actor OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=NEW.tenant_id AND u.user_id=actor AND u.role_key IN ('owner','admin')) OR NOT EXISTS(SELECT 1 FROM public.keel_inventory_authority_decisions d JOIN public.keel_inventory_observations o ON o.tenant_id=d.tenant_id AND o.source_id=d.source_id AND o.provider_record_identity_id=d.provider_record_identity_id JOIN public.inventory i ON i.tenant_id=d.tenant_id AND i.product_id=d.canonical_product_id WHERE d.tenant_id=NEW.tenant_id AND d.authority_decision_id=NEW.authority_decision_id AND d.source_id=NEW.source_id AND d.decision='select' AND d.authority_kind='provider' AND d.canonical_product_id=NEW.canonical_product_id AND d.quantity_semantics=o.quantity_semantics AND d.provider_location_identity_id IS NOT DISTINCT FROM o.provider_location_identity_id AND o.inventory_observation_id=NEW.inventory_observation_id AND i.inventory_id=NEW.inventory_id AND i.stock_quantity=o.quantity) THEN RAISE EXCEPTION 'owner-selected provider stock evidence required' USING ERRCODE='42501'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER stock_scan_guard BEFORE INSERT OR UPDATE OR DELETE ON public.keel_provider_stock_scan_members FOR EACH ROW EXECUTE FUNCTION public.keel_provider_stock_receipt_guard();
CREATE TRIGGER stock_post_guard BEFORE INSERT OR UPDATE OR DELETE ON public.keel_provider_stock_posts FOR EACH ROW EXECUTE FUNCTION public.keel_provider_stock_receipt_guard();
