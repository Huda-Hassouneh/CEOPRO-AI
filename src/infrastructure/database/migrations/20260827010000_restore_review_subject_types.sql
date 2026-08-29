-- CEOPRO AI - Restore multi-subject reviews and the full sentiment output
-- shape spec S16 requires.
--
-- Final_schema.sql's `reviews` is product-only (product_id UUID NOT NULL,
-- no subject_type/competitor_id at all) - spec S16 requires sentiment
-- analysis at PRODUCT, COMPETITOR, and BUSINESS-overall levels, and
-- sentiment/ + mpi/ were both built against all three. Confirmed with the
-- project owner directly (2026-08-27) to extend the table back to
-- supporting all three rather than reduce the feature to product-only.
--
-- Also restores spec S13's Collection Policy Engine columns
-- (source_status/collection_method), entirely absent from Final_schema.sql's
-- reviews - without them there is no column for "every data_access.py in
-- src/ai/ filters to ALLOWED only" to filter on at all.

ALTER TABLE reviews ALTER COLUMN product_id DROP NOT NULL;

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS subject_type VARCHAR(20) NOT NULL DEFAULT 'PRODUCT';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS competitor_id UUID;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS source_status VARCHAR(20) NOT NULL DEFAULT 'ALLOWED';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS collection_method VARCHAR(50) NOT NULL DEFAULT 'MANUAL';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS review_language VARCHAR(5);

-- product_id's existing FK (tenant_id, product_id) -> products(tenant_id, product_id)
-- already tolerates NULL product_id without modification (composite FKs with
-- any NULL component aren't checked, Postgres default MATCH SIMPLE).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_reviews_competitor_isolated'
    ) THEN
        ALTER TABLE reviews ADD CONSTRAINT fk_reviews_competitor_isolated
            FOREIGN KEY (tenant_id, competitor_id) REFERENCES tenant_competitors(tenant_id, global_competitor_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_subject_type') THEN
        ALTER TABLE reviews ADD CONSTRAINT chk_review_subject_type
            CHECK (subject_type IN ('PRODUCT', 'COMPETITOR', 'BUSINESS'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_subject_consistency') THEN
        ALTER TABLE reviews ADD CONSTRAINT chk_review_subject_consistency
            CHECK (
                (subject_type = 'PRODUCT' AND product_id IS NOT NULL AND competitor_id IS NULL) OR
                (subject_type = 'COMPETITOR' AND competitor_id IS NOT NULL AND product_id IS NULL) OR
                (subject_type = 'BUSINESS' AND product_id IS NULL AND competitor_id IS NULL)
            );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_collection_method') THEN
        ALTER TABLE reviews ADD CONSTRAINT chk_review_collection_method
            CHECK (collection_method IN ('MANUAL', 'PUBLIC_API', 'PUBLIC_FEED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_review_source_status') THEN
        ALTER TABLE reviews ADD CONSTRAINT chk_review_source_status
            CHECK (source_status IN ('ALLOWED', 'RESTRICTED', 'BLOCKED'));
    END IF;
END $$;

-- sentiment_results collapsed from a full 3-class probability distribution +
-- confidence (what src/ai/sentiment/model.py's classifier actually outputs
-- and spec S16 asks for) down to a single sentiment_score/sentiment_label.
-- Extending rather than replacing, same reasoning as evidence_records and
-- reviews above: the detail is real signal spec S16 wants preserved, not
-- redundant with the new columns, which src/ai/sentiment/evidence.py now
-- populates too (sentiment_score = positive_probability - negative_probability,
-- the same continuous-score formula already used for aggregation elsewhere
-- in this module).
ALTER TABLE sentiment_results ADD COLUMN IF NOT EXISTS positive_probability NUMERIC(5, 4);
ALTER TABLE sentiment_results ADD COLUMN IF NOT EXISTS neutral_probability NUMERIC(5, 4);
ALTER TABLE sentiment_results ADD COLUMN IF NOT EXISTS negative_probability NUMERIC(5, 4);
ALTER TABLE sentiment_results ADD COLUMN IF NOT EXISTS confidence NUMERIC(5, 4);
