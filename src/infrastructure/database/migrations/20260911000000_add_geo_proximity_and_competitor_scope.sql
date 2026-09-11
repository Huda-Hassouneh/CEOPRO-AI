-- CEOPRO AI - Region-aware competitor discovery: proximity + breadth.
--
-- Two real product asks from this session, neither served by the existing
-- schema:
--
-- 1. "The competitor must be in the same target region... though we can
--    ultimately rank or filter them based on the user's preference/input."
--    companies.operating_countries (already exists) answers the coarse
--    country-level allow-list, but a continuous "closest to farthest"
--    ranking with a user-adjustable radius needs real coordinates, not
--    just a country match - hence latitude/longitude here, plus a
--    persisted distance_km so proximity sorting never has to recompute
--    the haversine distance on every read.
-- 2. "Determine whether they are competing across most products (a broad
--    domain competitor) or just on a single product (a niche/item
--    competitor)." - product_match_rate already exists but had no
--    persisted breadth label; competitor_scope adds one without
--    replacing the existing tier (CANDIDATE/RELEVANT/STRATEGIC), which
--    answers a different question ("is this a real, trackable
--    competitor") from breadth ("how much of my catalog do they cover").

-- companies: the tenant's own search-scope profile. Nullable - existing
-- tenants have none of this set until they (or a geocoding step) supply
-- it; every consumer of these columns must degrade honestly when they're
-- NULL, never fabricate a location.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS city VARCHAR(150);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;
-- Tenant-adjustable default radius for domain-level discovery ("expand or
-- narrow the search area radius directly from the interface") - this is
-- the persisted default a UI writes to; any single discovery/listing call
-- can still pass its own radius_km to override it for one request without
-- touching this stored preference.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS default_search_radius_km INTEGER
    CHECK (default_search_radius_km IS NULL OR default_search_radius_km > 0);
-- UX fix: end users select a named scope, never type a raw kilometer
-- figure ("how is a user supposed to guess the exact kilometer
-- distance?"). CITY/PROVINCE resolve to a preset default_search_radius_km
-- (company_geo_profile.py::SCOPE_LEVEL_PRESET_RADIUS_KM) computed by the
-- backend; COUNTRY means no radius filter at all (operating_countries
-- alone decides scope); CUSTOM is the one escape hatch for a caller that
-- genuinely wants to set its own km (an advanced/API setting, not the
-- default UI path). Defaults to PROVINCE - a reasonable "nearby, not just
-- my city, not the whole country" starting point for a new tenant.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS search_scope_level TEXT NOT NULL DEFAULT 'PROVINCE'
    CHECK (search_scope_level IN ('CITY', 'PROVINCE', 'COUNTRY', 'CUSTOM'));

-- global_competitors: real coordinates when a discovery source provides
-- them (e.g. Google Places' geometry.location); city is a human-readable
-- fallback for when only a place name/locality is known, not a real
-- lat/lng pair.
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS city VARCHAR(150);
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
ALTER TABLE global_competitors ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;

-- tenant_competitors: per-tenant-pair facts that depend on both sides
-- (distance) or on this tenant's own catalog (scope), so they don't
-- belong on the global, tenant-independent global_competitors row.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS distance_km DOUBLE PRECISION;
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS competitor_scope TEXT
    CHECK (competitor_scope IS NULL OR competitor_scope IN ('NICHE_ITEM', 'PARTIAL_OVERLAP', 'BROAD_DOMAIN'));
-- Which discovery path found this competitor - product-level search is
-- the only one implemented so far (PRODUCT_SEARCH); PLACES_NEARBY and
-- INDUSTRY_KEYWORD_SEARCH are reserved for the hybrid domain-level
-- discovery sources planned as the next phase, so this column doesn't
-- need a second migration once they land.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS discovery_method TEXT
    CHECK (discovery_method IS NULL OR discovery_method IN ('PRODUCT_SEARCH', 'PLACES_NEARBY', 'INDUSTRY_KEYWORD_SEARCH'));

CREATE INDEX IF NOT EXISTS idx_tenant_competitors_distance ON tenant_competitors (tenant_id, distance_km);
