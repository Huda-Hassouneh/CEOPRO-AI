export type NotificationPermissionMode = "ANY" | "ALL";

export type GetPlatformNotificationRecipientsArgs = {
  platformTenantId: string;

  /**
   * Business-domain permissions required for this event.
   *
   * Example:
   * PAYMENT_FAILED -> ["billing.read"]
   */
  requiredPermissions: string[];

  /**
   * ANY:
   * User needs at least one required permission.
   *
   * ALL:
   * User needs every required permission.
   */
  permissionMode?: NotificationPermissionMode;
};
