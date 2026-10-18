-- Radar's own plan terms, agreed by the owner (docs/PLAN_LIMITS_FEASIBILITY.md).
-- Prices are unchanged ($55 / $140 / $350). Every plan now includes market
-- intelligence, demand forecasting and competitor tracking; plans differ by
-- capacity. Only the plan catalog changes - no company's data, usage
-- counters or plan assignment is touched. Undo with
-- rollback/20261013000000_agreed_plan_limits.down.sql.
--
--                         Starter   Growth   Enterprise   (was)
--   tracked_competitors        10       30          100   (0 / 10 / 50)
--   sentiment_analysis      5,000   25,000      100,000   (0 / 20,000 / 100,000)
--   marketing images           20      100          150   (40 / 200 / 200)
-- Already matching and left as they are: products 250/2,000/10,000; AI tokens
-- 100k/500k/2M; data sources 1/5/20; storage 1/10/50 GB; uploads
-- 50/500/2,048 MB a month.

UPDATE usage_plan_limits AS l SET limit_value = v.limit_value
FROM (VALUES
    ('starter', 'tracked_competitors', 10), ('growth', 'tracked_competitors', 30), ('enterprise', 'tracked_competitors', 100),
    ('starter', 'sentiment_analysis', 5000), ('growth', 'sentiment_analysis', 25000), ('enterprise', 'sentiment_analysis', 100000),
    ('starter', 'marketing_image_generation', 20), ('growth', 'marketing_image_generation', 100),
    ('enterprise', 'marketing_image_generation', 150)
) AS v(plan_key, feature_code, limit_value)
WHERE l.plan_key = v.plan_key AND l.feature_code = v.feature_code;

INSERT INTO usage_plan_entitlements (plan_key, feature_code)
SELECT 'starter', f.code
FROM (VALUES ('market_intelligence'), ('demand_prediction'), ('competitor_management')) AS f(code)
ON CONFLICT DO NOTHING;

UPDATE usage_plans SET catalog_version = 'radar-2026-10' WHERE plan_key IN ('starter', 'growth', 'enterprise');
