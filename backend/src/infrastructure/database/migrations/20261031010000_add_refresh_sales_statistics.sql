-- Right after a company imports a large sales file, the planner's statistics still describe the tables as they
-- were before it, so for that company it expects ~1 invoice and joins invoices to their lines with a nested
-- loop on tenant_id alone. Measured: the forecast staleness check for a fresh company with 12,000 imported lines
-- took 32.6 s (72 million row comparisons) instead of ~30 ms, and the import itself starts that check.
-- Autovacuum fixes the statistics only a minute or more later. The import calls this function once after
-- committing many rows; ANALYZE needs the table owner, hence SECURITY DEFINER, and the function can do nothing
-- but refresh these three tables' statistics.
CREATE OR REPLACE FUNCTION refresh_sales_statistics()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    ANALYZE invoices;
    ANALYZE invoice_items;
    ANALYZE transactions;
END;
$$;

REVOKE ALL ON FUNCTION refresh_sales_statistics() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION refresh_sales_statistics() TO ceopro_app;
    END IF;
END $$;
