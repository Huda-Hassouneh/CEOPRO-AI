-- Plan allowances revised for APEX (see CURRENT_STATUS.md, "Plans").
-- Competitors: 5 could not cover even one realistic shop (market-wide rivals
-- plus product specialists); storing them is cheap, automated monitoring is
-- metered separately (web_searches). AI questions: about 5.5k tokens each, so
-- 400 / 2,000 a month stays well inside the plan price even on a premium
-- model. Products: forecasting costs about 2 s of CPU per product per
-- refresh, hence a modest Standard increase. Technical safety limits (upload
-- size, per-minute AI cap) are separate and unchanged.
UPDATE usage_plan_limits SET limit_value = v.limit_value
FROM (VALUES
    ('standard', 'tracked_products', 150),
    ('standard', 'tracked_competitors', 15),
    ('standard', 'rag_assistant', 400),
    ('standard', 'web_searches', 100),
    ('standard', 'marketing_image_generation', 40),
    ('pro', 'tracked_competitors', 60),
    ('pro', 'rag_assistant', 2000),
    ('pro', 'web_searches', 500)
) AS v(plan_key, feature_code, limit_value)
WHERE usage_plan_limits.plan_key = v.plan_key AND usage_plan_limits.feature_code = v.feature_code;
