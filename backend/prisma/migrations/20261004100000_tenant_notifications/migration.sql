-- Tenant-facing notification inbox.
--
-- This is intentionally separate from platform_* notifications because:
--   1. tenant notifications use tenant membership/RLS;
--   2. platform notifications use Platform Admin membership/RBAC;
--   3. the two audiences must never leak into each other.
--
-- This migration creates storage + normal application RLS only.
-- Worker-specific cross-tenant permissions should be added separately.

CREATE TABLE "tenant_notifications" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),
  "tenant_id" UUID NOT NULL,

  "event_type" VARCHAR(80) NOT NULL,
  "severity" VARCHAR(20) NOT NULL,

  "title_key" VARCHAR(120) NOT NULL,
  "body_key" VARCHAR(120) NOT NULL,

  "payload" JSONB NOT NULL DEFAULT '{}'::jsonb,

  "resource_type" VARCHAR(80),
  "resource_id" UUID,

  "dedupe_key" VARCHAR(255) NOT NULL,

  "occurred_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "expires_at" TIMESTAMPTZ(6),

  CONSTRAINT "tenant_notifications_pkey"
    PRIMARY KEY ("id"),

  CONSTRAINT "tenant_notifications_severity_check"
    CHECK ("severity" IN ('INFO', 'WARNING', 'CRITICAL')),

  CONSTRAINT "tenant_notifications_tenant_id_fkey"
    FOREIGN KEY ("tenant_id")
    REFERENCES "companies"("tenant_id")
    ON DELETE CASCADE
);

CREATE UNIQUE INDEX "tenant_notifications_tenant_dedupe_key"
  ON "tenant_notifications"("tenant_id", "dedupe_key");

-- Required for the composite FK from receipts.
CREATE UNIQUE INDEX "tenant_notifications_tenant_id_key"
  ON "tenant_notifications"("tenant_id", "id");

CREATE INDEX "tenant_notifications_tenant_created_idx"
  ON "tenant_notifications"(
    "tenant_id",
    "created_at" DESC,
    "id" DESC
  );


-- ============================================================
-- Recipient receipts
-- ============================================================

CREATE TABLE "tenant_notification_receipts" (
  "notification_id" UUID NOT NULL,
  "tenant_id" UUID NOT NULL,
  "recipient_user_id" UUID NOT NULL,

  "read_at" TIMESTAMPTZ(6),
  "archived_at" TIMESTAMPTZ(6),

  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT "tenant_notification_receipts_pkey"
    PRIMARY KEY ("notification_id", "recipient_user_id"),

  CONSTRAINT "tenant_notification_receipts_notification_fkey"
    FOREIGN KEY ("tenant_id", "notification_id")
    REFERENCES "tenant_notifications"("tenant_id", "id")
    ON DELETE CASCADE,

  -- Important:
  -- the recipient must actually belong to the SAME tenant.
  CONSTRAINT "tenant_notification_receipts_membership_fkey"
    FOREIGN KEY ("tenant_id", "recipient_user_id")
    REFERENCES "tenant_users"("tenant_id", "user_id")
    ON DELETE CASCADE
);

CREATE INDEX "tenant_notification_receipts_inbox_idx"
  ON "tenant_notification_receipts"(
    "recipient_user_id",
    "tenant_id",
    "archived_at",
    "read_at",
    "notification_id"
  );


-- ============================================================
-- Durable event outbox
-- ============================================================

CREATE TABLE "tenant_notification_outbox" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),
  "tenant_id" UUID NOT NULL,

  "event_type" VARCHAR(80) NOT NULL,
  "dedupe_key" VARCHAR(255) NOT NULL,

  "payload" JSONB NOT NULL DEFAULT '{}'::jsonb,

  "status" VARCHAR(20) NOT NULL DEFAULT 'pending',
  "attempts" INTEGER NOT NULL DEFAULT 0,

  "next_attempt_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "delivered_at" TIMESTAMPTZ(6),

  "last_error_code" VARCHAR(100),

  "occurred_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT "tenant_notification_outbox_pkey"
    PRIMARY KEY ("id"),

  CONSTRAINT "tenant_notification_outbox_tenant_id_fkey"
    FOREIGN KEY ("tenant_id")
    REFERENCES "companies"("tenant_id")
    ON DELETE CASCADE,

  CONSTRAINT "tenant_notification_outbox_status_check"
    CHECK (
      "status" IN (
        'pending',
        'processing',
        'delivered',
        'failed'
      )
    ),

  CONSTRAINT "tenant_notification_outbox_attempts_check"
    CHECK ("attempts" >= 0)
);

CREATE UNIQUE INDEX "tenant_notification_outbox_tenant_dedupe_key"
  ON "tenant_notification_outbox"(
    "tenant_id",
    "dedupe_key"
  );

CREATE INDEX "tenant_notification_outbox_due_idx"
  ON "tenant_notification_outbox"(
    "next_attempt_at",
    "id"
  )
  WHERE "status" IN ('pending', 'processing');


-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE "tenant_notifications"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tenant_notifications"
  FORCE ROW LEVEL SECURITY;

ALTER TABLE "tenant_notification_receipts"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tenant_notification_receipts"
  FORCE ROW LEVEL SECURITY;

ALTER TABLE "tenant_notification_outbox"
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE "tenant_notification_outbox"
  FORCE ROW LEVEL SECURITY;


-- ============================================================
-- Normal application policies
-- ============================================================

-- A user may only read notifications for which they actually have
-- a recipient receipt inside their active tenant.
CREATE POLICY "tenant_notifications_recipient_read"
ON "tenant_notifications"
FOR SELECT
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


-- Users can only see their own receipt.
CREATE POLICY "tenant_notification_receipts_read"
ON "tenant_notification_receipts"
FOR SELECT
USING (
  "tenant_id" = get_current_tenant()
  AND "recipient_user_id" =
    NULLIF(
      current_setting('app.current_user_id', true),
      ''
    )::uuid
);


-- Users can mark only their own receipt read/archive.
CREATE POLICY "tenant_notification_receipts_update"
ON "tenant_notification_receipts"
FOR UPDATE
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


-- Business transactions running as the normal application role
-- may insert events only for their current tenant.
CREATE POLICY "tenant_notification_outbox_source_insert"
ON "tenant_notification_outbox"
FOR INSERT
WITH CHECK (
  "tenant_id" = get_current_tenant()
);


-- SELECT is useful for Prisma INSERT ... RETURNING and for safe
-- tenant-local idempotency/retry handling.
CREATE POLICY "tenant_notification_outbox_source_read"
ON "tenant_notification_outbox"
FOR SELECT
USING (
  "tenant_id" = get_current_tenant()
);


-- ============================================================
-- Normal web application DB privileges
-- ============================================================

REVOKE ALL
ON TABLE
  "tenant_notifications",
  "tenant_notification_receipts",
  "tenant_notification_outbox"
FROM ceopro_app;

GRANT SELECT
ON TABLE
  "tenant_notifications",
  "tenant_notification_receipts"
TO ceopro_app;

GRANT UPDATE ("read_at", "archived_at")
ON TABLE "tenant_notification_receipts"
TO ceopro_app;

GRANT SELECT, INSERT
ON TABLE "tenant_notification_outbox"
TO ceopro_app;