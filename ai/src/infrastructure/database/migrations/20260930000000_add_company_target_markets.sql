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
