-- Price changes on a competitor's own menu / site / posts, and the owner's decisions on which of their items is
-- which of the company's products.
--
-- competitor_price_history: competitor_intel rows are REPLACED on every re-read of a site, so by itself a price that
-- moved leaves no trace (only prices matched to the company's own products had a history, in competitor_prices).
-- This table keeps one row per (item, currency, price) with when it was first and last seen; a CHANGE is a row whose
-- predecessor for the same item has another price. Written by competitor_intel.save_site_intel / save_channel_facts.
-- confidence / extracted_by / verified are kept so a change between two weak reads (OCR, captions) can be told
-- apart from one between two reliable reads and never raises an alert on its own.
--
-- competitor_match_override: the automatic match of a competitor's item to one of the company's products can be wrong
-- ("Mansaf tray" vs "Mansaf plate"). REJECTED = this item is never matched to this product; MATCHED = the owner
-- chose this item for this product. offerings.record_matches reads it on every pass.
--
-- Additive: two new tables, nothing else touched.

CREATE TABLE IF NOT EXISTS competitor_price_history (
    history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    name_key TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price NUMERIC(14, 4) NOT NULL CHECK (price >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'XXX',
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_url TEXT,
    extracted_by VARCHAR(20),
    channel VARCHAR(20),
    confidence NUMERIC(4, 3),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_price_history_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE,
    CONSTRAINT chk_price_history_seen CHECK (last_seen_at >= first_seen_at)
);
CREATE INDEX IF NOT EXISTS idx_price_history_item
    ON competitor_price_history (tenant_id, global_competitor_id, name_key, currency, first_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_recent
    ON competitor_price_history (tenant_id, first_seen_at DESC, history_id);  -- matches list_changes' ORDER BY, so a page stops early

ALTER TABLE competitor_price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_price_history FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_competitor_price_history ON competitor_price_history
    FOR ALL USING (tenant_id = get_current_tenant());

CREATE TABLE IF NOT EXISTS competitor_match_override (
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    product_id UUID NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    item_name TEXT,
    verdict VARCHAR(10) NOT NULL CHECK (verdict IN ('REJECTED', 'MATCHED')),
    decided_by UUID NOT NULL,
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, global_competitor_id, product_id, item_key),
    CONSTRAINT fk_match_override_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE
);
-- At most one item the owner chose per product and competitor.
CREATE UNIQUE INDEX IF NOT EXISTS uq_match_override_one_choice
    ON competitor_match_override (tenant_id, global_competitor_id, product_id) WHERE verdict = 'MATCHED';

ALTER TABLE competitor_match_override ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_match_override FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_competitor_match_override ON competitor_match_override
    FOR ALL USING (tenant_id = get_current_tenant());
