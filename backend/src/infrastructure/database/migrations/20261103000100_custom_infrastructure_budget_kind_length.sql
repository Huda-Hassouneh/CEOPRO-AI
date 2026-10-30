-- Infrastructure is a distinct supported pricing budget category and must
-- fit in the existing versioned cost-rate and binding columns.
ALTER TABLE public.billing_custom_cost_rates
  ALTER COLUMN budget_kind TYPE VARCHAR(20);
ALTER TABLE public.billing_custom_cost_bindings
  ALTER COLUMN budget_kind TYPE VARCHAR(20);
