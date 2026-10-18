import { notificationWorkerPrisma } from "../../config/notification-worker-database.js";
import type { PlatformNotificationOutboxEvent } from "./platform-notification.types.js";
type PlatformTenantRow = {
  tenant_id: string;
};
export async function claimDueEvents(
  batchSize = 20
): Promise<PlatformNotificationOutboxEvent[]> {
  return notificationWorkerPrisma.$queryRaw<PlatformNotificationOutboxEvent[]>`
    WITH due AS (
      SELECT "id"
      FROM "platform_notification_outbox"
      WHERE
        "status" IN ('pending', 'processing')
        AND "next_attempt_at" <= CURRENT_TIMESTAMP
      ORDER BY
        "next_attempt_at",
        "id"
      FOR UPDATE SKIP LOCKED
      LIMIT ${batchSize}
    )

    UPDATE "platform_notification_outbox" AS o
    SET
      "status" = 'processing',

      "attempts" =
        o."attempts" + 1,

      "next_attempt_at" =
        CURRENT_TIMESTAMP + INTERVAL '2 minutes'

    FROM due

    WHERE o."id" = due."id"

    RETURNING o.*;
  `;
}

export async function getPlatformTenantId() {
  const rows = await notificationWorkerPrisma.$queryRaw<PlatformTenantRow[]>`
    SELECT "tenant_id"
    FROM "companies"
    WHERE
      "business_type" = 'platform'
      AND "deleted_at" IS NULL
    LIMIT 2
  `;

  if (rows.length !== 1) {
    throw new Error(
      `Expected exactly one active platform tenant, found ${rows.length}`
    );
  }

  return rows[0].tenant_id;
}
