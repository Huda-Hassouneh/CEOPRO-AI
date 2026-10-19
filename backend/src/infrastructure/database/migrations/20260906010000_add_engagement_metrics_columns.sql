-- CEOPRO AI - Post/comment engagement metrics.
-- social_data_provider.py can now fetch a competitor's real per-post
-- aggregate counts (likes, shares, total comments) and per-comment
-- engagement (likes, replies) from a paid provider, but no column
-- anywhere could hold them - market_observations only had rating/
-- review_count (a 0-5 star rating and a count, sample_output_ready.json's
-- book-review shape) and reviews had no engagement columns at all.
-- Nullable throughout: every existing collector (books_to_scrape,
-- market_source, google_places, amazon_paapi) has nothing to report here
-- and must keep working unchanged.

ALTER TABLE market_observations
    ADD COLUMN IF NOT EXISTS like_count INT CHECK (like_count >= 0),
    ADD COLUMN IF NOT EXISTS share_count INT CHECK (share_count >= 0);

ALTER TABLE reviews
    ADD COLUMN IF NOT EXISTS like_count INT CHECK (like_count >= 0),
    ADD COLUMN IF NOT EXISTS reply_count INT CHECK (reply_count >= 0);
