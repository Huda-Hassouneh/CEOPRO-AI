import { platformNotificationRepo } from "../repo/platform-notification.repo.js";

type NotificationIdentity = {
  platformTenantId: string;
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
  return platformNotificationRepo.listForRecipient(args);
}

async function getUnreadCount(args: NotificationIdentity) {
  return platformNotificationRepo.countUnreadForRecipient(args);
}

async function markRead(args: NotificationActionArgs) {
  return platformNotificationRepo.markReadForRecipient(args);
}

async function archive(args: NotificationActionArgs) {
  return platformNotificationRepo.archiveForRecipient(args);
}

async function markAllRead(args: NotificationIdentity) {
  return platformNotificationRepo.markAllReadForRecipient(args);
}

export const platformNotificationService = {
  listNotifications,
  getUnreadCount,
  markRead,
  archive,
  markAllRead
};
