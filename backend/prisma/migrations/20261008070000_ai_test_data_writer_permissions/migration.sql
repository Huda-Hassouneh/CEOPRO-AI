-- Grants a dedicated, pre-created test database login access to selected
-- CEOPRO data-ingestion tables. 

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_ai_test_writer'
  ) THEN
    RAISE EXCEPTION
      'Required test role ceopro_ai_test_writer is missing. Create it in the TEST database, then rerun Prisma migrate deploy. See docs/ai-test-db-writer.md.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'ceopro_ai_test_writer'
      AND (
        NOT rolcanlogin
        OR rolsuper
        OR rolcreatedb
        OR rolcreaterole
        OR rolreplication
        OR rolbypassrls
      )
  ) THEN
    RAISE EXCEPTION
      'ceopro_ai_test_writer must be a LOGIN role with NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_auth_members
    WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'ceopro_ai_test_writer')
  ) THEN
    RAISE EXCEPTION
      'ceopro_ai_test_writer must not inherit or be able to SET ROLE to another database role.';
  END IF;
END $$;

DO $$
BEGIN
  EXECUTE format(
    'GRANT CONNECT ON DATABASE %I TO %I',
    current_database(),
    'ceopro_ai_test_writer'
  );
END $$;

GRANT USAGE ON SCHEMA public TO ceopro_ai_test_writer;

GRANT SELECT, INSERT, UPDATE ON TABLE
  public.global_competitors,
  public.tenant_competitors,
  public.competitor_product_mappings,
  public.competitor_prices,
  public.competitor_score_snapshots,
  public.reviews,
  public.sentiment_results,
  public.evidence_records,
  public.rag_documents_metadata,
  public.rag_document_chunks,
  public.data_sources,
  public.ingestion_jobs,
  public.import_staging_rows,
  public.market_observation_staging,
  public.market_observations,
  public.market_events
TO ceopro_ai_test_writer;

GRANT INSERT ON TABLE public.audit_logs TO ceopro_ai_test_writer;

DO $$
DECLARE
  staging_sequence text;
BEGIN
  staging_sequence := pg_get_serial_sequence(
    'public.import_staging_rows',
    'staging_row_id'
  );

  IF staging_sequence IS NOT NULL THEN
    EXECUTE format(
      'GRANT USAGE, SELECT ON SEQUENCE %s TO %I',
      staging_sequence::regclass,
      'ceopro_ai_test_writer'
    );
  END IF;
END $$;
