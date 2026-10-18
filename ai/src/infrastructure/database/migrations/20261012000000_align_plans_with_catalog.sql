-- Radar's packages now match the existing CEOPRO production plan catalog
-- (catalog version 2026-10-v2), read as a reference from the CEOPRO backend:
--   src/config/production-plans.ts      (prices, trials, billing options, limits)
--   src/modules/features/catalog.ts      (units: rag_assistant = tokens,
--                                         document_extraction = KB, ...)
--   src/modules/subscription/service/plan-pricing.ts (period price formula)
--
--   Starter    55 USD / month, 14-day trial
--   Growth    140 USD / month, 14-day trial
--   Enterprise 350 USD / month, 7-day trial
--   3 months: 10% off, 6 months: 20% off (price = monthly x months x (1 - discount), cents)
--
-- Radar's earlier Standard (49) and Pro (99) packages are retired (kept for
-- history, no longer sold) and companies on them move to Starter and Growth.
-- Custom stays for quoted, non-self-serve deals.

-- Units and the extra metered features the catalog defines.
INSERT INTO usage_features (feature_code, unit, aggregation_type, reset_cycle) VALUES
    ('document_extraction', 'KB', 'sum', 'billing_period'),
    ('sentiment_analysis', 'records', 'sum', 'billing_period'),
    ('connected_data_sources', 'sources', 'max', 'lifetime')
ON CONFLICT (feature_code) DO NOTHING;
UPDATE usage_features SET unit = 'tokens' WHERE feature_code = 'rag_assistant';

