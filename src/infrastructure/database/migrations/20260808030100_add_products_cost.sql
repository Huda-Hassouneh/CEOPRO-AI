-- Closes PENDING_ACTIONS.md #14: without a cost/COGS basis,
-- src/ai/pricing/guardrails.py could only bound how far a suggested price
-- moves from the current price, not whether the result stays profitable.
-- Nullable - most products won't have this populated on day one, and
-- src/ai/pricing/guardrails.py's margin guardrail is a no-op when it's NULL,
-- same cold-start-friendly shape as every other optional signal in this track.

ALTER TABLE products ADD COLUMN IF NOT EXISTS cost NUMERIC(10, 2);
