-- Competitor comments are read by (tenant, competitor) on every comments list, the competitor overview, the
-- completeness check and the alerts bell, but reviews was indexed only by product and by parent. Partial index:
-- only competitor rows (product reviews are untouched), newest first for the "recent" sort and the 14-day alert window.
CREATE INDEX IF NOT EXISTS idx_reviews_competitor
    ON reviews (tenant_id, competitor_id, review_date DESC)
    WHERE subject_type = 'COMPETITOR';
