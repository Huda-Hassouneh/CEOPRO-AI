-- Undoes migrations/20261024000000_add_product_price_comparisons.sql.
-- The table only holds derived data (recomputed from competitor_intel by
-- POST /pricing/comparisons/refresh), so dropping it loses nothing that cannot be rebuilt.
-- Code deployed with the migration tolerates the table being absent (SAVEPOINT + undefined_table).
DROP TABLE IF EXISTS product_price_comparisons;
