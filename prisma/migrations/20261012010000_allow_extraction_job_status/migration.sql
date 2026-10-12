-- Manual business-file uploads reserve a job while the AI extraction call is
-- running. The original baseline constraint omitted this lifecycle state.
ALTER TABLE ingestion_jobs
    DROP CONSTRAINT IF EXISTS chk_job_status;

ALTER TABLE ingestion_jobs
    ADD CONSTRAINT chk_job_status
        CHECK (job_status IN ('EXTRACTING', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED'));
