-- Keel market-worker compatibility. Application auth, billing and RLS remain Node-owned.
-- Reviewed additive market schema from the supplied Python runtime.

-- Source: 20260911000000_add_geo_proximity_and_competitor_scope.sql
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

-- Source: 20260915000000_add_scraping_cost_ledger.sql
-- CEOPRO AI - Scraping Cost Ledger.
-- One real row per actual scrape attempt that resolved to a mapped product
-- (mirrors competitor_prices' own mapping_id anchor) - the real spend
-- record src/market_scraper/cost_ledger.py's dynamic cost-to-margin gate
-- reads to decide whether continuing to track a product is still worth
-- what it costs.
--
-- cost_amount is nullable ON PURPOSE: a collector whose real per-request
-- price hasn't been configured yet (no SCRAPE_COST_PER_REQUEST_<NAME> env
-- var set) still gets a ledger row - honestly marking the cost unknown -
-- rather than a fabricated $0.00 that would make an unmetered collector
-- look free and silently defeat the whole point of this table.

CREATE TABLE IF NOT EXISTS scraping_cost_ledger (
    cost_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    mapping_id UUID NOT NULL,
    collector_key VARCHAR(64) NOT NULL,
    cost_amount NUMERIC(12, 6) CHECK (cost_amount >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_cost_ledger_mapping_isolated FOREIGN KEY (tenant_id, mapping_id)
        REFERENCES competitor_product_mappings(tenant_id, mapping_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_mapping_time ON scraping_cost_ledger(tenant_id, mapping_id, observed_at DESC);

ALTER TABLE scraping_cost_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraping_cost_ledger FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='scraping_cost_ledger' AND policyname='isolation_scraping_cost_ledger') THEN
  CREATE POLICY isolation_scraping_cost_ledger ON scraping_cost_ledger FOR ALL USING (tenant_id = get_current_tenant());
 END IF;
END $$;

-- Source: 20260928010000_add_global_search_scope_and_geo_gates.sql
-- CEOPRO AI - Real competitor-relevance gate: let a tenant explicitly
-- choose GLOBAL scope, and stop silently treating "no location evidence"
-- as "definitely local" or "definitely global."
--
-- Root cause this closes (see src/ai/pricing/competitor_classification.py
-- and src/market_scraper/discovery.py for the actual logic fix): the
-- existing search_scope_level (CITY/PROVINCE/COUNTRY/CUSTOM, added
-- 20260911000000) already lets a tenant pick a real local/regional/country
-- scope, but had no way to express "I genuinely want global competitors" -
-- a tenant who actually wants worldwide results had no honest value to
-- select, which is a real product gap, not just a classification bug.
--
-- global_competitors.country_code already exists
-- (20260827020000_add_competitor_country_code.sql) but was never actually
-- populated by either discovery path - this migration doesn't touch that
-- column, the code fix populates it from a real, free, zero-credential
-- signal (the discovered URL's own country-code top-level domain).

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_search_scope_level_check;
ALTER TABLE companies ADD CONSTRAINT companies_search_scope_level_check
    CHECK (search_scope_level IN ('CITY', 'PROVINCE', 'COUNTRY', 'GLOBAL', 'CUSTOM'));

-- Source: 20260930000000_add_company_target_markets.sql
-- CEOPRO AI - Explicit commercial Target Markets.
--
-- Deliberately a NEW, separate table, not a column on companies: Target
-- Markets answer a different question ("which countries do we want to
-- COMPETE IN commercially") than every existing geography field on
-- companies -
--   - country_code / operating_countries: where the business is
--     registered/actually operates from (company_target_markets.py never
--     reads or writes these).
--   - search_scope_level / default_search_radius_km / latitude /
--     longitude / city: HOW FAR competitor discovery searches around the
--     tenant's own location (company_geo_profile.py).
-- A tenant fully entitled to sell in a market it doesn't operate in, or
-- want its discovery radius widened to (a manufacturer whose factory is
-- in one country but whose real target buyers are in three others), needs
-- to express that as a third, independent fact - never inferred from the
-- other two, from uploaded files, from business_type, or from the product
-- catalog (see company_target_markets.py's own docstring for why: no
-- signal on this platform can honestly claim to know WHERE a tenant wants
-- to compete, only a human explicitly saying so).
--
-- One row per (tenant, country) rather than a single TEXT[] column on
-- companies (unlike operating_countries) so RLS can isolate it exactly
-- like every other tenant-scoped child table in this schema (tenant_
-- competitors, competitor_product_mappings, campaign_content) - a REPLACE-
-- style PUT (company_target_markets.py::set_tenant_target_markets) is
-- still a normal DELETE+INSERT under one transaction, not a per-row API.

CREATE TABLE IF NOT EXISTS company_target_markets (
    target_market_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    country_code VARCHAR(2) NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_company_target_markets_tenant_country UNIQUE (tenant_id, country_code)
);

CREATE INDEX IF NOT EXISTS idx_company_target_markets_tenant ON company_target_markets(tenant_id);

ALTER TABLE company_target_markets ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_target_markets FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'company_target_markets' AND policyname = 'isolation_company_target_markets'
    ) THEN
        CREATE POLICY isolation_company_target_markets ON company_target_markets
            FOR ALL USING (tenant_id = get_current_tenant());
    END IF;
END $$;

-- Source: 20260930010000_add_target_market_type.sql
-- CEOPRO AI - Target Markets: support COUNTRY, REGION, and GLOBAL scope,
-- not just a bare country code.
--
-- Real gap in the original company_target_markets table (20260930000000):
-- country_code-only meant a tenant could only ever declare individual
-- countries, never "I want to compete across this whole region" (without
-- listing every country in it) or "I want to compete globally" as a
-- first-class target-market fact separate from search_scope_level=GLOBAL
-- (a different, existing concept - see company_target_markets.py's own
-- docstring). This migration adds market_type + region_name and makes
-- country_code conditionally required instead of always-required.
--
-- REGION is deliberately free text (region_name), never a fixed
-- enum/lookup table of named regions ("Middle East", "Europe", ...) -
-- this platform has no authoritative, industry-agnostic region->country
-- mapping anywhere (confirmed: iso_countries.py only maps individual
-- ISO codes to names), and inventing one would mean guessing which
-- countries a human-typed region name actually includes - exactly the
-- kind of fabrication this whole feature exists to avoid. A declared
-- REGION is real, honest evidence for discovery's own search-bias text
-- (sector_detection.py::resolve_tenant_geo_scope() - a search engine can
-- interpret "Middle East" as a real query term), but competitor_
-- classification.py's own country-evidence gate only ever trusts an
-- unambiguous ISO country_code match (a COUNTRY-type entry) or a
-- declared GLOBAL entry, never a REGION string it cannot honestly resolve
-- to a country list.

ALTER TABLE company_target_markets
    ADD COLUMN IF NOT EXISTS market_type VARCHAR(10) NOT NULL DEFAULT 'COUNTRY',
    ADD COLUMN IF NOT EXISTS region_name VARCHAR(100);

ALTER TABLE company_target_markets ALTER COLUMN country_code DROP NOT NULL;

ALTER TABLE company_target_markets DROP CONSTRAINT IF EXISTS company_target_markets_country_code_check;
ALTER TABLE company_target_markets ADD CONSTRAINT chk_target_markets_country_code_format
    CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$');

ALTER TABLE company_target_markets DROP CONSTRAINT IF EXISTS chk_target_markets_market_type;
ALTER TABLE company_target_markets ADD CONSTRAINT chk_target_markets_market_type
    CHECK (market_type IN ('COUNTRY', 'REGION', 'GLOBAL'));

-- Each market_type carries exactly the field(s) that make sense for it -
-- a COUNTRY row with a region_name set, or a GLOBAL row with either set,
-- is a real data-integrity bug this constraint catches at write time
-- rather than leaving it to application code alone.
ALTER TABLE company_target_markets DROP CONSTRAINT IF EXISTS chk_target_markets_shape;
ALTER TABLE company_target_markets ADD CONSTRAINT chk_target_markets_shape CHECK (
    (market_type = 'COUNTRY' AND country_code IS NOT NULL AND region_name IS NULL)
    OR (market_type = 'REGION' AND region_name IS NOT NULL AND country_code IS NULL)
    OR (market_type = 'GLOBAL' AND country_code IS NULL AND region_name IS NULL)
);

-- Replaces the old country-only unique constraint with three type-scoped
-- partial unique indexes: at most one row per (tenant, country) among
-- COUNTRY rows, at most one row per (tenant, region name, case-
-- insensitive) among REGION rows, and at most ONE GLOBAL row per tenant
-- ever (a second "compete globally" declaration is meaningless).
ALTER TABLE company_target_markets DROP CONSTRAINT IF EXISTS uq_company_target_markets_tenant_country;
DROP INDEX IF EXISTS uq_company_target_markets_tenant_country;

CREATE UNIQUE INDEX IF NOT EXISTS uq_target_markets_country
    ON company_target_markets(tenant_id, country_code) WHERE market_type = 'COUNTRY';
CREATE UNIQUE INDEX IF NOT EXISTS uq_target_markets_region
    ON company_target_markets(tenant_id, lower(region_name)) WHERE market_type = 'REGION';
CREATE UNIQUE INDEX IF NOT EXISTS uq_target_markets_global
    ON company_target_markets(tenant_id) WHERE market_type = 'GLOBAL';


-- Restricted collection roles still use table RLS; no auth, billing, or global RLS function changes.
DO $$ DECLARE worker_role text; BEGIN
 FOREACH worker_role IN ARRAY ARRAY['ceopro_app','ceopro_ai_test_writer'] LOOP
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=worker_role) THEN
   EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.scraping_cost_ledger, public.company_target_markets TO %I',worker_role);
  END IF;
 END LOOP;
END $$;
