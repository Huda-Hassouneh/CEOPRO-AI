-- Follow-up to the already exercised reconciliation role migration.
-- Row locks require UPDATE privilege even when the SQL only reads a row.
-- Keep membership-write privilege in a NOLOGIN function owner, not in accounting.
GRANT UPDATE(user_id) ON public.tenant_users TO ceopro_schedule_writer;
CREATE FUNCTION public.billing_accounting_principal(p_tenant uuid,p_actor uuid) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF p_tenant IS DISTINCT FROM public.get_current_tenant()
 OR p_actor IS DISTINCT FROM nullif(current_setting('app.current_user_id',true),'')::uuid
 OR public.keel_active_principal(p_actor,p_tenant) IS DISTINCT FROM TRUE THEN RETURN false; END IF;
 PERFORM 1 FROM public.tenant_users WHERE tenant_id=p_tenant AND user_id=p_actor AND removed_at IS NULL FOR SHARE;
 RETURN FOUND;
END $$;
ALTER FUNCTION public.billing_accounting_principal(uuid,uuid) OWNER TO ceopro_schedule_writer;
REVOKE ALL ON FUNCTION public.billing_accounting_principal(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_accounting_principal(uuid,uuid) TO ceopro_credit_accounting;

CREATE FUNCTION public.billing_webhook_receipt_guard() RETURNS trigger
 LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF current_user='ceopro_billing_webhook' AND
 ((OLD.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id)
 OR (OLD.processed_at IS NOT NULL AND NEW.processed_at IS DISTINCT FROM OLD.processed_at)) THEN
  RAISE EXCEPTION 'Verified event binding and completion are immutable' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_webhook_receipt_guard() FROM PUBLIC;
CREATE TRIGGER billing_webhook_receipt_guard BEFORE UPDATE ON public.billing_webhook_events
 FOR EACH ROW EXECUTE FUNCTION public.billing_webhook_receipt_guard();
