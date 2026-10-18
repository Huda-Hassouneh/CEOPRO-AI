-- Records an OWNER's explicit track / untrack choice on a competitor, so
-- automatic processes (re-scoring after discovery, auto-tracking) never
-- overturn it: a competitor the owner untracked is not silently re-tracked,
-- and one the owner tracked is not silently dropped by a category rule.
-- NULL = no explicit choice; the system's own classification applies.
ALTER TABLE tenant_competitors ADD COLUMN IF NOT EXISTS tracking_decision TEXT
    CHECK (tracking_decision IS NULL OR tracking_decision IN ('USER_TRACKED', 'USER_UNTRACKED'));
