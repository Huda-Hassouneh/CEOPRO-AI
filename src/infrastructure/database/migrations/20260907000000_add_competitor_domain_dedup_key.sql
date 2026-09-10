-- CEOPRO AI - Domain-keyed competitor deduplication.
-- register_tenant_scoped_competitor() previously deduplicated on
-- LOWER(competitor_name) alone (uq_competitor_private). Two different
-- discovery paths finding the SAME real seller under two different
-- result titles (e.g. Google Custom Search returning "Buy Espresso
-- Machine - Acme Coffee Co" while a sitemap/SearchAction pass returns
-- "Acme Coffee | Espresso Machine") created two separate global_
-- competitors rows for one real business - a genuine duplicate-row bug,
-- not a hypothetical one, once more than one discovery path exists.
--
-- website_identity_key is the real fix: normalized to the hostname
-- (minus "www.") for an ordinary seller domain, where one hostname
-- really is one business. A bare hostname is NOT a safe identity key
-- for a social-only competitor (task: social-only discovery) - every
-- Instagram-based business shares the host "instagram.com", so the key
-- there is host + first path segment (the handle), computed in Python
-- (register_tenant_scoped_competitor) since that logic needs real
-- per-platform knowledge, not a portable SQL expression.

ALTER TABLE global_competitors
    ADD COLUMN IF NOT EXISTS website_identity_key TEXT;

-- Best-effort backfill for existing rows: hostname only (every
-- pre-existing row here is an ordinary seller domain, never a social
-- profile - social-only discovery didn't exist before this migration).
UPDATE global_competitors
SET website_identity_key = LOWER(REGEXP_REPLACE(
    SUBSTRING(website_url FROM '^[a-zA-Z]+://([^/]+)'), '^www\.', ''
))
WHERE website_identity_key IS NULL AND website_url IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_competitor_private_identity
    ON global_competitors (added_by_tenant_id, website_identity_key)
    WHERE (visibility = 'PRIVATE' AND website_identity_key IS NOT NULL);
