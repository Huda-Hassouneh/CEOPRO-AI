-- Forward hardening of the incoming installer-owned statistics command.
-- Keep both upstream migration identities intact for existing installations.
-- No tenant rows are returned or changed; only these fixed tables' planner
-- statistics can be refreshed. Runtime roles cannot replace this command.
CREATE OR REPLACE FUNCTION public.refresh_sales_statistics()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    ANALYZE public.invoices;
    ANALYZE public.invoice_items;
    ANALYZE public.transactions;
END;
$$;

REVOKE ALL ON FUNCTION public.refresh_sales_statistics() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refresh_sales_statistics()
    FROM ceopro_billing_setup, ceopro_billing_webhook, ceopro_credit_accounting;
GRANT EXECUTE ON FUNCTION public.refresh_sales_statistics() TO ceopro_app;
