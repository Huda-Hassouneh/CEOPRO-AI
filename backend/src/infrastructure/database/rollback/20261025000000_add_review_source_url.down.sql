-- Undoes migrations/20261025000000_add_review_source_url.sql. Loses only the stored link to each comment's original
-- page (re-collected on the next comments refresh); the comments themselves stay.
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_source_url_http_check;
ALTER TABLE reviews DROP COLUMN IF EXISTS source_url;
