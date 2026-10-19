-- CEOPRO AI - Add transactions + model_versions, and reconcile demand_forecasts
-- with what src/ai/forecasting/ already writes.
--
-- Final_schema.sql (the post-schema-fork canonical 26-table schema) never
-- carried these tables forward from the old init_schema.sql - confirmed
-- directly against a live database (PENDING_ACTIONS.md #31): no
-- `transactions` table at all, no `model_versions` table at all. Without
-- them, forecasting/data_access.py::load_daily_demand() and
-- forecasting/evidence.py::insert_model_version() cannot run - not a bug in
-- that code, a genuine data-model gap. Decided explicitly (not assumed): add
-- these tables back rather than rework forecasting/ onto invoices/
-- invoice_items, which lack a per-line transaction_date and a POS/online
-- sale_source distinction forecasting's own code and tests already depend
-- on. Same "extend Final_schema.sql, don't reduce the feature" precedent
-- already used for evidence_records (20260827000000_restore_shared_evidence_
-- architecture.sql).
--
-- A second, independent gap found while wiring this up: demand_forecasts'
-- own columns don't match what forecasting/evidence.py::insert_demand_
-- forecast() writes, or what test_integration_db.py's own live-DB assertions
-- expect (predicted_quantity vs. expected_demand; confidence_lower_bound/
-- confidence_upper_bound vs. confidence_range_lower/confidence_range_upper;
-- no forecast_target_date column at all; forecast_start_date/
-- forecast_end_date NOT NULL but never populated by evidence.py). Reconciled
-- here in the same migration rather than leaving forecasting broken a second
-- way after this lands.

-- 1. TRANSACTIONS
-- Columns match forecasting/data_access.py::load_daily_demand()'s query
-- (transaction_date, quantity_sold, unit_price) plus test_integration_db.py's
-- seed fixture (sale_source, original_currency) and the old init_schema.sql's
-- currency-traceability columns (converted_amount/converted_currency/
-- exchange_rate/conversion_source/conversion_timestamp), kept for parity
-- since nothing in this schema fork's cross-currency work (currency_rates,
-- pricing/currency.py) had a reason to drop them.
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    product_id UUID NOT NULL,
    quantity_sold INT NOT NULL CHECK (quantity_sold > 0),
    unit_price NUMERIC(12, 4) NOT NULL CHECK (unit_price >= 0),
    total_price NUMERIC(12, 4) NOT NULL CHECK (total_price >= 0),
    original_currency VARCHAR(3) NOT NULL CHECK (original_currency ~ '^[A-Z]{3}$'),
    converted_amount NUMERIC(12, 4),
    converted_currency VARCHAR(3) CHECK (converted_currency IS NULL OR converted_currency ~ '^[A-Z]{3}$'),
    exchange_rate NUMERIC(18, 8),
    conversion_source VARCHAR(100),
    conversion_timestamp TIMESTAMP WITH TIME ZONE,
    sale_source VARCHAR(50) NOT NULL DEFAULT 'POS',
    transaction_date TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_transactions_product_isolated FOREIGN KEY (tenant_id, product_id) REFERENCES products(tenant_id, product_id) ON DELETE CASCADE,
    CONSTRAINT uq_tenant_transaction_perimeter UNIQUE (tenant_id, transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_tenant_date ON transactions(tenant_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_transactions_tenant_product ON transactions(tenant_id, product_id);

ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'transactions' AND policyname = 'isolation_transactions') THEN
        CREATE POLICY isolation_transactions ON transactions FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;

-- 2. MODEL_VERSIONS
-- No tenant_id, no RLS - a global model registry, matching the old schema
-- exactly and forecasting/evidence.py::insert_model_version(), which never
-- passes a tenant. artifact_path added directly here (PENDING_ACTIONS.md #7 -
-- "small, additive schema change... low risk, just needs someone to run it")
-- rather than as a second migration, since this table is being created fresh
-- anyway.
CREATE TABLE IF NOT EXISTS model_versions (
    model_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(100) NOT NULL,
    version VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'development',
    trained_at TIMESTAMP WITH TIME ZONE,
    metrics JSONB,
    artifact_path VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_model_status CHECK (status IN ('development', 'candidate', 'staging', 'production', 'archived'))
);

-- 3. DEMAND_FORECASTS reconciliation
-- Renaming existing columns (not adding new ones alongside) since
-- Final_schema.sql's demand_forecasts has never been written to in
-- production (no forecasting code path could reach it until this migration)
-- - there's no real data to preserve under the old names.
ALTER TABLE demand_forecasts RENAME COLUMN predicted_quantity TO expected_demand;
-- test_integration_db.py::test_evidence_writers_round_trip_through_real_tables
-- asserts a 12.7 insert reads back as 13 - an INT column, matching the
-- pre-fork schema's expected_demand INT NOT NULL, not NUMERIC(12,2).
ALTER TABLE demand_forecasts ALTER COLUMN expected_demand TYPE INT USING ROUND(expected_demand)::INT;

ALTER TABLE demand_forecasts RENAME COLUMN confidence_lower_bound TO confidence_range_lower;
ALTER TABLE demand_forecasts RENAME COLUMN confidence_upper_bound TO confidence_range_upper;

ALTER TABLE demand_forecasts ADD COLUMN IF NOT EXISTS forecast_target_date DATE;

-- forecasting/evidence.py::insert_demand_forecast() never populates
-- forecast_start_date/forecast_end_date (it only ever knew about a single
-- forecast_target_date) - both were NOT NULL in Final_schema.sql's original,
-- untouched definition, which would reject every real insert. The existing
-- chk_forecast_dates CHECK (forecast_end_date >= forecast_start_date) still
-- holds once these are nullable: a CHECK with a NULL operand evaluates to
-- unknown, which Postgres treats as satisfying the constraint, not violating
-- it.
ALTER TABLE demand_forecasts ALTER COLUMN forecast_start_date DROP NOT NULL;
ALTER TABLE demand_forecasts ALTER COLUMN forecast_end_date DROP NOT NULL;
