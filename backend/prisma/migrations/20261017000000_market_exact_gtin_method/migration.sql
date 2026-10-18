-- Explicit provenance for the optional GTIN collector adapter.
-- Keep existing methods, RLS, grants, tenant FKs and score constraints intact.
BEGIN;
ALTER TABLE public.market_observations DROP CONSTRAINT market_observations_match_method_check;
ALTER TABLE public.market_observations ADD CONSTRAINT market_observations_match_method_check
    CHECK (match_method IN ('EXACT_SKU', 'FUZZY_NAME', 'EXACT_GTIN'));
COMMIT;
