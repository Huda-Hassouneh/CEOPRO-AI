-- Extends the existing dedicated notification worker identity so it can
-- dispatch tenant-facing notifications without weakening the normal web role.
--
-- The worker stays NOSUPERUSER / NOBYPASSRLS from
-- 20261003193000_platform_notification_worker_role.

GRANT SELECT, UPDATE
ON TABLE tenant_notification_outbox
TO ceopro_notification_worker;

GRANT SELECT, INSERT
ON TABLE tenant_notifications
TO ceopro_notification_worker;

GRANT INSERT
ON TABLE tenant_notification_receipts
TO ceopro_notification_worker;

-- These grants already exist for platform notifications, but repeating them
-- here makes the tenant notification dependency explicit and remains harmless.
GRANT SELECT
ON TABLE companies, tenant_users, system_roles
TO ceopro_notification_worker;


/*
 * ============================================================
 * RLS: CUSTOMER TENANTS
 * ============================================================
 */

CREATE POLICY tenant_notification_worker_company_read
ON companies
FOR SELECT
TO ceopro_notification_worker
USING (
    business_type IS DISTINCT FROM 'platform'
    AND deleted_at IS NULL
    AND platform_status = 'active'
);

CREATE POLICY tenant_notification_worker_membership_read
ON tenant_users
FOR SELECT
TO ceopro_notification_worker
USING (
    removed_at IS NULL
    AND platform_status = 'active'
    AND EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id = tenant_users.tenant_id
          AND c.business_type IS DISTINCT FROM 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);


/*
 * ============================================================
 * RLS: TENANT NOTIFICATION OUTBOX
 * ============================================================
 */

CREATE POLICY tenant_notification_worker_outbox_read
ON tenant_notification_outbox
FOR SELECT
TO ceopro_notification_worker
USING (true);

CREATE POLICY tenant_notification_worker_outbox_update
ON tenant_notification_outbox
FOR UPDATE
TO ceopro_notification_worker
USING (true)
WITH CHECK (true);


/*
 * ============================================================
 * RLS: FINAL TENANT NOTIFICATIONS
 * ============================================================
 */

CREATE POLICY tenant_notification_worker_notification_read
ON tenant_notifications
FOR SELECT
TO ceopro_notification_worker
USING (
    EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id = tenant_notifications.tenant_id
          AND c.business_type IS DISTINCT FROM 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);

CREATE POLICY tenant_notification_worker_notification_insert
ON tenant_notifications
FOR INSERT
TO ceopro_notification_worker
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id = tenant_notifications.tenant_id
          AND c.business_type IS DISTINCT FROM 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);


/*
 * ============================================================
 * RLS: TENANT NOTIFICATION RECEIPTS
 * ============================================================
 *
 * A receipt can only be created for an active membership in the same tenant
 * as the notification.
 */

CREATE POLICY tenant_notification_worker_receipt_insert
ON tenant_notification_receipts
FOR INSERT
TO ceopro_notification_worker
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM tenant_notifications n
        WHERE n.id = tenant_notification_receipts.notification_id
          AND n.tenant_id = tenant_notification_receipts.tenant_id
    )
    AND EXISTS (
        SELECT 1
        FROM tenant_users tu
        WHERE tu.tenant_id = tenant_notification_receipts.tenant_id
          AND tu.user_id = tenant_notification_receipts.recipient_user_id
          AND tu.removed_at IS NULL
          AND tu.platform_status = 'active'
    )
);


/*
 * ============================================================
 * PLATFORM ADMIN -> TENANT OUTBOX PRODUCER
 * ============================================================
 *
 * A Platform Admin billing action may legitimately produce a notification for
 * a customer tenant, for example CUSTOM_PLAN_OFFER_READY. The normal same-
 * tenant source policy cannot cover that case because the actor's current
 * tenant is the CEOPRO platform tenant, while the target notification belongs
 * to the customer tenant.
 *
 * This policy keeps the producer on ceopro_app (never the worker DB identity)
 * while requiring a verified active platform membership with billing.manage
 * or all permissions.
 */

CREATE POLICY tenant_notification_outbox_platform_source_insert
ON tenant_notification_outbox
FOR INSERT
TO ceopro_app
WITH CHECK (
    get_current_tenant() IS NOT NULL
    AND tenant_id <> get_current_tenant()
    AND EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id = get_current_tenant()
          AND c.business_type = 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
    AND EXISTS (
        SELECT 1
        FROM tenant_users tu
        JOIN system_roles sr
          ON sr.role_key = tu.role_key
        WHERE tu.tenant_id = get_current_tenant()
          AND tu.user_id = NULLIF(
              current_setting('app.current_user_id', true),
              ''
          )::uuid
          AND tu.removed_at IS NULL
          AND tu.platform_status = 'active'
          AND (
              sr.permissions ->> 'all' = 'true'
              OR sr.permissions ->> 'billing.manage' = 'true'
          )
    )
);
