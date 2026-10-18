-- CEOPRO AI
-- Usage-driven internal infrastructure rate cards for custom-plan pricing.
--
-- This table is intentionally separate from vendor_rates:
--   vendor_rates          = external provider/API costs
--   infrastructure_rates  = internal/platform infrastructure cost drivers
--
-- No existing quote or plan columns are changed. Historical/custom quote
-- evidence continues to live in custom_plan_quotes.pricing_inputs and
-- custom_plan_quotes.pricing_snapshot.

CREATE TYPE infrastructure_rate_usage_basis_enum AS ENUM (
    'limit_value',
    'estimated_usage',
    'enabled_feature'
);

CREATE TYPE infrastructure_rate_verification_status_enum AS ENUM (
    'confirmed',
    'estimated',
    'unconfirmed',
    'deprecated'
);

CREATE TABLE infrastructure_rates (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    feature_id UUID,
    cost_driver VARCHAR(100) NOT NULL,
    usage_basis infrastructure_rate_usage_basis_enum NOT NULL DEFAULT 'estimated_usage',
    billing_unit VARCHAR(80) NOT NULL,
    billing_units_per_feature_unit DECIMAL(18, 10) NOT NULL DEFAULT 1,
    unit_cost DECIMAL(14, 6) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    operational_multiplier DECIMAL(8, 4) NOT NULL DEFAULT 1,
    variability_reserve DECIMAL(8, 4) NOT NULL DEFAULT 1,
    effective_from TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_to TIMESTAMPTZ(6),
    verification_status infrastructure_rate_verification_status_enum NOT NULL DEFAULT 'unconfirmed',
    source TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT infrastructure_rates_pkey PRIMARY KEY (id),
    CONSTRAINT infrastructure_rates_feature_id_fkey
        FOREIGN KEY (feature_id)
        REFERENCES features(feature_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE,
    CONSTRAINT infrastructure_rates_unit_cost_nonnegative_chk
        CHECK (unit_cost >= 0),
    CONSTRAINT infrastructure_rates_billing_units_positive_chk
        CHECK (billing_units_per_feature_unit > 0),
    CONSTRAINT infrastructure_rates_operational_multiplier_positive_chk
        CHECK (operational_multiplier > 0),
    CONSTRAINT infrastructure_rates_variability_reserve_min_chk
        CHECK (variability_reserve >= 1),
    CONSTRAINT infrastructure_rates_effective_window_chk
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT infrastructure_rates_currency_chk
        CHECK (currency ~ '^[A-Z]{3}$')
);

-- Supports active-rate lookup by selected feature and quote time.
CREATE INDEX infrastructure_rates_feature_id_effective_from_idx
    ON infrastructure_rates(feature_id, effective_from);

-- Supports administration/history views by internal cost driver.
CREATE INDEX infrastructure_rates_cost_driver_effective_from_idx
    ON infrastructure_rates(cost_driver, effective_from);

-- Supports filtering out deprecated/unverified cards efficiently.
CREATE INDEX infrastructure_rates_verification_status_idx
    ON infrastructure_rates(verification_status);

-- Prevents accidentally inserting the exact same version twice while still
-- allowing rate history over time and multiple different cost drivers per feature.
CREATE UNIQUE INDEX infrastructure_rates_feature_driver_effective_from_key
    ON infrastructure_rates(feature_id, cost_driver, effective_from)
    WHERE feature_id IS NOT NULL;

CREATE TRIGGER infrastructure_rates_set_updated_at
BEFORE UPDATE ON infrastructure_rates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE infrastructure_rates IS
'Versioned internal infrastructure cost drivers used by CEOPRO custom-plan pricing; separate from external vendor rates.';

COMMENT ON COLUMN infrastructure_rates.usage_basis IS
'How pricing derives the feature quantity: configured limit, estimated usage, or one unit when the feature is enabled.';

COMMENT ON COLUMN infrastructure_rates.billing_units_per_feature_unit IS
'Conversion from one feature unit to the rate billing unit. Example: document_storage_mb to GB-month uses 0.0009765625.';

-- Existing extraction enforcement records ceil(bytes / 1024) as KB. Correct
-- the catalog metadata in-place so existing plans and usage displays use the
-- same unit without changing entitlement quantities.
UPDATE features
SET unit = 'KB', unit_ar = 'كيلوبايت'
WHERE feature_code = 'document_extraction'
  AND (unit IS DISTINCT FROM 'KB' OR unit_ar IS DISTINCT FROM 'كيلوبايت');
