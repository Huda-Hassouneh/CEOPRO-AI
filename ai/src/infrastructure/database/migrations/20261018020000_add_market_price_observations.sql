-- Market reference prices: prices for a tenant's product found on the open
-- market (a seller's public page, a public price database, a shopping
-- search) rather than from a tracked competitor's mapped product page.
-- Deliberately NOT written to competitor_prices: those rows are tied to a
-- tracked competitor and a policy-approved source and feed competitor
-- analytics; a reference price is weaker evidence and is labelled as such.
--
-- market_price_lookups records every lookup attempt per product, so a product
-- with no price shows when it was last tried and why nothing came back, and a
-- product is not searched again (and paid for) before the retry interval.

CREATE TABLE IF NOT EXISTS market_price_observations (
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    provider VARCHAR(40) NOT NULL,
    seller_name TEXT,
    product_title TEXT,
    source_url TEXT,
    price NUMERIC(12, 4) NOT NULL CHECK (price >= 0),
    currency VARCHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    rating NUMERIC(3, 2) CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
    review_count INTEGER CHECK (review_count IS NULL OR review_count >= 0),
    -- How well the listing's title matches our product (0-1).
    match_score DOUBLE PRECISION NOT NULL CHECK (match_score >= 0 AND match_score <= 1),
    -- NULL = could not be judged (no exchange rate); FALSE = far from the product's own price, kept but not counted.
    plausible BOOLEAN,
    dedupe_key TEXT NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_market_price_observation UNIQUE (tenant_id, product_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_market_price_obs_product ON market_price_observations (tenant_id, product_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS market_price_lookups (
    tenant_id UUID NOT NULL,
    product_id UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    outcome VARCHAR(20) NOT NULL CHECK (outcome IN ('FOUND', 'NOTHING_FOUND', 'NOT_CONFIGURED', 'PROVIDER_ERROR')),
    providers_tried JSONB NOT NULL DEFAULT '[]'::jsonb,
    quotes_found INTEGER NOT NULL DEFAULT 0 CHECK (quotes_found >= 0),
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    last_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, product_id)
);

ALTER TABLE market_price_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_price_observations FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_market_price_observations ON market_price_observations
    FOR ALL USING (tenant_id = get_current_tenant());

ALTER TABLE market_price_lookups ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_price_lookups FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_market_price_lookups ON market_price_lookups
    FOR ALL USING (tenant_id = get_current_tenant());
