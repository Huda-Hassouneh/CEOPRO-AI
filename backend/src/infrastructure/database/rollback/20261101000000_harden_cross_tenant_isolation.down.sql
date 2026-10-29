-- Undoes migrations/20261101000000_harden_cross_tenant_isolation.sql (reopens the gaps it closed).
DROP POLICY IF EXISTS auth_tokens_scope ON auth_tokens;
ALTER TABLE auth_tokens DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON model_versions;
ALTER TABLE model_versions DISABLE ROW LEVEL SECURITY;
ALTER TABLE model_versions DROP COLUMN IF EXISTS tenant_id;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        GRANT INSERT, UPDATE, DELETE ON system_roles, usage_plan_entitlements, schema_migrations, image_workers TO ceopro_app;
        GRANT EXECUTE ON FUNCTION claim_image_generation_job(TEXT, INTEGER) TO ceopro_app;
    END IF;
END $$;
