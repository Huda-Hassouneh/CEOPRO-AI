-- CEOPRO AI - Restore the evidence_id link on recommendation_outcomes.
-- Final_schema.sql's version has no evidence_id at all (forecast_id and a
-- mandatory recommended_action instead) - spec S24 requires "Every
-- recommendation must create a RECOMMENDATION_OUTCOME record" traceable
-- back to the evidence that produced it. Nullable, same reasoning as
-- evidence_records.forecast_id being made nullable in the other direction:
-- forecast-originated outcomes can keep using forecast_id, evidence-originated
-- ones (pricing/'s recommendations today) use evidence_id.

-- evidence_records only had a single-column PK (evidence_id) - every other
-- table in Final_schema.sql pairs its PK with a `uq_tenant_X_perimeter
-- UNIQUE (tenant_id, X)` constraint specifically so tenant-isolated composite
-- FKs like the one below are possible. Matching that established convention
-- rather than introducing a different FK shape just for this one table.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tenant_evidence_perimeter') THEN
        ALTER TABLE evidence_records ADD CONSTRAINT uq_tenant_evidence_perimeter UNIQUE (tenant_id, evidence_id);
    END IF;
END $$;

ALTER TABLE recommendation_outcomes ADD COLUMN IF NOT EXISTS evidence_id UUID;
ALTER TABLE recommendation_outcomes ALTER COLUMN recommended_action DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_rec_outcome_evidence_isolated') THEN
        ALTER TABLE recommendation_outcomes ADD CONSTRAINT fk_rec_outcome_evidence_isolated
            FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence_records(tenant_id, evidence_id) ON DELETE CASCADE;
    END IF;
END $$;
