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
