-- ENT-008 Stage 1: tenant-scoped durable intent and execution receipts.
-- This table is orchestration state only. It does not meter usage, credits,
-- provider cost, or customer entitlements.

CREATE TABLE IF NOT EXISTS public.keel_operation_receipts (
    receipt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES public.companies(tenant_id) ON DELETE CASCADE,
    source_id UUID NOT NULL,
    ingestion_job_id UUID,
    operation_type TEXT NOT NULL CHECK (operation_type = 'reviewed_source_collection'),
    principal_kind TEXT NOT NULL CHECK (principal_kind IN ('user', 'service')),
    actor_user_id UUID NOT NULL,
    period_start DATE NOT NULL,
    idempotency_key UUID NOT NULL DEFAULT gen_random_uuid(),
    request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
    state TEXT NOT NULL CHECK (state IN (
        'dispatch_pending', 'queued', 'claimed', 'authorized', 'provider_started',
        'retryable', 'completed', 'denied', 'reconciliation_required', 'failed'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    lease_generation BIGINT NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
    provider_started_at TIMESTAMPTZ,
    provider_outcome TEXT NOT NULL CHECK (provider_outcome IN ('not_started', 'unknown', 'completed')),
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT fk_keel_operation_receipt_source
        FOREIGN KEY (tenant_id, source_id)
        REFERENCES public.data_sources(tenant_id, source_id) ON DELETE RESTRICT,
    CONSTRAINT fk_keel_operation_receipt_job
        FOREIGN KEY (tenant_id, ingestion_job_id)
        REFERENCES public.ingestion_jobs(tenant_id, job_id) ON DELETE SET NULL (ingestion_job_id),
    CONSTRAINT uq_keel_operation_receipt_identity
        UNIQUE (tenant_id, operation_type, period_start, idempotency_key),
    CONSTRAINT ck_keel_operation_receipt_lease
        CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT ck_keel_operation_receipt_provider
        CHECK ((provider_started_at IS NULL) = (provider_outcome = 'not_started'))
);

CREATE INDEX IF NOT EXISTS idx_keel_operation_receipts_dispatch
    ON public.keel_operation_receipts (created_at)
    WHERE state IN ('dispatch_pending', 'retryable');

CREATE INDEX IF NOT EXISTS idx_keel_operation_receipts_expired_lease
    ON public.keel_operation_receipts (lease_expires_at)
    WHERE state IN ('claimed', 'authorized', 'provider_started');

CREATE UNIQUE INDEX IF NOT EXISTS uq_keel_operation_receipts_active_source
    ON public.keel_operation_receipts (tenant_id, source_id)
    WHERE state IN (
        'dispatch_pending', 'queued', 'claimed', 'authorized', 'provider_started',
        'retryable', 'reconciliation_required'
    );

ALTER TABLE public.keel_operation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.keel_operation_receipts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS isolation_keel_operation_receipts ON public.keel_operation_receipts;
CREATE POLICY isolation_keel_operation_receipts
    ON public.keel_operation_receipts
    FOR ALL
    USING (tenant_id = public.get_current_tenant())
    WITH CHECK (tenant_id = public.get_current_tenant());

REVOKE ALL ON public.keel_operation_receipts FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE ALL ON public.keel_operation_receipts FROM ceopro_app;
        GRANT SELECT, INSERT ON public.keel_operation_receipts TO ceopro_app;
        GRANT UPDATE (
            state, attempt_count, lease_owner, lease_expires_at, lease_generation,
            provider_started_at, provider_outcome, error_code, updated_at, completed_at,
            ingestion_job_id
        ) ON public.keel_operation_receipts TO ceopro_app;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.list_tenants_with_expired_operation_receipts()
RETURNS TABLE (tenant_id UUID)
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT DISTINCT r.tenant_id
      FROM public.keel_operation_receipts AS r
     WHERE r.state IN ('claimed', 'authorized', 'provider_started')
       AND r.lease_expires_at < NOW()
     ORDER BY r.tenant_id;
$$;
REVOKE ALL ON FUNCTION public.list_tenants_with_expired_operation_receipts() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION public.list_tenants_with_expired_operation_receipts() TO ceopro_app;
    END IF;
END $$;

-- Cross-tenant dispatch discovers tenant IDs only. Receipt contents remain
-- protected by FORCE RLS and are fetched on a tenant-scoped connection.
CREATE OR REPLACE FUNCTION public.list_tenants_with_pending_operation_receipts()
RETURNS TABLE (tenant_id UUID)
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT DISTINCT r.tenant_id
      FROM public.keel_operation_receipts AS r
     WHERE r.state IN ('dispatch_pending', 'retryable')
     ORDER BY r.tenant_id;
$$;
REVOKE ALL ON FUNCTION public.list_tenants_with_pending_operation_receipts() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT EXECUTE ON FUNCTION public.list_tenants_with_pending_operation_receipts() TO ceopro_app;
    END IF;
END $$;
