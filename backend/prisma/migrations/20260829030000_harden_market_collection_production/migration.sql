-- CEOPRO AI - production gates for market collection: reviewed approval,
-- Tier-2 staging, stale-job recovery, quarantine, and retention metadata.

ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS approval_reference TEXT;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS approved_by UUID;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS privacy_reviewed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS retention_days INT NOT NULL DEFAULT 90;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS contains_personal_data BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_data_source_retention_days') THEN
        ALTER TABLE data_sources ADD CONSTRAINT chk_data_source_retention_days
            CHECK (retention_days BETWEEN 1 AND 3650);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_allowed_source_has_approval') THEN
        ALTER TABLE data_sources ADD CONSTRAINT chk_allowed_source_has_approval
            CHECK (policy_status <> 'ALLOWED' OR (
                approval_reference IS NOT NULL AND approved_by IS NOT NULL
                AND approved_at IS NOT NULL AND privacy_reviewed_at IS NOT NULL
            )) NOT VALID;
    END IF;
END $$;

ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS rows_quarantined INT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_stale_market
    ON ingestion_jobs(tenant_id, source_id, heartbeat_at)
    WHERE job_status = 'PROCESSING';

CREATE TABLE IF NOT EXISTS market_observation_staging (
    staging_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    job_id UUID NOT NULL,
    mapping_id UUID NOT NULL,
    raw_payload JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    validation_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (validation_status IN ('PENDING', 'REJECTED', 'QUARANTINED', 'PROMOTED')),
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    safety_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    staged_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_market_stage_source FOREIGN KEY (tenant_id, source_id)
        REFERENCES data_sources(tenant_id, source_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_stage_job FOREIGN KEY (tenant_id, job_id)
        REFERENCES ingestion_jobs(tenant_id, job_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_stage_mapping FOREIGN KEY (tenant_id, mapping_id)
        REFERENCES competitor_product_mappings(tenant_id, mapping_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_market_stage_review
    ON market_observation_staging(tenant_id, validation_status, staged_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_stage_job_content
    ON market_observation_staging(tenant_id, job_id, mapping_id, content_hash);

ALTER TABLE market_observation_staging ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_observation_staging FORCE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'market_observation_staging' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON market_observation_staging
            FOR ALL USING (tenant_id = get_current_tenant())
            WITH CHECK (tenant_id = get_current_tenant());
    END IF;
END $$;

CREATE OR REPLACE FUNCTION recover_stale_market_jobs(stale_after_minutes INT DEFAULT 30)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE affected INT;
BEGIN
    IF stale_after_minutes < 1 OR stale_after_minutes > 1440 THEN
        RAISE EXCEPTION 'stale_after_minutes must be between 1 and 1440';
    END IF;
    UPDATE ingestion_jobs job
    SET job_status = 'FAILED', ended_at = NOW(),
        error_log = 'Recovered after stale worker heartbeat'
    FROM data_sources source
    WHERE source.tenant_id = job.tenant_id AND source.source_id = job.source_id
      AND source.collection_method IS NOT NULL AND job.job_status = 'PROCESSING'
      AND COALESCE(job.heartbeat_at, job.started_at)
          < NOW() - (stale_after_minutes * INTERVAL '1 minute');
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_market_retention()
RETURNS TABLE(staging_deleted INT, observations_redacted INT, reviews_anonymized INT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    DELETE FROM market_observation_staging stage
    USING data_sources source
    WHERE source.tenant_id = stage.tenant_id AND source.source_id = stage.source_id
      AND stage.staged_at < NOW() - (source.retention_days * INTERVAL '1 day');
    GET DIAGNOSTICS staging_deleted = ROW_COUNT;

    UPDATE market_observations observation
    SET page_text = NULL, raw_payload = '{}'::jsonb
    FROM data_sources source
    WHERE source.tenant_id = observation.tenant_id
      AND source.source_id = observation.source_id
      AND observation.observed_at < NOW() - (source.retention_days * INTERVAL '1 day')
      AND (observation.page_text IS NOT NULL OR observation.raw_payload <> '{}'::jsonb);
    GET DIAGNOSTICS observations_redacted = ROW_COUNT;

    UPDATE reviews review
    SET reviewer_name = NULL
    FROM data_sources source
    WHERE source.tenant_id = review.tenant_id AND source.source_id = review.source_id
      AND review.review_date < NOW() - (source.retention_days * INTERVAL '1 day')
      AND review.reviewer_name IS NOT NULL;
    GET DIAGNOSTICS reviews_anonymized = ROW_COUNT;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION recover_stale_market_jobs(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION enforce_market_retention() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            market_observation_staging, market_observations, market_events,
            competitor_score_snapshots, market_alert_rules, market_alert_events
        TO ceopro_app;
        GRANT EXECUTE ON FUNCTION recover_stale_market_jobs(INT) TO ceopro_app;
        GRANT EXECUTE ON FUNCTION enforce_market_retention() TO ceopro_app;
    END IF;
END $$;
