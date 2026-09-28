-- Add Platform Admin permissions to the existing system_roles.
--
-- IMPORTANT:
-- We MERGE permissions instead of replacing the JSON because legacy
-- permissions such as manage_billing/manage_catalog are still used by
-- tenant-facing routes.

-- ---------------------------------------------------------------------------
-- OWNER
-- ---------------------------------------------------------------------------

UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{"all": true}'::jsonb
WHERE role_key = 'owner';


-- ---------------------------------------------------------------------------
-- ADMIN
-- ---------------------------------------------------------------------------
-- Day-to-day platform administration.
-- Sensitive ownership, role management, pricing-policy management and
-- platform-settings mutation remain owner-only.
UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{
        "platform.overview.read": true,

        "companies.read": true,
        "companies.update": true,
        "companies.status.manage": true,

        "users.read": true,
        "users.manage": true,

        "subscriptions.read": true,

        "billing.read": true,
        "billing.manage": true,

        "adminTeam.read": true,

        "auditLogs.read": true,

        "platformSettings.read": true
    }'::jsonb
WHERE role_key = 'admin';


-- ---------------------------------------------------------------------------
-- MANAGER
-- ---------------------------------------------------------------------------
-- Operational visibility without sensitive administration.
UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{
        "platform.overview.read": true,

        "companies.read": true,

        "users.read": true,

        "subscriptions.read": true,

        "auditLogs.read": true
    }'::jsonb
WHERE role_key = 'manager';


-- ---------------------------------------------------------------------------
-- ACCOUNTANT
-- ---------------------------------------------------------------------------
-- Billing/subscription operations.
-- Pricing policy remains owner-only.
UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{
        "platform.overview.read": true,

        "subscriptions.read": true,

        "billing.read": true,
        "billing.manage": true
    }'::jsonb
WHERE role_key = 'accountant';


-- ---------------------------------------------------------------------------
-- STAFF
-- ---------------------------------------------------------------------------
-- Basic read-only operational access.
UPDATE system_roles
SET permissions =
    COALESCE(permissions, '{}'::jsonb)
    || '{
        "platform.overview.read": true,

        "companies.read": true,

        "users.read": true,

        "subscriptions.read": true
    }'::jsonb
WHERE role_key = 'staff';