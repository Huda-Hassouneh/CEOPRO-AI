-- Tenant notification web/API policies must apply only to ceopro_app.
-- The dedicated notification worker has its own narrow RLS policies.

DROP POLICY IF EXISTS "tenant_notifications_recipient_read"
ON "tenant_notifications";

CREATE POLICY "tenant_notifications_recipient_read"
ON "tenant_notifications"
FOR SELECT
TO ceopro_app
USING (
  "tenant_id" = get_current_tenant()
  AND EXISTS (
    SELECT 1
    FROM "tenant_notification_receipts" r
    WHERE r."tenant_id" = "tenant_notifications"."tenant_id"
      AND r."notification_id" = "tenant_notifications"."id"
      AND r."recipient_user_id" =
        NULLIF(
          current_setting('app.current_user_id', true),
          ''
        )::uuid
  )
);


DROP POLICY IF EXISTS "tenant_notification_receipts_read"
ON "tenant_notification_receipts";

CREATE POLICY "tenant_notification_receipts_read"
ON "tenant_notification_receipts"
FOR SELECT
TO ceopro_app
USING (
  "tenant_id" = get_current_tenant()
  AND "recipient_user_id" =
    NULLIF(
      current_setting('app.current_user_id', true),
      ''
    )::uuid
);


DROP POLICY IF EXISTS "tenant_notification_receipts_update"
ON "tenant_notification_receipts";

CREATE POLICY "tenant_notification_receipts_update"
ON "tenant_notification_receipts"
FOR UPDATE
TO ceopro_app
USING (
  "tenant_id" = get_current_tenant()
  AND "recipient_user_id" =
    NULLIF(
      current_setting('app.current_user_id', true),
      ''
    )::uuid
)
WITH CHECK (
  "tenant_id" = get_current_tenant()
  AND "recipient_user_id" =
    NULLIF(
      current_setting('app.current_user_id', true),
      ''
    )::uuid
);


DROP POLICY IF EXISTS "tenant_notification_outbox_source_insert"
ON "tenant_notification_outbox";

CREATE POLICY "tenant_notification_outbox_source_insert"
ON "tenant_notification_outbox"
FOR INSERT
TO ceopro_app
WITH CHECK (
  "tenant_id" = get_current_tenant()
);


DROP POLICY IF EXISTS "tenant_notification_outbox_source_read"
ON "tenant_notification_outbox";

CREATE POLICY "tenant_notification_outbox_source_read"
ON "tenant_notification_outbox"
FOR SELECT
TO ceopro_app
USING (
  "tenant_id" = get_current_tenant()
);