-- CEOPRO AI - Web-search result cache + 3-tier competitor intelligence gate.
--
-- web_search_cache: identical catalog searches (same product name + geo
-- scope, whether from the same tenant re-running discovery or a
-- different tenant selling the same product) currently hit Google Custom
-- Search's real 100/day free-tier quota every time - a real, hard
-- multi-tenant scaling limit. Cached per exact query string (which
-- already encodes product name + geo scope + which discovery function
-- built it), with an expiry, so a repeat search is a cache hit, not a
-- second live API call. Deliberately NOT tenant-scoped/RLS-gated: a
-- cached "what URLs does Google return for this exact public search
-- string" result is public search-index metadata, not tenant-owned
-- data - the one table in this schema that intentionally doesn't need
-- tenant isolation, since sharing it across tenants is the entire point
-- (that's what makes it a real multi-tenant cost optimization).
CREATE TABLE IF NOT EXISTS web_search_cache (
    cache_key TEXT PRIMARY KEY,
    results_json JSONB NOT NULL,
    cached_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_search_cache_expires_at ON web_search_cache(expires_at);

-- tenant_competitors.tier: the 3-tier intelligence gate discussed this
-- session - CANDIDATE (registered, not yet evaluated as real), RELEVANT
-- (passed the manufacturer/region checks, but below the product-overlap
-- threshold), STRATEGIC (passed all three - the existing is_confirmed_
-- competitor gate). Real point: STRATEGIC is the only tier that should
-- ever get the expensive deep-collection (paid comment/review depth via
-- ScrapeCreators/Apify) turned on - see product_families.py::
-- recommended_collector_config(). in_operating_region was already being
-- COMPUTED in classify_competitor() but never persisted, so "relevant"
-- couldn't be queried later without recomputing - tier fixes that with
-- one additive column instead of adding a second unpersisted boolean.
ALTER TABLE tenant_competitors
    ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'CANDIDATE'
        CHECK (tier IN ('CANDIDATE', 'RELEVANT', 'STRATEGIC'));
