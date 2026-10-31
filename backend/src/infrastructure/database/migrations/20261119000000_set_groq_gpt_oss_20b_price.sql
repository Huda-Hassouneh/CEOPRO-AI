-- KEEL - Price the assistant's default language model so it actually answers.
--
-- Root cause of "the chatbot only returns retrieved evidence, never a written
-- answer": migration 20261028000000 seeded groq / openai/gpt-oss-20b with NULL
-- prices, on the rule "don't call a paid API at an unknown cost". The billing
-- gate (src/ai/billing/credits.py::_cost) raises COST_NOT_CONFIGURED whenever a
-- unit price is NULL, and the assistant (rag/advisor.py) then degrades to
-- "evidence mode" and never calls the model - even when GROQ_API_KEY is set and
-- valid. So a correctly-configured deployment still showed no real answers.
--
-- This sets Groq's published list price for openai/gpt-oss-20b, confirmed from
-- Groq's model documentation (console.groq.com/docs/model/openai/gpt-oss-20b)
-- on 2026-11-19: $0.075 per 1M input tokens, $0.30 per 1M output tokens, and a
-- 50%-discounted cached-input rate of $0.037 per 1M. Stored per token in USD.
-- An operator can override any of these at any time with
--   python -m scripts.billing_admin set-price --budget ai --provider groq \
--     --operation openai/gpt-oss-20b --unit input_token --usd-per-million <rate>
-- Re-runnable: UPDATE only touches the rows, and the cached-input row is
-- inserted only if missing (ON CONFLICT DO NOTHING).

UPDATE provider_cost_schedules
   SET unit_cost_usd = 0.000000075, safety_margin = 0, cost_is_final = TRUE,
       source = 'Groq list price, console.groq.com/docs/model/openai/gpt-oss-20b, verified 2026-11-19',
       configured_by = 'migration 20261119000000', updated_at = NOW()
 WHERE budget_kind = 'ai' AND provider = 'groq' AND operation = 'openai/gpt-oss-20b' AND unit = 'input_token';

UPDATE provider_cost_schedules
   SET unit_cost_usd = 0.000000300, safety_margin = 0, cost_is_final = TRUE,
       source = 'Groq list price, console.groq.com/docs/model/openai/gpt-oss-20b, verified 2026-11-19',
       configured_by = 'migration 20261119000000', updated_at = NOW()
 WHERE budget_kind = 'ai' AND provider = 'groq' AND operation = 'openai/gpt-oss-20b' AND unit = 'output_token';

INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin,
                                     charged_on_failure, cost_is_final, source, configured_by) VALUES
    ('ai', 'groq', 'openai/gpt-oss-20b', 'cache_read_token', 0.000000037, 0, TRUE, TRUE,
     'Groq cached-input list price, console.groq.com/docs/model/openai/gpt-oss-20b, verified 2026-11-19', 'migration 20261119000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;
