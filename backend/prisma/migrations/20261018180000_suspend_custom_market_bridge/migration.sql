-- Stop the database producer for the withdrawn custom Python worker bridge.
-- Existing data, migration history, tenant policies and grants are preserved.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = 'ingestion_jobs'
      AND t.tgname = 'sales_import_market_discovery' AND NOT t.tgisinternal
  ) THEN
    ALTER TABLE public.ingestion_jobs DISABLE TRIGGER sales_import_market_discovery;
  END IF;
END $$;
