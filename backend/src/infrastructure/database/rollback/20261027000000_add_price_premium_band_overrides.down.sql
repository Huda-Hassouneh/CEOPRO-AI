-- Undoes migrations/20261027000000_add_price_premium_band_overrides.sql. Owner-set bands are lost (the observed/default bands remain).
DROP TABLE IF EXISTS price_premium_band_overrides;
