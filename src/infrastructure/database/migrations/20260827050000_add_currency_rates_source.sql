-- CEOPRO AI - Restore currency_rates.source.
-- Spec S9: "The system must NEVER silently convert money without preserving
-- the original value ... plus the rate, its date, and its source." Final_schema.sql's
-- currency_rates has no source column at all - nullable here, same as the
-- old schema, since not every rate feed reports one.

ALTER TABLE currency_rates ADD COLUMN IF NOT EXISTS source VARCHAR(100);
