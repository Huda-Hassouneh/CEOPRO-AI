-- The legacy schedule lookup FK was retained because PostgreSQL truncated its
-- generated identifier to this 63-character name. Versioned custom cost rates
-- are referenced through cost_rate_id and no longer need this composite FK.
ALTER TABLE public.billing_custom_cost_bindings
    DROP CONSTRAINT IF EXISTS billing_custom_cost_bindings_budget_kind_provider_operatio_fkey;