-- Included modules (the catalog's on/off features).
CREATE TABLE IF NOT EXISTS usage_plan_entitlements (
    plan_key VARCHAR(50) NOT NULL REFERENCES usage_plans(plan_key) ON DELETE CASCADE,
    feature_code VARCHAR(60) NOT NULL,
    PRIMARY KEY (plan_key, feature_code)
);
-- Shared catalog data like usage_plan_limits: no tenant rows, read-only for the app.
GRANT SELECT ON usage_plan_entitlements TO ceopro_app;

ALTER TABLE usage_plans ADD COLUMN IF NOT EXISTS catalog_version VARCHAR(30);

INSERT INTO usage_plans (plan_key, display_name, display_name_ar, monthly_price, currency, trial_days, tier_level,
                         self_serve, is_active, catalog_version) VALUES
    ('starter', 'Starter', 'البداية', 55, 'USD', 14, 1, TRUE, TRUE, '2026-10-v2'),
    ('growth', 'Growth', 'النمو', 140, 'USD', 14, 2, TRUE, TRUE, '2026-10-v2'),
    ('enterprise', 'Enterprise', 'المؤسسات', 350, 'USD', 7, 3, TRUE, TRUE, '2026-10-v2')
ON CONFLICT (plan_key) DO UPDATE SET
    display_name = EXCLUDED.display_name, display_name_ar = EXCLUDED.display_name_ar,
    monthly_price = EXCLUDED.monthly_price, currency = EXCLUDED.currency, trial_days = EXCLUDED.trial_days,
    tier_level = EXCLUDED.tier_level, self_serve = EXCLUDED.self_serve, is_active = EXCLUDED.is_active,
    catalog_version = EXCLUDED.catalog_version;

UPDATE usage_plans SET tier_level = 4 WHERE plan_key = 'custom';
UPDATE usage_plans SET is_active = FALSE WHERE plan_key IN ('standard', 'pro');

-- Limits exactly as in the catalog. NULL = unlimited; 0 = not included.
-- web_searches and marketing_image_generation exist only in Radar (the
-- catalog has no allowance for them): Starter keeps the old Standard
-- allowance, Growth and Enterprise the old Pro allowance, pending a decision.
INSERT INTO usage_plan_limits (plan_key, feature_code, limit_value) VALUES
    ('starter', 'rag_assistant', 100000), ('starter', 'document_extraction', 51200), ('starter', 'document_storage_mb', 1024),
    ('starter', 'tracked_products', 250), ('starter', 'connected_data_sources', 1),
    ('starter', 'tracked_competitors', 0), ('starter', 'sentiment_analysis', 0),
    ('starter', 'web_searches', 100), ('starter', 'marketing_image_generation', 40),

    ('growth', 'rag_assistant', 500000), ('growth', 'document_extraction', 512000), ('growth', 'document_storage_mb', 10240),
    ('growth', 'tracked_products', 2000), ('growth', 'connected_data_sources', 5),
    ('growth', 'tracked_competitors', 10), ('growth', 'sentiment_analysis', 20000),
    ('growth', 'web_searches', 500), ('growth', 'marketing_image_generation', 200),

    ('enterprise', 'rag_assistant', 2000000), ('enterprise', 'document_extraction', 2097152), ('enterprise', 'document_storage_mb', 51200),
    ('enterprise', 'tracked_products', 10000), ('enterprise', 'connected_data_sources', 20),
    ('enterprise', 'tracked_competitors', 50), ('enterprise', 'sentiment_analysis', 100000),
    ('enterprise', 'web_searches', 500), ('enterprise', 'marketing_image_generation', 200),

    ('custom', 'document_extraction', NULL), ('custom', 'sentiment_analysis', NULL), ('custom', 'connected_data_sources', NULL)
ON CONFLICT (plan_key, feature_code) DO UPDATE SET limit_value = EXCLUDED.limit_value;

INSERT INTO usage_plan_entitlements (plan_key, feature_code)
SELECT p.plan_key, f.code
FROM (VALUES ('starter'), ('growth'), ('enterprise'), ('custom')) AS p(plan_key)
CROSS JOIN (VALUES ('dashboard_analytics'), ('product_management'), ('data_integration')) AS f(code)
UNION ALL
SELECT p.plan_key, f.code
FROM (VALUES ('growth'), ('enterprise'), ('custom')) AS p(plan_key)
CROSS JOIN (VALUES ('market_intelligence'), ('demand_prediction'), ('competitor_management')) AS f(code)
ON CONFLICT DO NOTHING;
-- The retired packages keep every module, so nobody still on them loses access.
INSERT INTO usage_plan_entitlements (plan_key, feature_code)
SELECT p.plan_key, f.code
FROM (VALUES ('standard'), ('pro')) AS p(plan_key)
CROSS JOIN (VALUES ('dashboard_analytics'), ('product_management'), ('data_integration'),
                   ('market_intelligence'), ('demand_prediction'), ('competitor_management')) AS f(code)
ON CONFLICT DO NOTHING;

-- Period prices (Stripe price ids are created by the billing sync, not here).
INSERT INTO billing_plan_prices (plan_key, period_code, interval_months, discount_percent, amount, currency)
SELECT p.plan_key, v.period_code, v.months, v.discount, ROUND(p.monthly_price * v.months * (1 - v.discount / 100.0), 2), p.currency
FROM usage_plans p
CROSS JOIN (VALUES ('monthly', 1, 0), ('three-months', 3, 10), ('six-months', 6, 20)) AS v(period_code, months, discount)
WHERE p.plan_key IN ('starter', 'growth', 'enterprise')
  AND NOT EXISTS (SELECT 1 FROM billing_plan_prices b WHERE b.plan_key = p.plan_key AND b.period_code = v.period_code AND b.retired_at IS NULL);
UPDATE billing_plan_prices SET retired_at = CURRENT_TIMESTAMP
WHERE plan_key IN ('standard', 'pro') AND retired_at IS NULL;

-- Companies on a trial or a manually assigned retired package move to its
-- successor. Paying Stripe subscribers keep the package and price they
-- bought (their entitlements are never changed silently) until they change
-- plan through Billing; their Stripe price still resolves to it.
UPDATE tenant_plan_assignments SET plan_key = CASE plan_key WHEN 'standard' THEN 'starter' ELSE 'growth' END
WHERE plan_key IN ('standard', 'pro') AND COALESCE(source, 'manual') <> 'stripe';
UPDATE billing_trials SET plan_key = CASE plan_key WHEN 'standard' THEN 'starter' ELSE 'growth' END
WHERE plan_key IN ('standard', 'pro');

-- The assistant allowance was counted in questions; it is now counted in
-- tokens, so this period's question counts can't carry over.
DELETE FROM tenant_usage_counters WHERE feature_code = 'rag_assistant'
  AND period_start >= date_trunc('month', CURRENT_DATE)::date;
