import { notificationWorkerPrisma } from "../../config/notification-worker-database.js";
import type { Prisma } from "../../generated/prisma/client.js";
import { buildPlatformNotification } from "./platform-notification.definition.js";
import { platformNotificationRepo } from "./repo/platform-notification.repo.js";
import type { PlatformNotificationOutboxEvent } from "./platform-notification.types.js";

export async function dispatchPlatformNotification(
  event: PlatformNotificationOutboxEvent
): Promise<void> {
  const definition = buildPlatformNotification(event);

  // event.tenant_id is the source/customer tenant. Recipients always come
  // from the canonical CEOPRO platform tenant.
  const platformTenantId = await platformNotificationRepo.getPlatformTenantId();

  const recipients =
    await platformNotificationRepo.getPlatformNotificationRecipientUserIds({
      platformTenantId,
      requiredPermissions: definition.recipientPolicy.requiredPermissions,
      permissionMode: definition.recipientPolicy.permissionMode
    });

  if (recipients.length === 0) {
    throw new Error(
      `No eligible platform notification recipients for event ${event.event_type}`
    );
  }

  await notificationWorkerPrisma.$transaction(async (tx) => {
    const notification = await platformNotificationRepo.createNotification(tx, {
      platformTenantId,
      sourceTenantId: event.tenant_id,
      eventType: event.event_type,
      severity: definition.severity,
      titleKey: definition.titleKey,
      bodyKey: definition.bodyKey,
      payload: definition.payload as Prisma.InputJsonValue,
      resourceType: definition.resourceType,
      resourceId: definition.resourceId,
      dedupeKey: event.dedupe_key,
      occurredAt: event.occurred_at
    });

    await platformNotificationRepo.createReceipts(tx, {
      notificationId: notification.id,
      platformTenantId,
      recipientUserIds: recipients
    });

    const delivered = await platformNotificationRepo.markOutboxDelivered(
      tx,
      event.id
    );

    if (!delivered) {
      throw new Error(`Outbox event ${event.id} was not in processing state`);
    }
  });

  console.info(
    `[PlatformNotificationWorker] Delivered` +
      ` | event=${event.event_type}` +
      ` | outbox=${event.id}` +
      ` | recipients=${recipients.length}`
  );
}
