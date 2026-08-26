-- CEOPRO AI - Restore evidence_records as the shared, cross-module evidence
-- table spec S22 requires: "All dashboard outputs, alerts, chatbot answers,
-- and recommendations must use this shared evidence model ... The system
-- must have one consistent evidence architecture."
--
-- Final_schema.sql's evidence_records is forecast-only: forecast_id is
-- NOT NULL, and the only columns are metric_name/metric_value_json/
-- contribution_weight - structurally, pricing/, sentiment/, mpi/, and
-- extraction/ cannot write to it at all. Rather than forking a second
-- evidence table (AI_PLAN_AND_CONTRACT_UPDATES.md already rejected that once:
-- "a second table would fork the evidence trail rather than extend it"),
-- this extends the existing table: forecast_id becomes optional (still used,
-- still FK'd, just not mandatory), and the general-purpose columns every
-- non-forecasting module's evidence.py needs come back alongside the
-- forecast-specific ones, which are untouched and still work exactly as
-- Final_schema.sql defined them for forecast_id IS NOT NULL rows.

ALTER TABLE evidence_records ALTER COLUMN forecast_id DROP NOT NULL;

ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS category VARCHAR(20);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS source_module VARCHAR(100);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS source_record_ids JSONB;
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5, 2);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS explanation_text TEXT;
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS model_version VARCHAR(50);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS country_context VARCHAR(2);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_evidence_category') THEN
        ALTER TABLE evidence_records ADD CONSTRAINT chk_evidence_category
            CHECK (category IS NULL OR category IN ('FACT', 'PREDICTION', 'RECOMMENDATION', 'ASSUMPTION', 'UNKNOWN'));
    END IF;
END $$;

-- A non-forecasting evidence row must still say what module produced it and
-- why (forecasting rows are exempt - they're identified by forecast_id
-- instead, and predate this column existing).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_evidence_shape') THEN
        ALTER TABLE evidence_records ADD CONSTRAINT chk_evidence_shape
            CHECK (forecast_id IS NOT NULL OR (category IS NOT NULL AND source_module IS NOT NULL AND explanation_text IS NOT NULL));
    END IF;
END $$;
