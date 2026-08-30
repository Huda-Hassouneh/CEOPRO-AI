-- CEOPRO AI - Complete market collection provenance, scoring, events, and alerts.

ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS collector_key VARCHAR(64);
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS render_javascript BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS collector_config JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS source_id UUID;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS external_review_id TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS safety_status VARCHAR(20) NOT NULL DEFAULT 'SAFE';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS safety_flags JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS chk_review_safety_status;
ALTER TABLE reviews ADD CONSTRAINT chk_review_safety_status
    CHECK (safety_status IN ('SAFE', 'QUARANTINED'));
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS chk_review_collection_method;
ALTER TABLE reviews ADD CONSTRAINT chk_review_collection_method CHECK (
    collection_method IN ('MANUAL', 'PUBLIC_API', 'PUBLIC_FEED', 'STRUCTURED_DATA', 'WEB_SCRAPE')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_external_source
    ON reviews(tenant_id, source_id, external_review_id)
    WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS market_observations (
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_id UUID NOT NULL,
    job_id UUID NOT NULL,
    mapping_id UUID NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT,
    description TEXT,
    canonical_url TEXT NOT NULL,
    image_url TEXT,
    external_id TEXT,
    rating NUMERIC(3, 2) CHECK (rating BETWEEN 0 AND 5),
    review_count INT CHECK (review_count >= 0),
    stock_quantity INT CHECK (stock_quantity >= 0),
    match_score NUMERIC(5, 4) NOT NULL CHECK (match_score BETWEEN 0.82 AND 1),
    match_method VARCHAR(20) NOT NULL CHECK (match_method IN ('EXACT_SKU', 'FUZZY_NAME')),
    page_text TEXT,
    safety_status VARCHAR(20) NOT NULL DEFAULT 'SAFE'
        CHECK (safety_status IN ('SAFE', 'QUARANTINED')),
    safety_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash CHAR(64) NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_market_observation_source FOREIGN KEY (tenant_id, source_id)
        REFERENCES data_sources(tenant_id, source_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_observation_job FOREIGN KEY (tenant_id, job_id)
        REFERENCES ingestion_jobs(tenant_id, job_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_observation_mapping FOREIGN KEY (tenant_id, mapping_id)
        REFERENCES competitor_product_mappings(tenant_id, mapping_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_market_observations_timeline
    ON market_observations(tenant_id, mapping_id, observed_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_observation_content
    ON market_observations(tenant_id, mapping_id, content_hash, observed_at);

CREATE TABLE IF NOT EXISTS market_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    global_competitor_id UUID NOT NULL,
    mapping_id UUID,
    source_id UUID,
    event_type VARCHAR(32) NOT NULL CHECK (event_type IN
        ('PRICE_CHANGED', 'PRODUCT_DISCOVERED', 'AVAILABILITY_CHANGED', 'SENTIMENT_CHANGED')),
    old_value JSONB,
    new_value JSONB NOT NULL,
    source_url TEXT,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    collected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_market_event_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors(tenant_id, global_competitor_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_event_mapping FOREIGN KEY (tenant_id, mapping_id)
        REFERENCES competitor_product_mappings(tenant_id, mapping_id) ON DELETE CASCADE,
    CONSTRAINT fk_market_event_source FOREIGN KEY (tenant_id, source_id)
        REFERENCES data_sources(tenant_id, source_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_market_events_timeline
    ON market_events(tenant_id, global_competitor_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS competitor_score_snapshots (
    score_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    price_score NUMERIC(5, 2) CHECK (price_score BETWEEN 0 AND 100),
    sentiment_score NUMERIC(5, 2) CHECK (sentiment_score BETWEEN 0 AND 100),
    market_activity_score NUMERIC(5, 2) CHECK (market_activity_score BETWEEN 0 AND 100),
    relevance_score NUMERIC(5, 2) CHECK (relevance_score BETWEEN 0 AND 100),
    composite_score NUMERIC(5, 2) NOT NULL CHECK (composite_score BETWEEN 0 AND 100),
    missing_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_score_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors(tenant_id, global_competitor_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_competitor_scores_leaderboard
    ON competitor_score_snapshots(tenant_id, composite_score DESC, calculated_at DESC);

CREATE TABLE IF NOT EXISTS market_alert_rules (
    alert_rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    global_competitor_id UUID NOT NULL,
    metric VARCHAR(32) NOT NULL CHECK (metric IN
        ('PRICE_CHANGE_PERCENT', 'COMPOSITE_SCORE', 'SENTIMENT_SCORE', 'MARKET_ACTIVITY_SCORE')),
    operator VARCHAR(4) NOT NULL CHECK (operator IN ('GT', 'GTE', 'LT', 'LTE')),
    threshold NUMERIC(12, 4) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_market_alert_rule_tenant UNIQUE (tenant_id, alert_rule_id),
    CONSTRAINT fk_alert_competitor FOREIGN KEY (tenant_id, global_competitor_id)
        REFERENCES tenant_competitors(tenant_id, global_competitor_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS market_alert_events (
    alert_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES companies(tenant_id) ON DELETE CASCADE,
    alert_rule_id UUID NOT NULL REFERENCES market_alert_rules(alert_rule_id) ON DELETE CASCADE,
    market_event_id UUID REFERENCES market_events(event_id) ON DELETE SET NULL,
    observed_value NUMERIC(12, 4) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_market_alert_events_unread
    ON market_alert_events(tenant_id, created_at DESC) WHERE acknowledged_at IS NULL;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'market_observations', 'market_events', 'competitor_score_snapshots',
        'market_alert_rules', 'market_alert_events'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = table_name AND policyname = 'tenant_isolation') THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I FOR ALL USING (tenant_id = get_current_tenant()) WITH CHECK (tenant_id = get_current_tenant())',
                table_name
            );
        END IF;
    END LOOP;
END $$;
