-- Menus and prices published outside a competitor's own website (market_menus.py): its listings on
-- delivery / menu platforms, menu photos on its Google Maps listing and menu pictures anywhere on the web.
--
-- 1. A new competitor data facet, MARKET_MENUS. Additive: the facet check is widened.
-- 2. Price rows for reading menu pictures with a vision model (Gemini, or Groq's vision model). billing/credits.py
--    refuses a provider call that has no confirmed price, so the rows exist with a NULL price until an operator
--    sets it from the provider's bill (python -m scripts.billing_admin set-price ...). Until then OCR's reading
--    stands and nothing is sent. DO NOTHING keeps any price that was already recorded.

ALTER TABLE competitor_enrichment DROP CONSTRAINT IF EXISTS competitor_enrichment_facet_check;
ALTER TABLE competitor_enrichment ADD CONSTRAINT competitor_enrichment_facet_check
    CHECK (facet IN ('PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS', 'PRICES', 'SOCIAL_CONTENT', 'MARKET_MENUS'));

INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin, charged_on_failure,
                                     source, configured_by) VALUES
    ('data', 'gemini_vision', 'read_image', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from the Google AI Studio / Vertex bill', 'migration 20261101000000'),
    ('data', 'groq_vision', 'read_image', 'request', NULL, NULL, TRUE, 'Price not confirmed - set from console.groq.com/docs/models or a Groq invoice', 'migration 20261101000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;
