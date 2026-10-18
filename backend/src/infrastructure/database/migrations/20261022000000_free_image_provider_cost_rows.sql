-- Marketing image generation: price rows for the free provider pool.
--
-- billing/credits.py refuses a provider call that has no confirmed price, so
-- every provider the image pool can use needs a row. Free-tier services cost
-- the platform nothing: a zero price makes the call free in the ledger.

-- Providers that are free by design (new rows; never overwrites an existing one).
INSERT INTO provider_cost_schedules (budget_kind, provider, operation, unit, unit_cost_usd, safety_margin, charged_on_failure,
                                     source, configured_by) VALUES
    ('ai', 'together', 'image_generation', 'image', 0, 0, FALSE, 'Together free FLUX.1-schnell-Free model, no charge', 'migration 20261022000000'),
    ('ai', 'gemini', 'image_generation', 'image', 0, 0, FALSE, 'Google AI Studio free-tier key, no charge', 'migration 20261022000000'),
    ('ai', 'aihorde', 'image_generation', 'image', 0, 0, FALSE, 'AI Horde community network, no charge', 'migration 20261022000000')
ON CONFLICT (budget_kind, provider, operation, unit) DO NOTHING;

-- Cloudflare Workers AI and Hugging Face were left unpriced (NULL = "set from the
-- bill"). The image pool is meant to run on their FREE plans, where usage past the
-- free allowance is refused by the provider rather than billed, so the price is 0.
-- Only rows still NULL are touched. IF A COMPANY'S ACCOUNT IS ON A PAID PLAN, set the
-- real price instead (UPDATE provider_cost_schedules SET unit_cost_usd = ..., safety_margin = ...).
UPDATE provider_cost_schedules
   SET unit_cost_usd = 0, safety_margin = 0, charged_on_failure = FALSE,
       source = 'Free-plan account (usage past the free allowance is refused, not billed); set a real price if the account is on a paid plan',
       configured_by = 'migration 20261022000000', updated_at = NOW()
 WHERE budget_kind = 'ai' AND operation = 'image_generation' AND unit = 'image'
   AND provider IN ('cloudflare', 'huggingface') AND unit_cost_usd IS NULL;
