-- Where a collected comment can be read in full (e.g. the YouTube comment's own link), so the owner can open
-- the original and act on it. Nullable and additive; only http(s) links are accepted.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_source_url_http_check;
ALTER TABLE reviews ADD CONSTRAINT reviews_source_url_http_check
    CHECK (source_url IS NULL OR source_url ~ '^https?://');
