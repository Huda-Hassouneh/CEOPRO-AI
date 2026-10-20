-- Forward repair; existing migration runner applies this file transactionally.
-- Quiesce report writers and deploy with period-aware accounting code.
ALTER TABLE metered_request_keys
    ADD COLUMN request_fingerprint VARCHAR(64),
    ADD COLUMN replayed BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN request_id UUID NOT NULL DEFAULT gen_random_uuid();

ALTER TABLE metered_request_keys
    DROP CONSTRAINT metered_request_keys_pkey,
    ADD CONSTRAINT metered_request_keys_pkey
        PRIMARY KEY (tenant_id, feature_code, period_start, idempotency_key);

-- Retain historical keys, ownership, grants, RLS and FORCE RLS unchanged.
-- Never delete cross-period history merely to restore the old primary key.
