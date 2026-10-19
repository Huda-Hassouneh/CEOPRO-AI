-- CEOPRO AI - Comment reply-threading.
--
-- Every comment social_data_provider.py/scrape_creators.py collects has
-- landed as an independent reviews row with only a reply_count (how many
-- replies IT has) - nothing recorded which comment a REPLY is itself
-- replying to, so a reply and its parent could never be reconstructed as
-- a real thread for sentiment analysis (a sarcastic reply agreeing with a
-- complaint reads very differently once you know what it's replying to).
--
-- parent_review_id closes that: nullable (a top-level comment, or any
-- review from a collector/platform that doesn't expose parent linkage -
-- ScrapeCreators' own live-confirmed Facebook payload does not - simply
-- has none), self-referencing within the same tenant using the identical
-- (tenant_id, review_id) composite every other reviews FK in this schema
-- already keys off of (uq_tenant_review_perimeter), so RLS isolation is
-- preserved the same way.
ALTER TABLE reviews
    ADD COLUMN IF NOT EXISTS parent_review_id UUID;

ALTER TABLE reviews DROP CONSTRAINT IF EXISTS fk_reviews_parent_isolated;
ALTER TABLE reviews ADD CONSTRAINT fk_reviews_parent_isolated
    FOREIGN KEY (tenant_id, parent_review_id) REFERENCES reviews(tenant_id, review_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_reviews_parent ON reviews(tenant_id, parent_review_id)
    WHERE parent_review_id IS NOT NULL;
