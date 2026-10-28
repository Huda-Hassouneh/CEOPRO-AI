-- Undoes migrations/20261101000000_add_market_menus_facet.sql. The MARKET_MENUS ledger rows are removed (the facts
-- they describe stay in competitor_intel); the vision price rows are removed only while still unpriced.
DELETE FROM competitor_enrichment WHERE facet = 'MARKET_MENUS';
ALTER TABLE competitor_enrichment DROP CONSTRAINT IF EXISTS competitor_enrichment_facet_check;
ALTER TABLE competitor_enrichment ADD CONSTRAINT competitor_enrichment_facet_check
    CHECK (facet IN ('PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS', 'PRICES', 'SOCIAL_CONTENT'));
DELETE FROM provider_cost_schedules
 WHERE budget_kind = 'data' AND provider IN ('gemini_vision', 'groq_vision') AND operation = 'read_image'
   AND unit_cost_usd IS NULL AND configured_by = 'migration 20261101000000';
