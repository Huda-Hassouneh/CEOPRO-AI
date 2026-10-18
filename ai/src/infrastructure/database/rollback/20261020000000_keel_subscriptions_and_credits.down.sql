-- Undoes migrations/20261020000000_keel_subscriptions_and_credits.sql. Not
-- applied automatically - run by hand only after deploying the previous
-- application version (the new code needs these tables). Restores the plan
-- catalog it replaced and the 3-argument auth_join_tenant().
--
-- The usage ledger, balances, adjustments and audit log are NOT dropped:
-- they are the financial record of what was spent while this version ran.
-- Drop them separately, after exporting them, only if that record is no
-- longer needed (see docs/SUBSCRIPTIONS_AND_CREDITS.md, "Rollback").

BEGIN;

UPDATE usage_plans SET display_name = 'Starter', display_name_ar = 'البداية', trial_days = 14, catalog_version = 'radar-2026-10' WHERE plan_key = 'starter';
UPDATE usage_plans SET display_name = 'Growth', display_name_ar = 'النمو', trial_days = 14, catalog_version = 'radar-2026-10' WHERE plan_key = 'growth';
UPDATE usage_plans SET display_name = 'Enterprise', display_name_ar = 'المؤسسات', trial_days = 7, catalog_version = 'radar-2026-10' WHERE plan_key = 'enterprise';
UPDATE usage_plans SET display_name = 'Standard', display_name_ar = 'الأساسية' WHERE plan_key = 'standard';
UPDATE usage_plans SET display_name = 'Pro', display_name_ar = 'الاحترافية' WHERE plan_key = 'pro';

UPDATE usage_plan_limits AS l SET limit_value = v.limit_value
FROM (VALUES
    ('starter', 'tracked_products', 250), ('growth', 'tracked_products', 2000), ('enterprise', 'tracked_products', 10000),
    ('starter', 'tracked_competitors', 10), ('growth', 'tracked_competitors', 30), ('enterprise', 'tracked_competitors', 100)
) AS v(plan_key, feature_code, limit_value)
WHERE l.plan_key = v.plan_key AND l.feature_code = v.feature_code;

DELETE FROM usage_plan_limits WHERE feature_code IN ('monthly_reports', 'team_seats', 'data_credits', 'ai_credits');
ALTER TABLE usage_plan_limits DROP COLUMN IF EXISTS trial_limit_value;

DROP FUNCTION IF EXISTS auth_join_tenant(UUID, UUID, VARCHAR, BIGINT);
CREATE OR REPLACE FUNCTION auth_join_tenant(p_tenant_id UUID, p_user_id UUID, p_role_key VARCHAR)
RETURNS VOID
LANGUAGE sql SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO tenant_users (tenant_id, user_id, role_key) VALUES (p_tenant_id, p_user_id, p_role_key)
    ON CONFLICT (tenant_id, user_id) DO UPDATE
        SET role_key = EXCLUDED.role_key, removed_at = NULL, joined_at = CURRENT_TIMESTAMP
        WHERE tenant_users.removed_at IS NOT NULL;
$$;
REVOKE ALL ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_join_tenant(UUID, UUID, VARCHAR) TO ceopro_app;

DELETE FROM schema_migrations WHERE filename = '20261020000000_keel_subscriptions_and_credits.sql';

COMMIT;
