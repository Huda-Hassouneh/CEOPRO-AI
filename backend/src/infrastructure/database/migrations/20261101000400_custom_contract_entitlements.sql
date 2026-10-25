-- Preserve customer-selected module access on a paid Custom contract.
-- NULL is reserved for legacy contracts whose module selection was not stored;
-- an explicit JSON [] means the reviewed contract grants no modules.
ALTER TABLE public.tenant_custom_contracts
    ADD COLUMN IF NOT EXISTS included_features JSONB;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tenant_custom_contracts_included_features_shape') THEN
    ALTER TABLE public.tenant_custom_contracts
      ADD CONSTRAINT tenant_custom_contracts_included_features_shape CHECK (
        included_features IS NULL OR (
          jsonb_typeof(included_features)='array'
          AND NOT jsonb_path_exists(included_features, '$[*] ? (@.type() != "string")')
          AND included_features <@ '["market_intelligence","demand_prediction","competitor_management"]'::jsonb
        )
      );
  END IF;
END $$;

-- Module codes are cost-binding keys but are not numeric allowance rows.
INSERT INTO public.usage_features (feature_code, unit, aggregation_type, reset_cycle)
VALUES ('market_intelligence','enabled','max','billing_period'),
       ('demand_prediction','enabled','max','billing_period'),
       ('competitor_management','enabled','max','billing_period')
ON CONFLICT (feature_code) DO NOTHING;
