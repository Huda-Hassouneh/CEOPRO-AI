-- Two more competitor data facets (NEWS, COMMENTS) and where a news item came from.
--
-- NEWS: what a competitor published itself (its own website feed) and what news
-- search found about it. COMMENTS: public comments on videos about it, with likes.
-- Additive: the facet check is widened, market_news gains two nullable columns.

ALTER TABLE competitor_enrichment DROP CONSTRAINT IF EXISTS competitor_enrichment_facet_check;
ALTER TABLE competitor_enrichment ADD CONSTRAINT competitor_enrichment_facet_check
    CHECK (facet IN ('PROFILE', 'SOCIAL_LINKS', 'REVIEWS', 'NEWS', 'COMMENTS', 'PRICES', 'SOCIAL_CONTENT'));

-- 'own_site' (the competitor's own feed), 'web_search' (a news search), 'gdelt' (the industry scan).
ALTER TABLE market_news ADD COLUMN IF NOT EXISTS source_kind VARCHAR(20);
-- A short excerpt as the source published it (a feed's description), never generated text.
ALTER TABLE market_news ADD COLUMN IF NOT EXISTS summary TEXT;
