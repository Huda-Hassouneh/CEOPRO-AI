import { notificationWorkerPrisma } from "../../config/notification-worker-database.js";
import type { Prisma } from "../../generated/prisma/client.js";
import { buildTenantNotification } from "./tenant-notification.definition.js";
import { tenantNotificationRepo } from "./repo/tenant-notification.repo.js";
import type { TenantNotificationOutboxEvent } from "./tenant-notification.types.js";

export async function dispatchTenantNotification(
  event: TenantNotificationOutboxEvent
): Promise<void> {
  const definition = buildTenantNotification(event);

  const recipients =
    await tenantNotificationRepo.getTenantNotificationRecipientUserIds({
      tenantId: event.tenant_id,
      requiredPermissions: definition.recipientPolicy.requiredPermissions,
      permissionMode: definition.recipientPolicy.permissionMode
    });

  if (recipients.length === 0) {
    throw new Error(
      `No eligible tenant notification recipients for event ${event.event_type}`
    );
  }

  await notificationWorkerPrisma.$transaction(async (tx) => {
    const notification = await tenantNotificationRepo.createNotification(tx, {
      tenantId: event.tenant_id,
      eventType: event.event_type,
      severity: definition.severity,
      titleKey: definition.titleKey,
      bodyKey: definition.bodyKey,
      payload: definition.payload as Prisma.InputJsonValue,
      resourceType: definition.resourceType,
      resourceId: definition.resourceId,
      expiresAt: definition.expiresAt,
      dedupeKey: event.dedupe_key,
      occurredAt: event.occurred_at
    });

    await tenantNotificationRepo.createReceipts(tx, {
      notificationId: notification.id,
      tenantId: event.tenant_id,
      recipientUserIds: recipients
    });

    const delivered = await tenantNotificationRepo.markOutboxDelivered(
      tx,
      event.id
    );

    if (!delivered) {
      throw new Error(`Outbox event ${event.id} was not in processing state`);
    }
  });

  console.info(
    `[TenantNotificationWorker] Delivered` +
      ` | event=${event.event_type}` +
      ` | outbox=${event.id}` +
      ` | tenant=${event.tenant_id}` +
      ` | recipients=${recipients.length}`
  );
}
