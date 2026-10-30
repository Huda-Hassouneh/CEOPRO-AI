-- Source-owned accounting links extend existing M95/M98 and canonical invoices.
-- Historical source migrations remain immutable; no payment/subscription authority is added.
ALTER TABLE public.invoice_items ADD COLUMN rounding_adjustment numeric(12,4) NOT NULL DEFAULT 0;
ALTER TABLE public.invoice_items DROP CONSTRAINT chk_total_price_consistent;
ALTER TABLE public.invoice_items ADD CONSTRAINT chk_total_price_consistent CHECK(total_price=quantity*unit_price+rounding_adjustment AND abs(rounding_adjustment)<=0.00005*quantity);
CREATE TABLE public.keel_provider_order_posts(
 tenant_id uuid NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
 source_id uuid NOT NULL,provider text NOT NULL CHECK(provider IN ('shopify','woocommerce')),provider_record_identity_id uuid NOT NULL,business_revision_id uuid NOT NULL,
 invoice_id uuid NOT NULL,actor_id uuid NOT NULL REFERENCES users(user_id),
 provider_modified_at timestamptz NOT NULL,canonical_hash char(64) NOT NULL CHECK(canonical_hash~'^[0-9a-f]{64}$'),
 line_links jsonb NOT NULL CHECK(jsonb_typeof(line_links)='object'),response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,business_revision_id),
 FOREIGN KEY(tenant_id,source_id,provider,provider_record_identity_id) REFERENCES keel_provider_record_identities(tenant_id,source_id,provider,provider_record_identity_id),
 FOREIGN KEY(tenant_id,source_id,provider,business_revision_id) REFERENCES keel_provider_business_revisions(tenant_id,source_id,provider,business_revision_id),
 FOREIGN KEY(tenant_id,invoice_id) REFERENCES invoices(tenant_id,invoice_id));
CREATE INDEX provider_order_posts_identity ON public.keel_provider_order_posts(tenant_id,provider_record_identity_id,created_at DESC);
ALTER TABLE public.keel_provider_order_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_provider_order_posts FORCE ROW LEVEL SECURITY;
CREATE POLICY provider_order_posts_tenant ON public.keel_provider_order_posts TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant() AND actor_id=nullif(current_setting('app.current_user_id',true),'')::uuid);
REVOKE ALL ON public.keel_provider_order_posts FROM PUBLIC,ceopro_app;
GRANT SELECT,INSERT ON public.keel_provider_order_posts TO ceopro_app;
CREATE FUNCTION public.keel_provider_order_post_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'provider accounting receipts are immutable' USING ERRCODE='42501'; END IF;
 IF NEW.tenant_id IS DISTINCT FROM public.get_current_tenant() OR NEW.actor_id IS DISTINCT FROM nullif(current_setting('app.current_user_id',true),'')::uuid
 OR NOT public.keel_active_principal(NEW.actor_id,NEW.tenant_id)
 OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=NEW.tenant_id AND u.user_id=NEW.actor_id AND u.role_key IN ('owner','admin'))
 OR NOT EXISTS(SELECT 1 FROM public.keel_provider_record_identities i JOIN public.keel_provider_business_revisions b ON b.tenant_id=i.tenant_id AND b.provider_record_identity_id=i.provider_record_identity_id JOIN public.keel_provider_business_reviews r ON r.tenant_id=b.tenant_id AND r.business_revision_id=b.business_revision_id
 WHERE i.tenant_id=NEW.tenant_id AND i.source_id=NEW.source_id AND i.provider_record_identity_id=NEW.provider_record_identity_id AND i.entity_type='order' AND i.canonical_invoice_id=NEW.invoice_id AND b.business_revision_id=NEW.business_revision_id AND r.decision='approve') THEN RAISE EXCEPTION 'approved owner source accounting evidence required' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER provider_order_post_guard BEFORE INSERT OR UPDATE OR DELETE ON public.keel_provider_order_posts FOR EACH ROW EXECUTE FUNCTION public.keel_provider_order_post_guard();
