-- Platform administration inbox. Apply after 20260927000000_owner_portal.
-- This migration creates storage only; producers, dispatcher, APIs and the UI
-- must be deployed separately.
--
-- Runtime web requests must never bypass tenant isolation.
-- A trusted notification dispatcher/worker must receive its own narrowly scoped
-- database privileges in a separately reviewed implementation step.


-- ============================================================
-- 1. FINISHED PLATFORM NOTIFICATIONS
-- ============================================================

CREATE TABLE "platform_notifications" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),

  -- Platform tenant whose admins receive this notification.
  "platform_tenant_id" UUID NOT NULL,

  -- Optional source/customer tenant that caused the event.
  "source_tenant_id" UUID,

  "event_type" VARCHAR(80) NOT NULL,
  "severity" VARCHAR(20) NOT NULL,

  -- i18n keys. The frontend resolves these using payload values.
  "title_key" VARCHAR(120) NOT NULL,
  "body_key" VARCHAR(120) NOT NULL,

  "payload" JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Optional resource the notification points to.
  "resource_type" VARCHAR(80),
  "resource_id" UUID,

  -- Prevent duplicate finished notifications within the platform tenant.
  "dedupe_key" VARCHAR(255) NOT NULL,

  -- When the underlying business event actually happened.
  "occurred_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- When this notification record was created.
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Optional expiry for old/transient notifications.
  "expires_at" TIMESTAMPTZ(6),

  CONSTRAINT "platform_notifications_pkey"
    PRIMARY KEY ("id"),

  CONSTRAINT "platform_notifications_severity_check"
    CHECK ("severity" IN ('INFO', 'WARNING', 'CRITICAL')),

  CONSTRAINT "platform_notifications_platform_tenant_id_fkey"
    FOREIGN KEY ("platform_tenant_id")
    REFERENCES "companies"("tenant_id")
    ON DELETE RESTRICT,

  CONSTRAINT "platform_notifications_source_tenant_id_fkey"
    FOREIGN KEY ("source_tenant_id")
    REFERENCES "companies"("tenant_id")
    ON DELETE SET NULL
);


CREATE UNIQUE INDEX "platform_notifications_platform_dedupe_key"
  ON "platform_notifications"(
    "platform_tenant_id",
    "dedupe_key"
  );


-- Required for the composite FK from receipts.
CREATE UNIQUE INDEX "platform_notifications_platform_id_key"
  ON "platform_notifications"(
    "platform_tenant_id",
    "id"
  );


CREATE INDEX "platform_notifications_platform_created_idx"
  ON "platform_notifications"(
    "platform_tenant_id",
    "created_at" DESC,
    "id" DESC
  );


-- ============================================================
-- 2. PER-ADMIN NOTIFICATION STATE
-- ============================================================

CREATE TABLE "platform_notification_receipts" (
  "notification_id" UUID NOT NULL,
  "platform_tenant_id" UUID NOT NULL,
  "recipient_user_id" UUID NOT NULL,

  "read_at" TIMESTAMPTZ(6),
  "archived_at" TIMESTAMPTZ(6),

  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT "platform_notification_receipts_pkey"
    PRIMARY KEY (
      "notification_id",
      "recipient_user_id"
    ),

  CONSTRAINT "platform_notification_receipts_notification_fkey"
    FOREIGN KEY (
      "platform_tenant_id",
      "notification_id"
    )
    REFERENCES "platform_notifications"(
      "platform_tenant_id",
      "id"
    )
    ON DELETE CASCADE,

  CONSTRAINT "platform_notification_receipts_user_fkey"
    FOREIGN KEY ("recipient_user_id")
    REFERENCES "users"("user_id")
    ON DELETE CASCADE
);


CREATE INDEX "platform_notification_receipts_inbox_idx"
  ON "platform_notification_receipts"(
    "recipient_user_id",
    "platform_tenant_id",
    "archived_at",
    "read_at",
    "notification_id"
  );


-- ============================================================
-- 3. DURABLE SOURCE-SIDE OUTBOX
-- ============================================================

-- Source-side durable work item.
--
-- Business services write events here inside the same transaction as the
-- business change. A trusted notification dispatcher later converts these
-- events into platform_notifications + platform_notification_receipts.
--
-- Dispatcher privileges are intentionally NOT granted in this migration.

CREATE TABLE "platform_notification_outbox" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),

  -- Tenant in whose business context the event occurred.
  "tenant_id" UUID NOT NULL,

  "event_type" VARCHAR(80) NOT NULL,

  -- Idempotency/deduplication key scoped to tenant.
  "dedupe_key" VARCHAR(255) NOT NULL,

  "payload" JSONB NOT NULL DEFAULT '{}'::jsonb,

  "status" VARCHAR(20) NOT NULL DEFAULT 'pending',

  "attempts" INTEGER NOT NULL DEFAULT 0,

  -- When the underlying business event actually happened.
  "occurred_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Used for retry/backoff scheduling.
  "next_attempt_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- When the dispatcher successfully completed the event.
  "delivered_at" TIMESTAMPTZ(6),

  -- Stable/internal error code from the last failed attempt.
  "last_error_code" VARCHAR(100),

  -- When this outbox row itself was inserted.
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT "platform_notification_outbox_pkey"
    PRIMARY KEY ("id"),

  CONSTRAINT "platform_notification_outbox_tenant_id_fkey"
    FOREIGN KEY ("tenant_id")
    REFERENCES "companies"("tenant_id")
    ON DELETE RESTRICT,

  CONSTRAINT "platform_notification_outbox_status_check"
    CHECK (
      "status" IN (
        'pending',
        'processing',
        'delivered',
        'failed'
      )
    ),

  CONSTRAINT "platform_notification_outbox_attempts_check"
    CHECK ("attempts" >= 0)
);


