-- Background image generation: a durable queue of image jobs, so a company can
-- ask for hundreds of images (several formats x several variations per
-- campaign) without a request waiting minutes, and so a worker crash or a busy
-- image server never loses a job.
--
-- One row = one image to make. Workers (python -m src.ai.marketing.image_worker,
-- any number, on any machines) claim jobs with claim_image_generation_job():
-- FOR UPDATE SKIP LOCKED, so two workers never take the same job, and
-- companies are served in turn (a company's 1st queued job before anyone's
-- 2nd), so one big batch never starves everyone else. A job whose worker died
-- (no heartbeat for stale_seconds) is claimed again. Failures are retried with
-- backoff up to max_attempts; a job is FAILED only after that.
--
-- Row-level security is ENABLED (not FORCED): the API's ceopro_app role only
-- ever sees its own company's jobs; the table owner (migrations, and the claim
-- function below as SECURITY DEFINER) can see every company's queue, which is
-- what claiming across companies requires. The claim returns only ids; all the
-- work on a job then runs on that company's own RLS-scoped connection.
--
-- Additive: one new table, two functions, one worker-heartbeat table.

CREATE TABLE IF NOT EXISTS image_generation_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL,
    batch_id UUID NOT NULL,
    image_format VARCHAR(20) NOT NULL
        CHECK (image_format IN ('SQUARE', 'PORTRAIT', 'STORY', 'LANDSCAPE', 'WIDE')),
    prompt TEXT,
    channel VARCHAR(20)
        CHECK (channel IS NULL OR channel IN ('INSTAGRAM', 'FACEBOOK', 'TIKTOK', 'GOOGLE_ADS', 'WEBSITE', 'PRINT', 'OTHER')),
    seed BIGINT CHECK (seed IS NULL OR seed >= 0),
    attach BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(12) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 20),
    next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    worker_id VARCHAR(120),
    heartbeat_at TIMESTAMP WITH TIME ZONE,
    asset_id UUID,
    mode VARCHAR(20),
    error TEXT,
    seconds NUMERIC(10, 1),
    created_by UUID,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT fk_image_jobs_campaign FOREIGN KEY (tenant_id, campaign_id)
        REFERENCES campaigns (tenant_id, campaign_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_image_jobs_queue ON image_generation_jobs (status, next_attempt_at)
    WHERE status IN ('QUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS idx_image_jobs_campaign ON image_generation_jobs (tenant_id, campaign_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_image_jobs_batch ON image_generation_jobs (tenant_id, batch_id);
CREATE INDEX IF NOT EXISTS idx_image_jobs_finished ON image_generation_jobs (finished_at) WHERE status = 'COMPLETED';

ALTER TABLE image_generation_jobs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'image_generation_jobs'
                   AND policyname = 'isolation_image_generation_jobs') THEN
        CREATE POLICY isolation_image_generation_jobs ON image_generation_jobs
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;

-- Workers that are alive (heartbeat), for the capacity view. Not company data.
CREATE TABLE IF NOT EXISTS image_workers (
    worker_id VARCHAR(120) PRIMARY KEY,
    host VARCHAR(200),
    servers INTEGER,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    images_made INTEGER NOT NULL DEFAULT 0
);

-- Claims the next job (or NULL): due QUEUED jobs, plus RUNNING ones whose
-- worker stopped sending heartbeats. Companies take turns.
CREATE OR REPLACE FUNCTION claim_image_generation_job(p_worker_id TEXT, p_stale_seconds INTEGER)
RETURNS TABLE(job_id UUID, tenant_id UUID, created_by UUID)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    picked UUID;
BEGIN
    SELECT j.job_id INTO picked
    FROM image_generation_jobs j
    WHERE (j.status = 'QUEUED' AND j.next_attempt_at <= NOW())
       OR (j.status = 'RUNNING' AND j.heartbeat_at < NOW() - make_interval(secs => p_stale_seconds))
    -- A company's place in line = its images being made now + its older
    -- waiting ones, so a company with nothing running goes before the second
    -- image of a company that already has one in progress.
    ORDER BY (
        SELECT COUNT(*) FROM image_generation_jobs earlier
        WHERE earlier.tenant_id = j.tenant_id AND earlier.job_id <> j.job_id
          AND (earlier.status = 'RUNNING' OR (earlier.status = 'QUEUED' AND earlier.created_at < j.created_at))
    ), j.created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF picked IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    UPDATE image_generation_jobs u
    SET status = 'RUNNING', worker_id = p_worker_id, heartbeat_at = NOW(), attempts = u.attempts + 1,
        started_at = COALESCE(u.started_at, NOW())
    WHERE u.job_id = picked
    RETURNING u.job_id, u.tenant_id, u.created_by;
END;
$$;

REVOKE ALL ON FUNCTION claim_image_generation_job(TEXT, INTEGER) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION claim_image_generation_job(TEXT, INTEGER) TO ceopro_app;
    END IF;
END $$;

-- Queue figures across every company, without any company's data: for the
-- capacity view (queue length, recent speed, live workers).
CREATE OR REPLACE FUNCTION image_generation_capacity(p_window_minutes INTEGER, p_alive_seconds INTEGER)
RETURNS TABLE(queued BIGINT, running BIGINT, completed_recent BIGINT, avg_seconds NUMERIC, live_workers BIGINT,
              live_servers BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT
        (SELECT COUNT(*) FROM image_generation_jobs WHERE status = 'QUEUED'),
        (SELECT COUNT(*) FROM image_generation_jobs WHERE status = 'RUNNING'),
        (SELECT COUNT(*) FROM image_generation_jobs
          WHERE status = 'COMPLETED' AND finished_at > NOW() - make_interval(mins => p_window_minutes)),
        (SELECT ROUND(AVG(seconds), 1) FROM image_generation_jobs
          WHERE status = 'COMPLETED' AND mode = 'ai' AND finished_at > NOW() - make_interval(mins => p_window_minutes)),
        (SELECT COUNT(*) FROM image_workers WHERE heartbeat_at > NOW() - make_interval(secs => p_alive_seconds)),
        (SELECT COALESCE(SUM(servers), 0) FROM image_workers WHERE heartbeat_at > NOW() - make_interval(secs => p_alive_seconds));
$$;

REVOKE ALL ON FUNCTION image_generation_capacity(INTEGER, INTEGER) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION image_generation_capacity(INTEGER, INTEGER) TO ceopro_app;
    END IF;
END $$;
