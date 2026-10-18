-- Forward only: retain historical rules and events; no customer data is removed.
ALTER TABLE public.market_alert_rules ADD COLUMN name varchar(120) NOT NULL DEFAULT 'Price change',
 ADD COLUMN cooldown_minutes integer NOT NULL DEFAULT 60 CHECK(cooldown_minutes BETWEEN 0 AND 10080);
ALTER TABLE public.market_alert_events ADD COLUMN trigger_facts jsonb NOT NULL DEFAULT '{}', ADD COLUMN resolved_at timestamptz,
 ADD COLUMN acknowledged_by uuid, ADD COLUMN resolved_by uuid, ADD COLUMN dedupe_key text;
CREATE UNIQUE INDEX market_alert_event_dedupe ON public.market_alert_events(tenant_id,dedupe_key) WHERE dedupe_key IS NOT NULL;
ALTER TABLE public.market_alert_events ADD CONSTRAINT market_alert_rule_tenant_fk FOREIGN KEY(tenant_id,alert_rule_id)
 REFERENCES public.market_alert_rules(tenant_id,alert_rule_id) ON DELETE CASCADE NOT VALID;
CREATE UNIQUE INDEX uq_market_event_tenant ON public.market_events(tenant_id,event_id);
ALTER TABLE public.market_alert_events ADD CONSTRAINT market_alert_event_tenant_fk FOREIGN KEY(tenant_id,market_event_id)
 REFERENCES public.market_events(tenant_id,event_id) NOT VALID;
-- Trigger-only identity. It cannot sign in, bypass RLS, or read customer tables.
DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_event_publisher') THEN
 CREATE ROLE ceopro_event_publisher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
 END IF; END $$;
GRANT USAGE ON SCHEMA public TO ceopro_event_publisher;
GRANT INSERT ON public.tenant_notification_outbox,public.platform_notification_outbox TO ceopro_event_publisher;
CREATE POLICY tenant_event_publisher ON public.tenant_notification_outbox FOR INSERT TO ceopro_event_publisher WITH CHECK(true);
CREATE POLICY platform_event_publisher ON public.platform_notification_outbox FOR INSERT TO ceopro_event_publisher WITH CHECK(true);
CREATE FUNCTION public.publish_important_event() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE event_name text; event_key text; event_payload jsonb; tenant uuid; notify_tenant boolean:=false; notify_platform boolean:=false;
BEGIN
 IF TG_TABLE_NAME='market_alert_events' THEN
  event_name:='MARKET_ALERT_TRIGGERED'; event_key:='market-alert:'||NEW.alert_event_id; tenant:=NEW.tenant_id;
  event_payload:=jsonb_build_object('resourceId',NEW.alert_event_id); notify_tenant:=true;
 ELSIF TG_TABLE_NAME='ingestion_jobs' THEN
  IF TG_OP<>'UPDATE' THEN RETURN NEW; END IF;
  IF NEW.job_status IS NOT DISTINCT FROM OLD.job_status OR NEW.job_status NOT IN ('COMPLETED','FAILED') THEN RETURN NEW; END IF;
  event_name:='IMPORT_'||NEW.job_status; event_key:='import:'||NEW.job_id||':'||NEW.job_status||':'||NEW.processing_attempts;
  event_payload:=jsonb_build_object('resourceId',NEW.job_id,'status',NEW.job_status); tenant:=NEW.tenant_id;
  notify_tenant:=true; notify_platform:=NEW.job_status='FAILED';
 ELSIF TG_TABLE_NAME='companies' THEN
  IF NEW.business_type='platform' THEN RETURN NEW; END IF;
  event_name:='TENANT_REGISTERED'; tenant:=NEW.tenant_id; event_key:='tenant-registered:'||tenant;
  event_payload:=jsonb_build_object('resourceId',tenant); notify_platform:=true;
 ELSIF TG_TABLE_NAME='subscriptions' THEN
  IF TG_OP='UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status AND NEW.cancel_at_period_end IS NOT DISTINCT FROM OLD.cancel_at_period_end THEN RETURN NEW; END IF;
  event_name:='SUBSCRIPTION_CHANGED'; tenant:=NEW.tenant_id;
  event_key:='subscription:'||NEW.id||':'||NEW.status||':'||NEW.cancel_at_period_end||':'||NEW.updated_at;
  event_payload:=jsonb_build_object('resourceId',NEW.id,'status',NEW.status,'cancelAtPeriodEnd',NEW.cancel_at_period_end);
  notify_tenant:=true; notify_platform:=true;
 END IF;
 IF notify_tenant THEN
 INSERT INTO public.tenant_notification_outbox(tenant_id,event_type,dedupe_key,payload) VALUES(tenant,event_name,event_key,event_payload) ON CONFLICT DO NOTHING;
 END IF;
 IF notify_platform THEN
 INSERT INTO public.platform_notification_outbox(tenant_id,event_type,dedupe_key,payload) VALUES(tenant,event_name,event_key,event_payload) ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.publish_important_event() FROM PUBLIC;
