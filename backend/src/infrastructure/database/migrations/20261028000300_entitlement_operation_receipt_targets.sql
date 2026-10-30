-- ENT-008 Stage 2: extend the existing tenant-scoped receipt authority to
-- competitor enrichment and scheduled connector synchronization.
-- Existing receipts are preserved and become source-target operations.

ALTER TABLE public.keel_operation_receipts
    ADD COLUMN IF NOT EXISTS target_kind TEXT,
    ADD COLUMN IF NOT EXISTS target_id UUID,
    ADD COLUMN IF NOT EXISTS request_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE public.keel_operation_receipts
   SET target_kind = 'source', target_id = source_id
 WHERE target_kind IS NULL OR target_id IS NULL;

ALTER TABLE public.keel_operation_receipts ALTER COLUMN source_id DROP NOT NULL;
ALTER TABLE public.keel_operation_receipts ALTER COLUMN target_kind SET NOT NULL;
ALTER TABLE public.keel_operation_receipts ALTER COLUMN target_id SET NOT NULL;

ALTER TABLE public.keel_operation_receipts
    DROP CONSTRAINT IF EXISTS keel_operation_receipts_operation_type_check;
ALTER TABLE public.keel_operation_receipts
    ADD CONSTRAINT ck_keel_operation_receipt_operation_target
    CHECK (
        (operation_type IN ('reviewed_source_collection', 'scheduled_connector_sync')
         AND target_kind = 'source' AND source_id = target_id)
        OR
        (operation_type = 'competitor_enrichment'
         AND target_kind = 'competitor' AND source_id IS NULL)
    );
ALTER TABLE public.keel_operation_receipts
    ADD CONSTRAINT ck_keel_operation_receipt_request_payload
    CHECK (
        jsonb_typeof(request_payload) = 'object'
        AND request_payload - ARRAY['facets', 'depth', 'mode'] = '{}'::jsonb
        AND (operation_type = 'competitor_enrichment' OR request_payload = '{}'::jsonb)
        AND (NOT (request_payload ? 'facets') OR jsonb_typeof(request_payload->'facets') = 'array')
        AND (NOT (request_payload ? 'depth') OR request_payload->>'depth' IN ('standard', 'deep'))
        AND (NOT (request_payload ? 'mode') OR request_payload->>'mode' IN ('single', 'due', 'force', 'comments'))
    );
ALTER TABLE public.keel_operation_receipts
    ADD CONSTRAINT ck_keel_operation_receipt_source_target
    CHECK ((target_kind = 'source' AND source_id IS NOT NULL)
        OR (target_kind = 'competitor' AND source_id IS NULL));

DROP INDEX IF EXISTS public.uq_keel_operation_receipts_active_source;
CREATE UNIQUE INDEX IF NOT EXISTS uq_keel_operation_receipts_active_target
    ON public.keel_operation_receipts (tenant_id, operation_type, target_kind, target_id)
    WHERE state IN (
        'dispatch_pending', 'queued', 'claimed', 'authorized', 'provider_started',
        'retryable', 'reconciliation_required'
    );

CREATE INDEX IF NOT EXISTS idx_keel_operation_receipts_target
    ON public.keel_operation_receipts (tenant_id, operation_type, target_kind, target_id, created_at DESC);

-- RLS and grants from migration 90 remain in force. The additional columns
-- are immutable after INSERT; only lifecycle fields retain UPDATE permission.
