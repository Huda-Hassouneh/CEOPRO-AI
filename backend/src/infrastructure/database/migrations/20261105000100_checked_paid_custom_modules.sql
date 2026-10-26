-- Read only the current tenant's modules from immutable, verified activation proof.
-- Do not grant the application access to private activation or financial tables.
CREATE FUNCTION public.billing_custom_paid_modules(p_tenant uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 tenant uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 modules jsonb;
BEGIN
 IF actor IS NULL OR tenant IS DISTINCT FROM p_tenant OR NOT public.keel_active_principal(actor,tenant) THEN
  RAISE EXCEPTION 'active tenant context required' USING ERRCODE='42501';
 END IF;
 SELECT r.configuration->'enabledFeatures' INTO modules
 FROM public.billing_custom_contract_activations x
 JOIN public.billing_custom_quote_revisions r ON (r.tenant_id,r.quote_id,r.revision_id)=(x.tenant_id,x.quote_id,x.revision_id)
 JOIN public.tenant_custom_contracts c ON c.tenant_id=x.tenant_id AND c.contract_ref='custom-quote:'||x.quote_id::text||':'||x.revision_id::text
 JOIN public.billing_subscriptions s ON s.tenant_id=x.tenant_id AND s.stripe_subscription_id=x.stripe_subscription_id
 JOIN public.tenant_plan_assignments a ON a.tenant_id=x.tenant_id
 WHERE x.tenant_id=p_tenant AND a.plan_key='custom' AND a.source='stripe' AND a.status='active'
   AND s.plan_key='custom' AND s.status='active'
 ORDER BY x.activated_at DESC LIMIT 1;
 RETURN coalesce(modules,'[]'::jsonb);
END $$;
REVOKE ALL ON FUNCTION public.billing_custom_paid_modules(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_custom_paid_modules(uuid) TO ceopro_app;
