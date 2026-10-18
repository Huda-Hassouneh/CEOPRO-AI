-- Preserve feature-specific operational configuration when a custom quote is
-- accepted and converted into a plan. Existing plan-feature links remain valid.
ALTER TABLE "plan_features"
ADD COLUMN "metadata" JSONB;
