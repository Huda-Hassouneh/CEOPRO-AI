-- Undoes migrations/20261026000000_add_price_comparison_overrides.sql. Owner decisions are lost (they cannot be rebuilt).
DROP TABLE IF EXISTS product_price_comparison_overrides;
