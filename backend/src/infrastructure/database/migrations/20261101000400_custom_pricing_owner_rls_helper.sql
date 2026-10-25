-- Billing tables use FORCE RLS. Their owner-read policies must not query
-- platform identity tables as ceopro_app, which has no direct read grant.
-- This narrow boolean helper keeps that identity check inside the established
-- SECURITY DEFINER pattern without exposing membership rows.
CREATE OR REPLACE FUNCTION public.keel_is_active_platform_owner(p_user_id uuid, p_tenant_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
  SELECT p_user_id IS NOT NULL AND p_tenant_id IS NOT NULL
     AND public.keel_active_principal(p_user_id, p_tenant_id)
     AND EXISTS (
       SELECT 1
         FROM public.keel_platform_workspace w
         JOIN public.keel_platform_members m ON m.user_id=p_user_id
         JOIN public.users u ON u.user_id=p_user_id
        WHERE w.tenant_id=p_tenant_id
          AND m.role_key='owner' AND m.status='active'
          AND u.platform_disabled_at IS NULL
     );
$$;
REVOKE ALL ON FUNCTION public.keel_is_active_platform_owner(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.keel_is_active_platform_owner(uuid,uuid) TO ceopro_app;

DROP POLICY IF EXISTS billing_custom_cost_rates_owner_read ON public.billing_custom_cost_rates;
CREATE POLICY billing_custom_cost_rates_owner_read ON public.billing_custom_cost_rates FOR SELECT TO ceopro_app
  USING (public.keel_is_active_platform_owner(
    nullif(current_setting('app.current_user_id',true),'')::uuid,
    public.get_current_tenant()));

DROP POLICY IF EXISTS billing_custom_pricing_owner_read ON public.billing_custom_pricing_policies;
CREATE POLICY billing_custom_pricing_owner_read ON public.billing_custom_pricing_policies FOR SELECT TO ceopro_app
  USING (public.keel_is_active_platform_owner(
    nullif(current_setting('app.current_user_id',true),'')::uuid,
    public.get_current_tenant()));

DROP POLICY IF EXISTS billing_custom_cost_binding_owner_read ON public.billing_custom_cost_bindings;
CREATE POLICY billing_custom_cost_binding_owner_read ON public.billing_custom_cost_bindings FOR SELECT TO ceopro_app
  USING (public.keel_is_active_platform_owner(
    nullif(current_setting('app.current_user_id',true),'')::uuid,
    public.get_current_tenant()));

