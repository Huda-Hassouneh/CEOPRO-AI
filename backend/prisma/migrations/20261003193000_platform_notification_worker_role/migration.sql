-- Dedicated runtime identity for the Platform Notification worker.
-- Password is intentionally NOT stored in this migration.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'ceopro_notification_worker'
    ) THEN
        CREATE ROLE ceopro_notification_worker
        WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS;
    END IF;
END
$$;


GRANT USAGE ON SCHEMA public
TO ceopro_notification_worker;


/*
 * ============================================================
 * OUTBOX
 * ============================================================
 *
 * Worker may:
 * - discover due events
 * - claim them
 * - reschedule them
 * - mark them delivered/failed
 */

GRANT SELECT, UPDATE
ON TABLE platform_notification_outbox
TO ceopro_notification_worker;


/*
 * ============================================================
 * FINAL NOTIFICATIONS
 * ============================================================
 *
 * Worker may:
 * - check notification dedupe
 * - create final notification
 *
 * It does NOT need DELETE.
 */

GRANT SELECT, INSERT
ON TABLE platform_notifications
TO ceopro_notification_worker;


/*
 * ============================================================
 * RECEIPTS
 * ============================================================
 *
 * Worker only creates recipient receipts.
 */

GRANT INSERT
ON TABLE platform_notification_receipts
TO ceopro_notification_worker;


/*
 * ============================================================
 * RECIPIENT RESOLUTION
 * ============================================================
 */

GRANT SELECT
ON TABLE companies
TO ceopro_notification_worker;

GRANT SELECT
ON TABLE tenant_users
TO ceopro_notification_worker;

GRANT SELECT
ON TABLE system_roles
TO ceopro_notification_worker;


/*
 * ============================================================
 * RLS: COMPANIES
 * ============================================================
 *
 * Worker only needs to discover the active CEOPRO platform tenant.
 */

CREATE POLICY platform_notification_worker_company_read
ON companies
FOR SELECT
TO ceopro_notification_worker
USING (
    business_type = 'platform'
    AND deleted_at IS NULL
    AND platform_status = 'active'
);


/*
 * ============================================================
 * RLS: PLATFORM MEMBERSHIPS
 * ============================================================
 *
 * Worker only sees memberships belonging to an active
 * platform company.
 */

CREATE POLICY platform_notification_worker_membership_read
ON tenant_users
FOR SELECT
TO ceopro_notification_worker
USING (
    EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id = tenant_users.tenant_id
          AND c.business_type = 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);


/*
 * ============================================================
 * RLS: OUTBOX
 * ============================================================
 */

CREATE POLICY platform_notification_worker_outbox_read
ON platform_notification_outbox
FOR SELECT
TO ceopro_notification_worker
USING (true);


CREATE POLICY platform_notification_worker_outbox_update
ON platform_notification_outbox
FOR UPDATE
TO ceopro_notification_worker
USING (true)
WITH CHECK (true);


/*
 * ============================================================
 * RLS: FINAL NOTIFICATIONS
 * ============================================================
 *
 * The worker may only read/create notifications belonging
 * to the canonical active platform tenant.
 */

CREATE POLICY platform_notification_worker_notification_read
ON platform_notifications
FOR SELECT
TO ceopro_notification_worker
USING (
    EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id =
            platform_notifications.platform_tenant_id
          AND c.business_type = 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);


CREATE POLICY platform_notification_worker_notification_insert
ON platform_notifications
FOR INSERT
TO ceopro_notification_worker
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM companies c
        WHERE c.tenant_id =
            platform_notifications.platform_tenant_id
          AND c.business_type = 'platform'
          AND c.deleted_at IS NULL
          AND c.platform_status = 'active'
    )
);


/*
 * ============================================================
 * RLS: RECEIPTS
 * ============================================================
 *
 * Receipt must belong to an existing notification in the
 * active CEOPRO platform tenant.
 */

CREATE POLICY platform_notification_worker_receipt_insert
ON platform_notification_receipts
FOR INSERT
TO ceopro_notification_worker
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM platform_notifications n
        WHERE n.id =
            platform_notification_receipts.notification_id
          AND n.platform_tenant_id =
            platform_notification_receipts.platform_tenant_id
    )
);