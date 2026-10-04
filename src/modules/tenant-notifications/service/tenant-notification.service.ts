import { tenantNotificationRepo } from "../repo/tenant-notification.repo.js";

type NotificationIdentity = {
  tenantId: string;
  recipientUserId: string;
};

type ListNotificationsArgs = NotificationIdentity & {
  limit: number;
  cursor?: string;
  unreadOnly: boolean;
  includeArchived: boolean;
};

type NotificationActionArgs = NotificationIdentity & {
  notificationId: string;
};

async function listNotifications(args: ListNotificationsArgs) {
  return tenantNotificationRepo.listForRecipient(args);
}

async function getUnreadCount(args: NotificationIdentity) {
  return tenantNotificationRepo.countUnreadForRecipient(args);
}

async function markRead(args: NotificationActionArgs) {
  return tenantNotificationRepo.markReadForRecipient(args);
}

async function archive(args: NotificationActionArgs) {
  return tenantNotificationRepo.archiveForRecipient(args);
}

async function markAllRead(args: NotificationIdentity) {
  return tenantNotificationRepo.markAllReadForRecipient(args);
}

export const tenantNotificationService = {
  listNotifications,
  getUnreadCount,
  markRead,
  archive,
  markAllRead
};
