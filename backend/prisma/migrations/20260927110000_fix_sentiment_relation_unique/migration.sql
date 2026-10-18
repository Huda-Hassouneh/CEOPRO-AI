ALTER TABLE "sentiment_results"
ADD CONSTRAINT "uq_sentiment_tenant_review"
UNIQUE ("tenant_id", "review_id");
