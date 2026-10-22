-- Groq (the assistant's language model) is a paid provider: rows exist so operators
-- see what must be priced; NULL until a person confirms the price from Groq's model
-- docs or an invoice (python -m scripts.billing_admin set-price ...). Until then the
-- assistant answers with cited evidence instead of failing. DO NOTHING keeps any
-- price that was already recorded.
INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin, charged_on_failure,
                                     source, configured_by) VALUES
    ('ai', 'groq', 'openai/gpt-oss-20b', 'input_token', NULL, NULL, TRUE, 'Price not confirmed - set from console.groq.com/docs/models or a Groq invoice', 'migration 20261028000000'),
    ('ai', 'groq', 'openai/gpt-oss-20b', 'output_token', NULL, NULL, TRUE, 'Price not confirmed - set from console.groq.com/docs/models or a Groq invoice', 'migration 20261028000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;
