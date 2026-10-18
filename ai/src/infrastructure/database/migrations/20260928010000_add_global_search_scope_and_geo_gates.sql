-- CEOPRO AI - Real competitor-relevance gate: let a tenant explicitly
-- choose GLOBAL scope, and stop silently treating "no location evidence"
-- as "definitely local" or "definitely global."
--
-- Root cause this closes (see src/ai/pricing/competitor_classification.py
-- and src/market_scraper/discovery.py for the actual logic fix): the
-- existing search_scope_level (CITY/PROVINCE/COUNTRY/CUSTOM, added
-- 20260911000000) already lets a tenant pick a real local/regional/country
-- scope, but had no way to express "I genuinely want global competitors" -
-- a tenant who actually wants worldwide results had no honest value to
-- select, which is a real product gap, not just a classification bug.
--
-- global_competitors.country_code already exists
-- (20260827020000_add_competitor_country_code.sql) but was never actually
-- populated by either discovery path - this migration doesn't touch that
-- column, the code fix populates it from a real, free, zero-credential
-- signal (the discovered URL's own country-code top-level domain).

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_search_scope_level_check;
ALTER TABLE companies ADD CONSTRAINT companies_search_scope_level_check
    CHECK (search_scope_level IN ('CITY', 'PROVINCE', 'COUNTRY', 'GLOBAL', 'CUSTOM'));
