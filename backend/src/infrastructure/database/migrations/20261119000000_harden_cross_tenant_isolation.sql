-- KEEL - Close the cross-tenant gaps the two-company security test found at
-- the database layer (docs/SECURITY_MULTI_TENANT_TEST.md). Every API route
-- already filtered these by company; this makes the database refuse it too,
-- so one missing WHERE can never reach another company.
--
-- 1. auth_tokens had no row-level security: any company's request
--    connection could read every company's pending team invitations
--    (invitee email, role), mark them used or delete them, and re-point
--    its own invitation at another company - a way to join a competitor
--    with the role of its choice. Now a request connection sees only its
--    own company's invitations and its own user's codes. The sign-in
--    flows that run before there is any company (password reset, email
--    verification, invitation links) use db.auth_lookup_connection(),
--    which sets app.auth_lookup = 'on' for its own short-lived session.
--    A connection with no context at all sees nothing.
-- 2. The request role could insert, change and delete shared tables no
--    request writes: what each role means (system_roles), which features
--    each plan has (usage_plan_entitlements), the migration history and
--    the image workers' heartbeats - and could claim any company's image
--    job. Only the schema owner (migrations, workers) writes these now.
-- 3. model_versions kept every company's forecast accuracy figures in one
--    table every company's connection could read. Each row now belongs to
--    the company whose forecast wrote it (set by the database from the
--    connection's own context) and only that company sees it. Earlier rows
--    have no company and stay visible to the schema owner only.

ALTER TABLE auth_tokens ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_tokens_scope ON auth_tokens;
CREATE POLICY auth_tokens_scope ON auth_tokens
    USING (
        current_setting('app.auth_lookup', true) = 'on'
        OR (tenant_id IS NOT NULL AND tenant_id = get_current_tenant())
        OR (tenant_id IS NULL AND user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    );

ALTER TABLE model_versions ADD COLUMN IF NOT EXISTS tenant_id UUID
    DEFAULT get_current_tenant() REFERENCES companies(tenant_id) ON DELETE CASCADE;
ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON model_versions;
CREATE POLICY tenant_isolation ON model_versions
    USING (tenant_id = get_current_tenant())
    WITH CHECK (tenant_id = get_current_tenant());

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ceopro_app') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON system_roles, usage_plan_entitlements, schema_migrations, image_workers
            FROM ceopro_app;
        REVOKE EXECUTE ON FUNCTION claim_image_generation_job(TEXT, INTEGER) FROM ceopro_app;
    END IF;
END $$;