-- Dedupe is tenant-scoped rather than global.
--
-- Example:
-- tenant A + payment_failed:invoice-123  -> allowed
-- tenant B + payment_failed:invoice-123  -> also allowed
--
-- But inserting the same key twice for tenant A is rejected.
CREATE UNIQUE INDEX "platform_notification_outbox_tenant_dedupe_key"
  ON "platform_notification_outbox"(
    "tenant_id",
    "dedupe_key"
  );


-- Efficient worker lookup for currently actionable rows.
CREATE INDEX "platform_notification_outbox_due_idx"
  ON "platform_notification_outbox"(
    "next_attempt_at",
    "id"
  )
  WHERE "status" IN ('pending', 'processing');


-- ============================================================
-- 4. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE "platform_notifications"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "platform_notifications"
  FORCE ROW LEVEL SECURITY;


ALTER TABLE "platform_notification_receipts"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "platform_notification_receipts"
  FORCE ROW LEVEL SECURITY;


ALTER TABLE "platform_notification_outbox"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "platform_notification_outbox"
  FORCE ROW LEVEL SECURITY;


-- ============================================================
-- 5. RUNTIME WEB-APP POLICIES
-- ============================================================

-- Runtime reads require the active transaction/session tenant to be the real
-- platform tenant.
--
-- No normal web-app INSERT policy is provided for notifications or receipts.
-- Those rows must be produced by a separately trusted dispatcher.

CREATE POLICY "platform_notifications_read"
  ON "platform_notifications"
  FOR SELECT
  USING (
    "platform_tenant_id" = get_current_tenant()

    AND EXISTS (
      SELECT 1
      FROM "companies" c
      WHERE c."tenant_id" = "platform_tenant_id"
        AND c."business_type" = 'platform'
        AND c."deleted_at" IS NULL
    )
  );


-- A platform user may only read their own receipt rows.

CREATE POLICY "platform_notification_receipts_read"
  ON "platform_notification_receipts"
  FOR SELECT
  USING (
    "platform_tenant_id" = get_current_tenant()

    AND "recipient_user_id" =
      NULLIF(
        current_setting('app.current_user_id', true),
        ''
      )::uuid

    AND EXISTS (
      SELECT 1
      FROM "platform_notifications" n
      WHERE n."id" =
        "platform_notification_receipts"."notification_id"

        AND n."platform_tenant_id" =
        "platform_notification_receipts"."platform_tenant_id"
    )
  );


-- Runtime admins may only update their own read/archive state.

CREATE POLICY "platform_notification_receipts_update"
  ON "platform_notification_receipts"
  FOR UPDATE
  USING (
    "platform_tenant_id" = get_current_tenant()

    AND "recipient_user_id" =
      NULLIF(
        current_setting('app.current_user_id', true),
        ''
      )::uuid
  )
  WITH CHECK (
    "platform_tenant_id" = get_current_tenant()

    AND "recipient_user_id" =
      NULLIF(
        current_setting('app.current_user_id', true),
        ''
      )::uuid
  );


-- Source-side business services may inspect their own outbox events.

CREATE POLICY "platform_notification_outbox_source_read"
  ON "platform_notification_outbox"
  FOR SELECT
  USING (
    "tenant_id" = get_current_tenant()
  );


-- Source-side business services may insert outbox events only for the currently
-- authenticated tenant context.

CREATE POLICY "platform_notification_outbox_source_insert"
  ON "platform_notification_outbox"
  FOR INSERT
  WITH CHECK (
    "tenant_id" = get_current_tenant()
  );


-- ============================================================
-- 6. WEB APPLICATION DATABASE PRIVILEGES
-- ============================================================

-- Prior app-role migrations may grant broad/default table privileges.
-- Narrow these tables explicitly.
--
-- The normal web application:
--   - may read finished notifications
--   - may read its own receipts
--   - may only update read_at / archived_at
--   - may insert source-side outbox events
--
-- It may NOT:
--   - insert final notifications
--   - insert receipts
--   - update dispatcher state
--   - perform cross-tenant notification dispatch

REVOKE ALL
  ON TABLE
    "platform_notifications",
    "platform_notification_receipts",
    "platform_notification_outbox"
  FROM ceopro_app;


GRANT SELECT
  ON TABLE
    "platform_notifications",
    "platform_notification_receipts"
  TO ceopro_app;


GRANT UPDATE (
    "read_at",
    "archived_at"
  )
  ON TABLE "platform_notification_receipts"
  TO ceopro_app;


GRANT SELECT, INSERT
  ON TABLE "platform_notification_outbox"
  TO ceopro_app;