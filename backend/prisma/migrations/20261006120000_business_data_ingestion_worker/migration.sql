-- Dedicated least-privilege identity and durable retry metadata for the
-- business-data staging consumer. The API continues to use ceopro_app.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_ingestion_worker'
    ) THEN
        CREATE ROLE ceopro_ingestion_worker
            WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    ELSE
        ALTER ROLE ceopro_ingestion_worker
            WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO ceopro_ingestion_worker',
        current_database()
    );
END
$$;

GRANT USAGE ON SCHEMA public TO ceopro_ingestion_worker;

ALTER TABLE ingestion_jobs
    ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ingestion_jobs
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE ingestion_jobs
    DROP CONSTRAINT IF EXISTS chk_ingestion_jobs_processing_attempts;
ALTER TABLE ingestion_jobs
    ADD CONSTRAINT chk_ingestion_jobs_processing_attempts
        CHECK (processing_attempts >= 0);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_worker_due
    ON ingestion_jobs (next_attempt_at, created_at, job_id)
    WHERE job_status IN ('QUEUED', 'PROCESSING');

CREATE INDEX IF NOT EXISTS idx_import_staging_pending_job
    ON import_staging_rows (tenant_id, job_id, staging_row_id)
    WHERE validation_status = 'PENDING';

-- Worker permissions are restricted to source lookup, job/staging lifecycle,
-- product resolution, and transaction inserts. It cannot delete data, modify
-- the catalog, or access unrelated tenant tables.
GRANT SELECT ON TABLE companies, data_sources TO ceopro_ingestion_worker;
GRANT SELECT, UPDATE ON TABLE ingestion_jobs, import_staging_rows
    TO ceopro_ingestion_worker;
GRANT SELECT, INSERT ON TABLE products TO ceopro_ingestion_worker;
GRANT INSERT ON TABLE transactions TO ceopro_ingestion_worker;

-- RLS policies are additive to ceopro_app's end-user tenant policies. The
-- worker sees only active customer tenants and only manual document-import
-- sources; it remains NOSUPERUSER/NOBYPASSRLS.
DROP POLICY IF EXISTS ingestion_worker_company_read ON companies;
CREATE POLICY ingestion_worker_company_read
    ON companies FOR SELECT TO ceopro_ingestion_worker
    USING (
        business_type IS DISTINCT FROM 'platform'
        AND deleted_at IS NULL
        AND platform_status = 'active'
    );

DROP POLICY IF EXISTS ingestion_worker_source_read ON data_sources;
CREATE POLICY ingestion_worker_source_read
    ON data_sources FOR SELECT TO ceopro_ingestion_worker
    USING (
        source_type = 'documents'
        AND EXISTS (
            SELECT 1 FROM companies c
            WHERE c.tenant_id = data_sources.tenant_id
              AND c.business_type IS DISTINCT FROM 'platform'
              AND c.deleted_at IS NULL
              AND c.platform_status = 'active'
        )
    );

DROP POLICY IF EXISTS ingestion_worker_job_read ON ingestion_jobs;
CREATE POLICY ingestion_worker_job_read
    ON ingestion_jobs FOR SELECT TO ceopro_ingestion_worker
    USING (
        EXISTS (
            SELECT 1 FROM data_sources s
            WHERE s.tenant_id = ingestion_jobs.tenant_id
              AND s.source_id = ingestion_jobs.source_id
              AND s.source_type = 'documents'
        )
    );

DROP POLICY IF EXISTS ingestion_worker_job_update ON ingestion_jobs;
CREATE POLICY ingestion_worker_job_update
    ON ingestion_jobs FOR UPDATE TO ceopro_ingestion_worker
    USING (
        EXISTS (
            SELECT 1 FROM data_sources s
            WHERE s.tenant_id = ingestion_jobs.tenant_id
              AND s.source_id = ingestion_jobs.source_id
              AND s.source_type = 'documents'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM data_sources s
            WHERE s.tenant_id = ingestion_jobs.tenant_id
              AND s.source_id = ingestion_jobs.source_id
              AND s.source_type = 'documents'
        )
    );

DROP POLICY IF EXISTS ingestion_worker_staging_read ON import_staging_rows;
CREATE POLICY ingestion_worker_staging_read
    ON import_staging_rows FOR SELECT TO ceopro_ingestion_worker
    USING (
        EXISTS (
            SELECT 1 FROM ingestion_jobs j
            WHERE j.tenant_id = import_staging_rows.tenant_id
              AND j.job_id = import_staging_rows.job_id
        )
    );

DROP POLICY IF EXISTS ingestion_worker_staging_update ON import_staging_rows;
CREATE POLICY ingestion_worker_staging_update
    ON import_staging_rows FOR UPDATE TO ceopro_ingestion_worker
    USING (
        EXISTS (
            SELECT 1 FROM ingestion_jobs j
            WHERE j.tenant_id = import_staging_rows.tenant_id
              AND j.job_id = import_staging_rows.job_id
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM ingestion_jobs j
            WHERE j.tenant_id = import_staging_rows.tenant_id
              AND j.job_id = import_staging_rows.job_id
        )
    );

DROP POLICY IF EXISTS ingestion_worker_product_read ON products;
CREATE POLICY ingestion_worker_product_read
    ON products FOR SELECT TO ceopro_ingestion_worker
    USING (
        EXISTS (
            SELECT 1 FROM companies c
            WHERE c.tenant_id = products.tenant_id
              AND c.business_type IS DISTINCT FROM 'platform'
              AND c.deleted_at IS NULL
              AND c.platform_status = 'active'
        )
    );

DROP POLICY IF EXISTS ingestion_worker_product_insert ON products;
CREATE POLICY ingestion_worker_product_insert
    ON products FOR INSERT TO ceopro_ingestion_worker
    WITH CHECK (
        source = 'IMPORTED'
        AND EXISTS (
            SELECT 1 FROM companies c
            WHERE c.tenant_id = products.tenant_id
              AND c.business_type IS DISTINCT FROM 'platform'
              AND c.deleted_at IS NULL
              AND c.platform_status = 'active'
        )
    );

DROP POLICY IF EXISTS ingestion_worker_transaction_insert ON transactions;
CREATE POLICY ingestion_worker_transaction_insert
    ON transactions FOR INSERT TO ceopro_ingestion_worker
    WITH CHECK (
        sale_source = 'IMPORT'
        AND EXISTS (
            SELECT 1 FROM companies c
            WHERE c.tenant_id = transactions.tenant_id
              AND c.business_type IS DISTINCT FROM 'platform'
              AND c.deleted_at IS NULL
              AND c.platform_status = 'active'
        )
    );
