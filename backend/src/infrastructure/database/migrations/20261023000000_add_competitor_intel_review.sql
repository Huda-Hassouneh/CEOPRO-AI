-- Owner verification of the prices read from a competitor's website / menus.
--
-- competitor_intel rows are REPLACED on every re-read of a site, so a decision
-- made on a row (confirmed, corrected, rejected) would be lost. This table
-- keeps the decision keyed by what was READ - (normalized item name, the price
-- as read) - and save_site_intel re-applies it to every later read:
--   CONFIRMED  the fact is marked verified (confidence 1.0)
--   CORRECTED  the owner's price replaces the one read (the read price is kept in the fact)
--   REJECTED   the fact is dropped
-- If the site later shows a DIFFERENT price for the item, the new price is a
-- new, unreviewed fact: a confirmation of an old price never vouches for a new one.
--
-- Additive: one new table, nothing else touched.

CREATE TABLE IF NOT EXISTS competitor_intel_review (
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    name_key TEXT NOT NULL,
    read_price NUMERIC(14, 4) NOT NULL CHECK (read_price >= 0),
    verdict VARCHAR(10) NOT NULL CHECK (verdict IN ('CONFIRMED', 'CORRECTED', 'REJECTED')),
    item_name TEXT,
    corrected_price NUMERIC(14, 4) CHECK (corrected_price IS NULL OR corrected_price >= 0),
    currency VARCHAR(3) CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    note TEXT,
    reviewed_by UUID NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, global_competitor_id, name_key, read_price),
    CONSTRAINT chk_review_correction CHECK ((verdict = 'CORRECTED') = (corrected_price IS NOT NULL)),
    CONSTRAINT fk_intel_review_tenant_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors (tenant_id, global_competitor_id) ON DELETE CASCADE
);

ALTER TABLE competitor_intel_review ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_intel_review FORCE ROW LEVEL SECURITY;

CREATE POLICY isolation_competitor_intel_review ON competitor_intel_review
    FOR ALL USING (tenant_id = get_current_tenant());
