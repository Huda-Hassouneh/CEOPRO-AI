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

CREATE POLICY isolation_scraping_cost_ledger ON scraping_cost_ledger
    FOR ALL USING (tenant_id = get_current_tenant());
