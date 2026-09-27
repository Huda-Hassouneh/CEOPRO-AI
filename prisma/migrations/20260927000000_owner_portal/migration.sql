ALTER TABLE "companies" ADD COLUMN "platform_status" VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE "companies" ADD COLUMN "platform_notes" VARCHAR(2000);
ALTER TABLE "users" ADD COLUMN "session_version" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "tenant_users" ADD COLUMN "platform_status" VARCHAR(20) NOT NULL DEFAULT 'active';

CREATE TABLE "platform_invitations" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),
  "tenant_id" UUID NOT NULL,
  "email" VARCHAR(255) NOT NULL,
  "role_key" VARCHAR(50) NOT NULL,
  "token_hash" VARCHAR(64) NOT NULL,
  "invited_by" UUID NOT NULL,
  "status" VARCHAR(20) NOT NULL DEFAULT 'pending',
  "expires_at" TIMESTAMPTZ(6) NOT NULL,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "accepted_at" TIMESTAMPTZ(6),
  CONSTRAINT "platform_invitations_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "platform_invitations_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "companies"("tenant_id") ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "platform_invitations_invited_by_fkey" FOREIGN KEY ("invited_by") REFERENCES "users"("user_id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX "platform_invitations_token_hash_key" ON "platform_invitations"("token_hash");
CREATE INDEX "platform_invitations_tenant_id_status_created_at_idx" ON "platform_invitations"("tenant_id", "status", "created_at");
CREATE INDEX "platform_invitations_tenant_id_email_idx" ON "platform_invitations"("tenant_id", "email");

CREATE TABLE "auth_sessions" (
  "id" UUID NOT NULL DEFAULT gen_random_uuid(),
  "user_id" UUID NOT NULL,
  "tenant_id" UUID NOT NULL,
  "device" VARCHAR(255) NOT NULL,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "last_active" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "expires_at" TIMESTAMPTZ(6) NOT NULL,
  "revoked_at" TIMESTAMPTZ(6),
  CONSTRAINT "auth_sessions_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "auth_sessions_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("user_id") ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "auth_sessions_tenant_id_fkey" FOREIGN KEY ("tenant_id") REFERENCES "companies"("tenant_id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "auth_sessions_user_id_revoked_at_expires_at_idx" ON "auth_sessions"("user_id", "revoked_at", "expires_at");
CREATE INDEX IF NOT EXISTS "subscriptions_owner_portal_latest_idx" ON "subscriptions"("tenant_id", "created_at" DESC, "id" DESC);
