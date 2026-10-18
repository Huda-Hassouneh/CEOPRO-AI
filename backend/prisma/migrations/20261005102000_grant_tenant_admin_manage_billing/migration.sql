-- Tenant administrators are expected to manage their own company's billing.
--
-- Keep tenant billing authorization on the canonical legacy permission
-- `manage_billing`. Platform administration remains separately protected by
-- the platform-tenant boundary plus namespaced permissions such as
-- `billing.manage`.
--
UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{"manage_billing": true}'::jsonb
WHERE role_key = 'admin';
