-- Undoes migrations/20261013000000_agreed_plan_limits.sql: restores the plan
-- catalog values it replaced. Not applied automatically - run by hand only
-- if the owner decides to go back. Touches the plan catalog only.
UPDATE usage_plan_limits AS l SET limit_value = v.limit_value
FROM (VALUES
    ('starter', 'tracked_competitors', 0), ('growth', 'tracked_competitors', 10), ('enterprise', 'tracked_competitors', 50),
    ('starter', 'sentiment_analysis', 0), ('growth', 'sentiment_analysis', 20000), ('enterprise', 'sentiment_analysis', 100000),
    ('starter', 'marketing_image_generation', 40), ('growth', 'marketing_image_generation', 200),
    ('enterprise', 'marketing_image_generation', 200)
) AS v(plan_key, feature_code, limit_value)
WHERE l.plan_key = v.plan_key AND l.feature_code = v.feature_code;

DELETE FROM usage_plan_entitlements
WHERE plan_key = 'starter' AND feature_code IN ('market_intelligence', 'demand_prediction', 'competitor_management');

UPDATE usage_plans SET catalog_version = '2026-10-v2' WHERE plan_key IN ('starter', 'growth', 'enterprise');
