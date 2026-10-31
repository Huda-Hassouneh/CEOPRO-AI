-- Undoes migrations/20261119000000_set_groq_gpt_oss_20b_price.sql: returns the
-- Groq default-model prices to NULL (the assistant then falls back to evidence
-- mode again) and removes the cached-input row.
UPDATE provider_cost_schedules
   SET unit_cost_usd = NULL, safety_margin = NULL,
       source = 'Price not confirmed - set from console.groq.com/docs/models or a Groq invoice',
       configured_by = 'rollback 20261119000000', updated_at = NOW()
 WHERE budget_kind = 'ai' AND provider = 'groq' AND operation = 'openai/gpt-oss-20b'
   AND unit IN ('input_token', 'output_token');

DELETE FROM provider_cost_schedules
 WHERE budget_kind = 'ai' AND provider = 'groq' AND operation = 'openai/gpt-oss-20b' AND unit = 'cache_read_token';
