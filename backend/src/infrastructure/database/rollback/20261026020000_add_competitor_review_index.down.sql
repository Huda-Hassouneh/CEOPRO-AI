-- Undoes migrations/20261026020000_add_competitor_review_index.sql. Only an index: nothing is lost, reads get slower.
DROP INDEX IF EXISTS idx_reviews_competitor;
