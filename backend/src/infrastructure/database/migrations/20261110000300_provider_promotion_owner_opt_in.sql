-- Explicit append-only Tenant Owner choice, separately scoped to source/category.
-- This does not authorize invoice accounting mappings or grant canonical table powers.
CREATE TABLE public.keel_provider_promotion_decisions(
 tenant_id uuid NOT NULL,source_id uuid NOT NULL,provider text NOT NULL,category text NOT NULL CHECK(category IN ('catalog','inventory','orders')),
 decision_id uuid NOT NULL DEFAULT gen_random_uuid(),enabled boolean NOT NULL DEFAULT false,actor_id uuid NOT NULL REFERENCES users(user_id),
 decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(tenant_id,decision_id),
 FOREIGN KEY(tenant_id,source_id,provider) REFERENCES keel_provider_sources(tenant_id,source_id,provider));
CREATE INDEX provider_promotion_latest ON public.keel_provider_promotion_decisions(tenant_id,source_id,category,decided_at DESC);
ALTER TABLE public.keel_provider_promotion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_provider_promotion_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON public.keel_provider_promotion_decisions TO ceopro_app USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
REVOKE ALL ON public.keel_provider_promotion_decisions FROM PUBLIC,ceopro_app;
GRANT SELECT,INSERT ON public.keel_provider_promotion_decisions TO ceopro_app;
CREATE FUNCTION public.keel_provider_promotion_owner_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP<>'INSERT' OR NEW.tenant_id IS DISTINCT FROM public.get_current_tenant() OR NEW.actor_id IS DISTINCT FROM nullif(current_setting('app.current_user_id',true),'')::uuid OR NOT public.keel_active_principal(NEW.actor_id,NEW.tenant_id)
 OR NOT EXISTS(SELECT 1 FROM public.tenant_users u WHERE u.tenant_id=NEW.tenant_id AND u.user_id=NEW.actor_id AND lower(u.role_key)='owner' AND u.removed_at IS NULL AND u.platform_suspended_at IS NULL)
 OR (NEW.category='orders' AND NEW.enabled) THEN RAISE EXCEPTION 'tenant owner category authorization and approved mapping required' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER promotion_owner_guard BEFORE INSERT OR UPDATE OR DELETE ON public.keel_provider_promotion_decisions FOR EACH ROW EXECUTE FUNCTION public.keel_provider_promotion_owner_guard();
