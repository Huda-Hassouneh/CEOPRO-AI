-- The canonical usage reserve upsert explicitly inserts its audit timestamp.
-- No change to quotas or counter values; preserve the existing atomic upsert.
GRANT INSERT(updated_at) ON public.tenant_usage_counters TO ceopro_credit_accounting;
