-- CEOPRO AI - Comprehensive market/engagement signal columns on
-- market_observations.
--
-- market_observations already captured product/listing metadata, safety
-- review, and the full raw payload (raw_payload jsonb), but had no
-- structured, indexed columns for: which product/competitor a row is
-- about without joining through competitor_product_mappings, which
-- platform/country it came from, price/availability at a glance (today
-- only in competitor_prices, a separate time-series table), or any social
-- engagement signal at all (likes, comments, shares, views, hashtags,
-- mentions, author, media type, publish vs. capture time). Everything
-- below was reachable only by querying inside raw_payload - not indexed,
-- not typed, not fast to search across products/competitors/platforms the
-- way a market-intelligence search needs.
--
-- product_id/global_competitor_id are denormalized from
-- competitor_product_mappings (already the source of truth via
-- mapping_id) specifically so a query can search "everything about this
-- product" or "everything about this competitor" without a join -
-- backfilled from the existing mapping_id for every historical row.

ALTER TABLE market_observations
    ADD COLUMN IF NOT EXISTS product_id UUID,
    ADD COLUMN IF NOT EXISTS global_competitor_id UUID,
    ADD COLUMN IF NOT EXISTS source_platform VARCHAR(50),
    ADD COLUMN IF NOT EXISTS country_code VARCHAR(2),
    ADD COLUMN IF NOT EXISTS price_amount NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS currency VARCHAR(3),
    ADD COLUMN IF NOT EXISTS is_available BOOLEAN,
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS author_name TEXT,
    ADD COLUMN IF NOT EXISTS author_handle TEXT,
    ADD COLUMN IF NOT EXISTS likes_count INTEGER,
    ADD COLUMN IF NOT EXISTS comments_count INTEGER,
    ADD COLUMN IF NOT EXISTS shares_count INTEGER,
    ADD COLUMN IF NOT EXISTS views_count INTEGER,
    ADD COLUMN IF NOT EXISTS engagement_captured_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS hashtags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS mentions JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS media_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS validation_status VARCHAR(20) NOT NULL DEFAULT 'PROMOTED';

-- Backfill product_id/global_competitor_id for any pre-existing rows from
-- their already-authoritative mapping - NOT VALID/no-op on an empty table,
-- real on one with history.
UPDATE market_observations mo
SET product_id = cpm.product_id, global_competitor_id = cpm.global_competitor_id
FROM competitor_product_mappings cpm
WHERE mo.tenant_id = cpm.tenant_id AND mo.mapping_id = cpm.mapping_id
  AND mo.product_id IS NULL;

ALTER TABLE market_observations
    ADD CONSTRAINT chk_market_obs_likes_nonneg CHECK (likes_count IS NULL OR likes_count >= 0),
    ADD CONSTRAINT chk_market_obs_comments_nonneg CHECK (comments_count IS NULL OR comments_count >= 0),
    ADD CONSTRAINT chk_market_obs_shares_nonneg CHECK (shares_count IS NULL OR shares_count >= 0),
    ADD CONSTRAINT chk_market_obs_views_nonneg CHECK (views_count IS NULL OR views_count >= 0),
    ADD CONSTRAINT chk_market_obs_price_nonneg CHECK (price_amount IS NULL OR price_amount >= 0),
    ADD CONSTRAINT chk_market_obs_currency_shape CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    ADD CONSTRAINT chk_market_obs_country_shape CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT chk_market_obs_validation_status
        CHECK (validation_status IN ('PROMOTED', 'QUARANTINED', 'REJECTED'));

-- Search-by-product and search-by-competitor, the two access patterns the
-- comprehensive market-data-record requirement calls out explicitly.
CREATE INDEX IF NOT EXISTS idx_market_observations_product
    ON market_observations(tenant_id, product_id, observed_at DESC)
    WHERE product_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_market_observations_competitor
    ON market_observations(tenant_id, global_competitor_id, observed_at DESC)
    WHERE global_competitor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_market_observations_platform
    ON market_observations(tenant_id, source_platform, observed_at DESC)
    WHERE source_platform IS NOT NULL;

COMMENT ON COLUMN market_observations.product_id IS
    'Denormalized from competitor_product_mappings.product_id (via mapping_id) for direct product search without a join.';
COMMENT ON COLUMN market_observations.global_competitor_id IS
    'Denormalized from competitor_product_mappings.global_competitor_id (via mapping_id) for direct competitor search without a join.';
COMMENT ON COLUMN market_observations.price_amount IS
    'Denormalized snapshot of the price captured with this observation - competitor_prices remains the authoritative time series pricing/ reads from; this column exists so one market_observations row is self-sufficient for search/RAG/trend use without a join.';
COMMENT ON COLUMN market_observations.validation_status IS
    'PROMOTED for every row in this table today (market_repository.save_market_record only inserts here after promotion) - persisted directly rather than only on market_observation_staging, which retention policy may purge (see maintenance.py) while this table is kept.';