-- Temporary ownership transfer membership is revoked within the migration.
DO $$ BEGIN EXECUTE format('GRANT ceopro_event_publisher TO %I',current_user); END $$;
GRANT CREATE ON SCHEMA public TO ceopro_event_publisher;
ALTER FUNCTION public.publish_important_event() OWNER TO ceopro_event_publisher;
DO $$ BEGIN EXECUTE format('REVOKE ceopro_event_publisher FROM %I',current_user); END $$;
REVOKE CREATE ON SCHEMA public FROM ceopro_event_publisher;
CREATE TRIGGER publish_market_alert AFTER INSERT ON public.market_alert_events FOR EACH ROW EXECUTE FUNCTION public.publish_important_event();
CREATE TRIGGER publish_import_status AFTER UPDATE ON public.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION public.publish_important_event();
CREATE TRIGGER publish_tenant_registered AFTER INSERT ON public.companies FOR EACH ROW EXECUTE FUNCTION public.publish_important_event();
CREATE TRIGGER publish_subscription_status AFTER INSERT OR UPDATE ON public.subscriptions FOR EACH ROW EXECUTE FUNCTION public.publish_important_event();
-- Recheck current membership and domain permissions when reading a receipt-backed
-- tenant notification. This helper only reads authorization leaves, never notifications.
CREATE FUNCTION public.can_read_domain_notification(event_name text) RETURNS boolean
 LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.tenant_users tu JOIN public.system_roles r ON r.role_key=tu.role_key
 WHERE tu.tenant_id=public.get_current_tenant() AND tu.user_id=NULLIF(current_setting('app.current_user_id',true),'')::uuid
 AND tu.removed_at IS NULL AND tu.platform_status='active'
 AND (r.permissions->>'all'='true' OR CASE
 WHEN event_name IN ('SUBSCRIPTION_CHANGED','CUSTOM_PLAN_OFFER_READY') THEN r.permissions->>'manage_billing'='true'
 WHEN event_name IN ('IMPORT_COMPLETED','IMPORT_FAILED') THEN r.permissions->>'manage_catalog'='true'
 WHEN event_name IN ('MARKET_ALERT_TRIGGERED','BUSINESS_RECOMMENDATION_READY') THEN r.permissions->>'view_analytics'='true' OR r.permissions->>'manage_catalog'='true'
 ELSE false END));
$$;
REVOKE ALL ON FUNCTION public.can_read_domain_notification(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_read_domain_notification(text) TO ceopro_app;
CREATE POLICY tenant_notification_current_domain ON public.tenant_notifications AS RESTRICTIVE FOR SELECT TO ceopro_app
 USING(public.can_read_domain_notification(event_type));

CREATE TABLE public.tenant_notification_preferences (
 tenant_id uuid NOT NULL,user_id uuid NOT NULL,
 category text NOT NULL CHECK(category IN ('business','market','imports')),
 enabled boolean NOT NULL DEFAULT true,
 PRIMARY KEY(tenant_id,user_id,category),
 FOREIGN KEY(tenant_id,user_id) REFERENCES public.tenant_users(tenant_id,user_id) ON DELETE CASCADE
);
ALTER TABLE public.tenant_notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_notification_preferences FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.tenant_notification_preferences FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON public.tenant_notification_preferences TO ceopro_app;
GRANT SELECT ON public.tenant_notification_preferences TO ceopro_notification_worker;
CREATE POLICY notification_preferences_self ON public.tenant_notification_preferences TO ceopro_app
 USING(tenant_id=public.get_current_tenant() AND user_id=NULLIF(current_setting('app.current_user_id',true),'')::uuid)
 WITH CHECK(tenant_id=public.get_current_tenant() AND user_id=NULLIF(current_setting('app.current_user_id',true),'')::uuid);
CREATE POLICY notification_preferences_worker ON public.tenant_notification_preferences FOR SELECT TO ceopro_notification_worker USING(true);
GRANT SELECT(tenant_id,plan_id,status) ON public.subscriptions TO ceopro_notification_worker;
GRANT SELECT(feature_id,feature_code,feature_type) ON public.features TO ceopro_notification_worker;
GRANT SELECT(plan_id,feature_id) ON public.plan_features TO ceopro_notification_worker;
CREATE POLICY notification_worker_entitlement ON public.subscriptions FOR SELECT TO ceopro_notification_worker
 USING(EXISTS(SELECT 1 FROM public.companies c WHERE c.tenant_id=subscriptions.tenant_id AND c.business_type IS DISTINCT FROM 'platform' AND c.deleted_at IS NULL AND c.platform_status='active'));
